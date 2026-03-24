from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
import importlib.util
import json

import pandas as pd

try:
    from .data_loader import load_data_workbook
    from .recommendations import _apply_status_rules, _is_dc_location
except ImportError:
    from data_loader import load_data_workbook
    from recommendations import _apply_status_rules, _is_dc_location


FORECAST_FILENAME = "forecast_latest.csv"
METADATA_FILENAME = "forecast_metadata.json"
LEADERBOARD_FILENAME = "leaderboard.csv"
PREDICTOR_DIRNAME = "predictor"


@dataclass(frozen=True)
class AutoGluonStatus:
    installed: bool
    detail: str


@dataclass(frozen=True)
class SavedForecastArtifact:
    forecasts: pd.DataFrame
    metadata: dict[str, object]
    model_dir: Path


def detect_autogluon() -> AutoGluonStatus:
    installed = importlib.util.find_spec("autogluon.timeseries") is not None
    if installed:
        return AutoGluonStatus(
            installed=True,
            detail="AutoGluon TimeSeries is installed and ready for model training and inference.",
        )
    return AutoGluonStatus(
        installed=False,
        detail="AutoGluon TimeSeries is not installed yet. Install the optional AutoGluon requirements before training.",
    )


def default_model_dir(project_root: Path) -> Path:
    return project_root / "models" / "autogluon"


def forecast_file_path(model_dir: Path) -> Path:
    return model_dir / FORECAST_FILENAME


def metadata_file_path(model_dir: Path) -> Path:
    return model_dir / METADATA_FILENAME


def make_item_id(supplier: object, item: object, location: object) -> str:
    return f"{str(supplier or '').strip()} | {str(item or '').strip()} | {str(location or '').strip()}"


def split_item_id(item_id: object) -> tuple[str, str, str]:
    text = str(item_id or "")
    parts = text.split(" | ")
    if len(parts) >= 3:
        return parts[0], parts[1], " | ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return text, "", ""


def ordered_month_labels(monthly_columns: list[str]) -> list[str]:
    def sort_key(label: str) -> tuple[int, datetime | str]:
        try:
            return (0, datetime.strptime(label, "%b-%y"))
        except ValueError:
            return (1, label)

    return [label for label in sorted(monthly_columns, key=sort_key)]


def month_label_to_timestamp(label: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(datetime.strptime(label, "%b-%y").replace(day=1))
    except ValueError:
        return pd.Timestamp(label)


def build_training_frames(
    data: pd.DataFrame,
    monthly_columns: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    filtered = _apply_status_rules(data)
    if filtered.empty:
        return pd.DataFrame(columns=["item_id", "timestamp", "target"]), pd.DataFrame(columns=[])

    month_order = ordered_month_labels(monthly_columns)
    long_records: list[dict[str, object]] = []
    static_records: list[dict[str, object]] = []

    for row in filtered.to_dict(orient="records"):
        item_id = make_item_id(row.get("supplier"), row.get("item"), row.get("location"))
        static_records.append(
            {
                "item_id": item_id,
                "supplier": row.get("supplier", ""),
                "item": row.get("item", ""),
                "location": row.get("location", ""),
                "prod_group": row.get("prod_group", ""),
                "abc": row.get("abc", ""),
                "season": row.get("season", ""),
                "frequency": row.get("frequency", ""),
                "lead_time": float(row.get("lead_time", 0.0) or 0.0),
                "is_dc": int(_is_dc_location(row.get("location"), row.get("supplier"))),
            }
        )
        for month_label in month_order:
            long_records.append(
                {
                    "item_id": item_id,
                    "timestamp": month_label_to_timestamp(month_label),
                    "target": float(row.get(month_label, 0.0) or 0.0),
                }
            )

    long_frame = pd.DataFrame(long_records)
    static_frame = pd.DataFrame(static_records).drop_duplicates(subset=["item_id"]).set_index("item_id")
    return long_frame, static_frame


def build_forecast_lookup(forecasts: pd.DataFrame) -> dict[tuple[str, str, str], float]:
    if forecasts.empty:
        return {}

    frame = forecasts.copy()
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.sort_values(["supplier", "item", "location", "timestamp"], kind="stable")
    else:
        frame = frame.sort_values(["supplier", "item", "location"], kind="stable")

    lookup: dict[tuple[str, str, str], float] = {}
    for row in frame.to_dict(orient="records"):
        key = (str(row.get("supplier", "")), str(row.get("item", "")), str(row.get("location", "")))
        if key not in lookup:
            lookup[key] = float(row.get("forecast_mean", row.get("mean", 0.0)) or 0.0)
    return lookup


def load_saved_forecast_artifact(model_dir: Path) -> SavedForecastArtifact | None:
    forecast_path = forecast_file_path(model_dir)
    metadata_path = metadata_file_path(model_dir)

    if not forecast_path.exists():
        return None

    forecasts = pd.read_csv(forecast_path)
    metadata: dict[str, object] = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    return SavedForecastArtifact(forecasts=forecasts, metadata=metadata, model_dir=model_dir)


def train_predictor_from_workbook(
    file_bytes: bytes,
    source_name: str,
    model_dir: Path,
    time_limit: int = 1800,
    prediction_length: int = 1,
    presets: str = "medium_quality",
) -> dict[str, object]:
    status = detect_autogluon()
    if not status.installed:
        raise RuntimeError(status.detail)

    from autogluon.timeseries import TimeSeriesDataFrame, TimeSeriesPredictor

    loaded = load_data_workbook(file_bytes, source_name)
    train_frame, static_frame = build_training_frames(loaded.data, loaded.monthly_columns)
    if train_frame.empty:
        raise RuntimeError("No eligible time series were found after applying the current status and location rules.")

    predictor_path = model_dir / PREDICTOR_DIRNAME
    predictor_path.parent.mkdir(parents=True, exist_ok=True)

    train_data = TimeSeriesDataFrame.from_data_frame(
        train_frame,
        id_column="item_id",
        timestamp_column="timestamp",
    )
    if not static_frame.empty:
        train_data.static_features = static_frame

    predictor = TimeSeriesPredictor(
        prediction_length=prediction_length,
        target="target",
        eval_metric="MASE",
        path=str(predictor_path),
    )
    predictor.fit(
        train_data=train_data,
        presets=presets,
        time_limit=time_limit,
    )

    predictions = predictor.predict(train_data)
    forecast_frame = predictions.reset_index()
    forecast_frame = forecast_frame.rename(columns={"mean": "forecast_mean"})
    forecast_frame["timestamp"] = pd.to_datetime(forecast_frame["timestamp"], errors="coerce")
    item_parts = pd.DataFrame(
        forecast_frame["item_id"].map(split_item_id).tolist(),
        columns=["supplier", "item", "location"],
        index=forecast_frame.index,
    )
    forecast_frame[["supplier", "item", "location"]] = item_parts
    ordered_columns = [
        "supplier",
        "item",
        "location",
        "timestamp",
        "forecast_mean",
        "0.1",
        "0.5",
        "0.9",
        "item_id",
    ]
    forecast_export = forecast_frame[[column for column in ordered_columns if column in forecast_frame.columns]].copy()
    forecast_export.to_csv(forecast_file_path(model_dir), index=False)

    leaderboard = predictor.leaderboard(train_data, silent=True)
    leaderboard.to_csv(model_dir / LEADERBOARD_FILENAME, index=False)

    metadata = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "source_name": source_name,
        "prediction_length": prediction_length,
        "time_limit_seconds": time_limit,
        "presets": presets,
        "series_count": int(train_frame["item_id"].nunique()),
        "training_rows": int(len(train_frame)),
        "monthly_columns": list(loaded.monthly_columns),
        "forecast_file": str(forecast_file_path(model_dir)),
        "leaderboard_file": str(model_dir / LEADERBOARD_FILENAME),
        "predictor_path": str(predictor_path),
    }
    metadata_file_path(model_dir).write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata
