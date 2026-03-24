from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pandas as pd

WSL_DISTRO = "Ubuntu"
WSL_RAPIDS_ENV = "rapids"
CONDA_INIT_PATH = "$HOME/miniforge3/etc/profile.d/conda.sh"
WSL_SETUP_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wsl_cudf_groupby.py"


@dataclass(frozen=True)
class AccelerationStatus:
    backend: str
    label: str
    detail: str
    gpu_detected: bool
    gpu_enabled: bool
    execution_target: str
    wsl_enabled: bool


def detect_acceleration(prefer_gpu: bool = True) -> AccelerationStatus:
    return _detect_acceleration_cached(prefer_gpu)


@lru_cache(maxsize=4)
def _detect_acceleration_cached(prefer_gpu: bool = True) -> AccelerationStatus:
    gpu_detected = shutil.which("nvidia-smi") is not None
    cudf_available = importlib.util.find_spec("cudf") is not None
    wsl_cudf_available = _detect_wsl_cudf()

    if prefer_gpu and gpu_detected and cudf_available:
        return AccelerationStatus(
            backend="gpu-cudf",
            label="GPU acceleration active",
            detail="cuDF is installed and an NVIDIA GPU is available, so large aggregation steps can run on the GPU.",
            gpu_detected=True,
            gpu_enabled=True,
            execution_target="windows-native",
            wsl_enabled=False,
        )

    if prefer_gpu and gpu_detected and wsl_cudf_available:
        return AccelerationStatus(
            backend="gpu-wsl-cudf",
            label="GPU acceleration active",
            detail="cuDF is available in WSL Ubuntu, so heavy aggregation steps and core row-level recommendation math are running on the GPU through RAPIDS while the dashboard stays on Windows.",
            gpu_detected=True,
            gpu_enabled=True,
            execution_target="wsl-ubuntu",
            wsl_enabled=True,
        )

    if prefer_gpu and gpu_detected and not cudf_available:
        return AccelerationStatus(
            backend="cpu-pandas",
            label="CPU processing active",
            detail="An NVIDIA GPU is available, but no usable cuDF runtime was found for this Python environment, so the app is using pandas on the CPU.",
            gpu_detected=True,
            gpu_enabled=False,
            execution_target="windows-native",
            wsl_enabled=False,
        )

    if prefer_gpu and not gpu_detected:
        return AccelerationStatus(
            backend="cpu-pandas",
            label="CPU processing active",
            detail="No compatible NVIDIA GPU was detected, so the app is using pandas on the CPU.",
            gpu_detected=False,
            gpu_enabled=False,
            execution_target="windows-native",
            wsl_enabled=False,
        )

    return AccelerationStatus(
        backend="cpu-pandas",
        label="CPU processing active",
        detail="GPU acceleration is turned off, so the app is using pandas on the CPU.",
        gpu_detected=gpu_detected,
        gpu_enabled=False,
        execution_target="windows-native",
        wsl_enabled=False,
    )


def aggregate_monthly_sum(
    frame: pd.DataFrame,
    group_columns: list[str],
    value_columns: list[str],
    acceleration: AccelerationStatus,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*group_columns, *value_columns])

    selected = frame[group_columns + value_columns].copy()

    if acceleration.gpu_enabled:
        if acceleration.backend == "gpu-wsl-cudf":
            try:
                return _aggregate_monthly_sum_wsl_cudf(selected, group_columns, value_columns)
            except Exception:
                pass
        try:
            import cudf  # type: ignore

            gpu_frame = cudf.from_pandas(selected)
            grouped = gpu_frame.groupby(group_columns, dropna=False)[value_columns].sum().reset_index()
            return grouped.to_pandas()
        except Exception:
            pass

    return (
        selected.groupby(group_columns, dropna=False)[value_columns]
        .sum(numeric_only=True)
        .reset_index()
    )


def _detect_wsl_cudf() -> bool:
    if shutil.which("wsl") is None:
        return False

    check_command = (
        f"source {CONDA_INIT_PATH} >/dev/null 2>&1 && "
        f"conda run -n {WSL_RAPIDS_ENV} python -c \"import cudf\" >/dev/null 2>&1"
    )
    try:
        result = subprocess.run(
            ["wsl", "-d", WSL_DISTRO, "bash", "-lc", check_command],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def _aggregate_monthly_sum_wsl_cudf(
    frame: pd.DataFrame,
    group_columns: list[str],
    value_columns: list[str],
) -> pd.DataFrame:
    if not WSL_SETUP_SCRIPT.exists():
        raise FileNotFoundError(f"WSL cuDF helper script not found: {WSL_SETUP_SCRIPT}")

    with tempfile.TemporaryDirectory(prefix="deviation_dash_wsl_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "aggregate_input.parquet"
        output_path = temp_path / "aggregate_output.parquet"
        frame.to_parquet(input_path, index=False)

        script_path = _windows_to_wsl_path(WSL_SETUP_SCRIPT)
        input_wsl = _windows_to_wsl_path(input_path)
        output_wsl = _windows_to_wsl_path(output_path)
        command_parts = [
            f"source {CONDA_INIT_PATH}",
            "&&",
            f"conda run -n {WSL_RAPIDS_ENV} python { _shell_quote(script_path) }",
            "--input",
            _shell_quote(input_wsl),
            "--output",
            _shell_quote(output_wsl),
        ]
        for column in group_columns:
            command_parts.extend(["--group-column", _shell_quote(column)])
        for column in value_columns:
            command_parts.extend(["--value-column", _shell_quote(column)])
        command = " ".join(command_parts)

        run_wsl_rapids_script(WSL_SETUP_SCRIPT, command_arguments=[
            "--input",
            input_wsl,
            "--output",
            output_wsl,
            *[value for column in group_columns for value in ("--group-column", column)],
            *[value for column in value_columns for value in ("--value-column", column)],
        ], timeout_seconds=600)

        return pd.read_parquet(output_path)


def _windows_to_wsl_path(path: Path) -> str:
    resolved = str(path.resolve())
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", resolved)
    if not match:
        return resolved.replace("\\", "/")
    drive = match.group(1).lower()
    rest = match.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def _shell_quote(value: object) -> str:
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


def windows_to_wsl_path(path: Path) -> str:
    return _windows_to_wsl_path(path)


def run_wsl_rapids_script(
    script_path: Path,
    command_arguments: list[object],
    timeout_seconds: int = 600,
) -> subprocess.CompletedProcess[str]:
    script_wsl = _windows_to_wsl_path(script_path)
    command_parts = [
        f"source {CONDA_INIT_PATH}",
        "&&",
        f"conda run -n {WSL_RAPIDS_ENV} python {_shell_quote(script_wsl)}",
        *(_shell_quote(argument) for argument in command_arguments),
    ]
    command = " ".join(command_parts)
    result = subprocess.run(
        ["wsl", "-d", WSL_DISTRO, "bash", "-lc", command],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(
            f"WSL RAPIDS script failed for {script_path.name}. stdout={stdout!r} stderr={stderr!r}"
        )
    return result
