from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deviation_dash.autogluon_integration import default_model_dir, train_predictor_from_workbook


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train an AutoGluon time-series model for Deviation Dash.")
    parser.add_argument(
        "--workbook",
        required=True,
        help="Path to the Excel workbook that contains the raw Data tab.",
    )
    parser.add_argument(
        "--model-dir",
        default=str(default_model_dir(PROJECT_ROOT)),
        help="Directory where the predictor and forecast artifacts should be saved.",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=1800,
        help="Training time limit in seconds.",
    )
    parser.add_argument(
        "--prediction-length",
        type=int,
        default=1,
        help="How many future months AutoGluon should forecast.",
    )
    parser.add_argument(
        "--presets",
        default="medium_quality",
        help="AutoGluon preset name such as medium_quality or high_quality.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbook_path = Path(args.workbook).expanduser()
    if not workbook_path.exists():
        print(f"Workbook not found: {workbook_path}")
        return 1

    model_dir = Path(args.model_dir).expanduser()
    metadata = train_predictor_from_workbook(
        file_bytes=workbook_path.read_bytes(),
        source_name=workbook_path.name,
        model_dir=model_dir,
        time_limit=args.time_limit,
        prediction_length=args.prediction_length,
        presets=args.presets,
    )
    print("AutoGluon training completed.")
    print(f"Model directory: {model_dir}")
    print(f"Forecast file: {metadata['forecast_file']}")
    print(f"Predictor path: {metadata['predictor_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
