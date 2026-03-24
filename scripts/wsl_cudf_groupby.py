from __future__ import annotations

import argparse

import cudf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate monthly sums with cuDF inside WSL.")
    parser.add_argument("--input", required=True, help="Input parquet path.")
    parser.add_argument("--output", required=True, help="Output parquet path.")
    parser.add_argument(
        "--group-column",
        action="append",
        dest="group_columns",
        default=[],
        help="Grouping column. Repeat this flag for multiple columns.",
    )
    parser.add_argument(
        "--value-column",
        action="append",
        dest="value_columns",
        default=[],
        help="Value column to sum. Repeat this flag for multiple columns.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = cudf.read_parquet(args.input)
    selected = frame[args.group_columns + args.value_columns]
    grouped = selected.groupby(args.group_columns, dropna=False)[args.value_columns].sum().reset_index()
    grouped.to_parquet(args.output, index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
