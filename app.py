from __future__ import annotations

import calendar
import html
import json
from io import BytesIO
import math
from pathlib import Path
import sys
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PACKAGE_ROOT = PROJECT_ROOT / "deviation_dash"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

try:
    from deviation_dash.autogluon_integration import (
        build_forecast_lookup,
        default_model_dir,
        detect_autogluon,
        load_saved_forecast_artifact,
    )
    from deviation_dash.data_loader import LoadedWorkbook, load_data_workbook
    from deviation_dash.acceleration import detect_acceleration
    from deviation_dash.recommendations import (
        DEFAULT_HIGHEST_OUTLIER_THRESHOLD_PCT,
        DEFAULT_SERVICE_LEVELS,
        METHOD_LOOKUP,
        METHODS,
        SERVICE_LEVEL_ORDER,
        SeasonalityConfig,
        calculate_method,
        default_planning_season,
    )
except ImportError:
    from autogluon_integration import (
        build_forecast_lookup,
        default_model_dir,
        detect_autogluon,
        load_saved_forecast_artifact,
    )
    from data_loader import LoadedWorkbook, load_data_workbook
    from acceleration import detect_acceleration
    from recommendations import (
        DEFAULT_HIGHEST_OUTLIER_THRESHOLD_PCT,
        DEFAULT_SERVICE_LEVELS,
        METHOD_LOOKUP,
        METHODS,
        SERVICE_LEVEL_ORDER,
        SeasonalityConfig,
        calculate_method,
        default_planning_season,
    )

st.set_page_config(page_title="Deviation Dash", layout="wide")

VIEW_OPTIONS = [
    "Supplier Overview",
    "Supplier Drill-Down",
    "Item Overview",
    "Location Recommendations",
    "Item Drill-Down",
    "Raw Data",
]
DATA_CACHE_VERSION = "2026-03-24-supplier-min-floor-v8"


@st.cache_data(show_spinner=False)
def load_workbook_data(
    cache_version: str,
    file_bytes: bytes,
    source_name: str,
) -> LoadedWorkbook:
    return load_data_workbook(file_bytes, source_name)


def month_label_end(label: str) -> date | None:
    try:
        month_start = datetime.strptime(str(label or "").strip(), "%b-%y").date().replace(day=1)
    except ValueError:
        return None
    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    return date(month_start.year, month_start.month, last_day)


def apply_historical_replay_window(loaded: LoadedWorkbook, as_of_date: date) -> tuple[LoadedWorkbook, list[str]]:
    masked_labels: list[str] = []
    replayed_data = loaded.data.copy()
    for label in loaded.monthly_columns:
        label_end = month_label_end(label)
        if label_end is None or label_end <= as_of_date:
            continue
        replayed_data[label] = 0.0
        masked_labels.append(label)
    return (
        LoadedWorkbook(
            data=replayed_data,
            monthly_columns=loaded.monthly_columns,
            source_name=loaded.source_name,
        ),
        masked_labels,
    )


@st.cache_data(show_spinner="Recalculating recommendations...")
def load_dashboard_data(
    cache_version: str,
    file_bytes: bytes,
    source_name: str,
    method_key: str,
    seasonality_enabled: bool,
    planning_season: str,
    as_of_iso: str,
    historical_replay_mode: bool,
    processing_backend: str,
    prefer_gpu: bool,
    forecast_csv_bytes: bytes | None,
    service_levels_json: str,
    cheap_local_deviation_threshold: float,
    remove_highest_outlier_enabled: bool,
    highest_outlier_threshold_pct: float,
) -> tuple[LoadedWorkbook, pd.DataFrame, pd.DataFrame]:
    loaded = load_workbook_data(cache_version, file_bytes, source_name)
    as_of_date = date.fromisoformat(as_of_iso)
    effective_loaded = loaded
    if historical_replay_mode:
        effective_loaded, _ = apply_historical_replay_window(loaded, as_of_date)
    seasonality = SeasonalityConfig(
        enabled=seasonality_enabled,
        planning_season=planning_season,
        as_of_date=as_of_date,
    )
    acceleration = detect_acceleration(prefer_gpu=prefer_gpu)
    forecast_lookup = None
    if forecast_csv_bytes:
        forecast_frame = pd.read_csv(BytesIO(forecast_csv_bytes))
        forecast_lookup = build_forecast_lookup(forecast_frame)
    service_levels = json.loads(service_levels_json)
    method = METHOD_LOOKUP[method_key]
    detail, summary = calculate_method(
        effective_loaded.data,
        effective_loaded.monthly_columns,
        method,
        seasonality,
        acceleration,
        forecast_lookup,
        service_levels,
        cheap_local_deviation_threshold,
        remove_highest_outlier_enabled,
        highest_outlier_threshold_pct,
    )
    return effective_loaded, detail, summary


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(198, 153, 78, 0.08), transparent 22%),
                linear-gradient(180deg, #f8faf8 0%, #edf2f5 100%);
            color: #13251f;
        }
        html, body, .stApp {
            font-family: "Aptos", "Franklin Gothic Medium", "Trebuchet MS", sans-serif;
            color: #13251f;
        }
        .material-symbols-rounded,
        .material-symbols-outlined,
        .material-symbols-sharp,
        .material-icons,
        .material-icons-round,
        .material-icons-outlined,
        .material-icons-sharp,
        [class*="material-symbols"],
        [class*="material-icons"] {
            font-family: "Material Symbols Rounded" !important;
            font-weight: 400 !important;
            font-style: normal !important;
            font-size: 1.1rem !important;
            line-height: 1 !important;
            letter-spacing: normal !important;
            text-transform: none !important;
            white-space: nowrap !important;
            word-wrap: normal !important;
            direction: ltr !important;
            -webkit-font-smoothing: antialiased !important;
            font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24;
        }
        [data-testid="stElementToolbar"],
        .vega-embed .vega-actions {
            display: none !important;
        }
        [data-testid="stDataFrameColumnMenu"],
        [data-testid="stDataFrameColumnFormattingMenu"] {
            background: transparent !important;
        }
        [data-testid="stDataFrameColumnMenu"] > div,
        [data-testid="stDataFrameColumnFormattingMenu"] > div {
            background: #ffffff !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.16) !important;
            border-radius: 12px !important;
            box-shadow: 0 18px 36px rgba(23, 59, 47, 0.16) !important;
            overflow: hidden !important;
        }
        [data-testid="stDataFrameColumnMenu"] *,
        [data-testid="stDataFrameColumnFormattingMenu"] * {
            color: #173b2f !important;
            fill: #173b2f !important;
        }
        [data-testid="stDataFrameColumnMenu"] [role="menuitem"],
        [data-testid="stDataFrameColumnFormattingMenu"] [role="menuitem"] {
            background: #ffffff !important;
            color: #173b2f !important;
            font-weight: 600 !important;
        }
        [data-testid="stDataFrameColumnMenu"] [role="menuitem"]:hover,
        [data-testid="stDataFrameColumnFormattingMenu"] [role="menuitem"]:hover {
            background: #eef3ef !important;
        }
        [data-testid="stDataFrameColumnMenu"] hr,
        [data-testid="stDataFrameColumnFormattingMenu"] hr {
            border-color: rgba(23, 59, 47, 0.12) !important;
        }
        [data-testid="stDataFrameColumnMenu"] label,
        [data-testid="stDataFrameColumnFormattingMenu"] label {
            color: #173b2f !important;
            font-weight: 600 !important;
        }
        [data-testid="stDataFrameColumnMenu"] input,
        [data-testid="stDataFrameColumnFormattingMenu"] input {
            accent-color: #173b2f !important;
        }
        [data-testid="stSidebar"] {
            background: #ffffff;
        }
        [data-testid="stMetricLabel"],
        [data-testid="stMetricLabel"] *,
        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] *,
        [data-testid="stMetricDeltaDescription"],
        [data-testid="stMetricDeltaDescription"] * {
            color: #173b2f !important;
        }
        [data-testid="stMetricLabel"] p {
            font-weight: 700 !important;
        }
        [data-testid="stMetricValue"] {
            font-weight: 700 !important;
        }
        [data-testid="stMetricDelta"] {
            font-weight: 700 !important;
        }
        .stCheckbox,
        .stCheckbox *,
        .stRadio,
        .stRadio *,
        [data-testid="stRadioGroup"],
        [data-testid="stRadioGroup"] *,
        [data-testid="stCheckbox"],
        [data-testid="stCheckbox"] * {
            color: #173b2f !important;
        }
        .stCheckbox label,
        .stRadio label,
        [data-testid="stCheckbox"] label,
        [data-testid="stRadio"] label {
            font-weight: 600 !important;
        }
        .stCheckbox svg,
        .stRadio svg,
        [data-testid="stCheckbox"] svg,
        [data-testid="stRadio"] svg {
            fill: #173b2f !important;
            color: #173b2f !important;
        }
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] *,
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] * {
            color: #324640 !important;
        }
        [data-testid="stCaptionContainer"] {
            font-size: 0.92rem !important;
        }
        [data-testid="stFileUploader"] small,
        [data-testid="stFileUploader"] span,
        [data-testid="stFileUploader"] p,
        [data-testid="stFileUploader"] label,
        [data-testid="stFileUploader"] svg {
            color: #173b2f !important;
            fill: #173b2f !important;
        }
        [data-testid="stFileUploaderDropzone"] {
            background: #f5f8f6 !important;
            border: 1px dashed rgba(23, 59, 47, 0.28) !important;
            color: #173b2f !important;
            border-radius: 14px !important;
        }
        [data-testid="stFileUploaderDropzone"] * {
            color: #173b2f !important;
        }
        [data-testid="stFileUploaderDropzone"] button {
            background: #eef3ef !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.16) !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            box-shadow: none !important;
        }
        [data-testid="stFileUploaderDropzone"] button:hover {
            background: #e0ebe3 !important;
            color: #173b2f !important;
            border-color: rgba(23, 59, 47, 0.22) !important;
        }
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
            background: #f5f8f6 !important;
            border: 1px dashed rgba(23, 59, 47, 0.28) !important;
            color: #173b2f !important;
        }
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {
            color: #173b2f !important;
        }
        [data-testid="stExpander"] details {
            background: #f7faf8;
            border: 1px solid rgba(23, 59, 47, 0.10);
            border-radius: 14px;
            overflow: hidden;
        }
        [data-testid="stExpander"] summary {
            background: #eef3ef !important;
            color: #173b2f !important;
            font-weight: 700;
            padding: 0.8rem 1rem !important;
        }
        [data-testid="stExpander"] summary:hover {
            background: #e4ece6 !important;
        }
        [data-testid="stExpander"] summary > div {
            display: flex !important;
            align-items: center !important;
            gap: 0.55rem !important;
            width: 100%;
        }
        [data-testid="stExpander"] summary p {
            margin: 0 !important;
            color: #173b2f !important;
            font-weight: 700 !important;
            line-height: 1.2 !important;
        }
        [data-testid="stExpander"] summary svg {
            color: #173b2f !important;
            fill: #173b2f !important;
            flex-shrink: 0 !important;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] details {
            background: #f7faf8;
            border: 1px solid rgba(23, 59, 47, 0.10);
            border-radius: 14px;
            overflow: hidden;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary {
            background: #eef3ef !important;
            color: #173b2f !important;
            font-weight: 700;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
            background: #e4ece6 !important;
        }
        .stButton > button,
        .stDownloadButton > button {
            background: #eef3ef !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.16) !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
            box-shadow: none !important;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover {
            background: #e0ebe3 !important;
            border-color: rgba(23, 59, 47, 0.22) !important;
            color: #173b2f !important;
        }
        .stButton > button:focus,
        .stDownloadButton > button:focus {
            color: #173b2f !important;
            box-shadow: 0 0 0 0.2rem rgba(138, 111, 30, 0.18) !important;
        }
        [data-testid="stSidebar"] .stButton > button,
        [data-testid="stSidebar"] .stDownloadButton > button {
            background: #eef3ef !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.16) !important;
            border-radius: 10px !important;
            font-weight: 700 !important;
        }
        [data-testid="stSidebar"] .stButton > button:hover,
        [data-testid="stSidebar"] .stDownloadButton > button:hover {
            background: #e0ebe3 !important;
            border-color: rgba(23, 59, 47, 0.22) !important;
            color: #173b2f !important;
        }
        [data-testid="stSidebar"] .stButton > button:focus,
        [data-testid="stSidebar"] .stDownloadButton > button:focus {
            color: #173b2f !important;
            box-shadow: 0 0 0 0.2rem rgba(138, 111, 30, 0.18) !important;
        }
        .stSelectbox [data-baseweb="select"] > div,
        .stMultiSelect [data-baseweb="select"] > div,
        .stTextInput [data-baseweb="input"] > div,
        .stNumberInput [data-baseweb="input"] > div {
            background: #ffffff !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.16) !important;
            border-radius: 10px !important;
            box-shadow: none !important;
            min-height: 2.85rem !important;
        }
        .stSelectbox [data-baseweb="select"] input,
        .stMultiSelect [data-baseweb="select"] input,
        .stTextInput input,
        .stNumberInput input {
            background: transparent !important;
            color: #173b2f !important;
            -webkit-text-fill-color: #173b2f !important;
        }
        .stSelectbox [data-baseweb="select"] span,
        .stMultiSelect [data-baseweb="select"] span,
        .stSelectbox [data-baseweb="select"] div,
        .stMultiSelect [data-baseweb="select"] div {
            color: #173b2f !important;
        }
        .stSelectbox svg,
        .stMultiSelect svg,
        .stNumberInput svg {
            fill: #173b2f !important;
            color: #173b2f !important;
        }
        .stMultiSelect [data-baseweb="tag"] {
            background: #e8f0ea !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.12) !important;
        }
        .stMultiSelect [data-baseweb="tag"] * {
            color: #173b2f !important;
        }
        .stTextInput label,
        .stSelectbox label,
        .stMultiSelect label,
        .stNumberInput label {
            color: #173b2f !important;
            font-weight: 700 !important;
        }
        ::placeholder {
            color: #5f726b !important;
            opacity: 1 !important;
        }
        [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div,
        [data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] > div,
        [data-testid="stSidebar"] .stTextInput [data-baseweb="input"] > div,
        [data-testid="stSidebar"] .stNumberInput [data-baseweb="input"] > div {
            background: #ffffff !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.16) !important;
            border-radius: 10px !important;
            box-shadow: none !important;
        }
        [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] input,
        [data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] input,
        [data-testid="stSidebar"] .stTextInput input,
        [data-testid="stSidebar"] .stNumberInput input {
            background: transparent !important;
            color: #173b2f !important;
            -webkit-text-fill-color: #173b2f !important;
        }
        [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] span,
        [data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] span,
        [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] div,
        [data-testid="stSidebar"] .stMultiSelect [data-baseweb="select"] div {
            color: #173b2f !important;
        }
        [data-testid="stSidebar"] .stSelectbox svg,
        [data-testid="stSidebar"] .stMultiSelect svg,
        [data-testid="stSidebar"] .stNumberInput svg {
            fill: #173b2f !important;
            color: #173b2f !important;
        }
        [data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] {
            background: #e8f0ea !important;
            color: #173b2f !important;
            border: 1px solid rgba(23, 59, 47, 0.12) !important;
        }
        [data-testid="stSidebar"] .stMultiSelect [data-baseweb="tag"] * {
            color: #173b2f !important;
        }
        [data-testid="stSidebar"] ::placeholder {
            color: #5f726b !important;
            opacity: 1 !important;
        }
        .hero {
            background: linear-gradient(180deg, #ffffff 0%, #f3f6f1 100%);
            color: #173b2f;
            padding: 1.6rem 1.8rem;
            border-radius: 18px;
            border: 1px solid rgba(23, 59, 47, 0.10);
            box-shadow: 0 18px 36px rgba(23, 59, 47, 0.08);
            margin-bottom: 1rem;
        }
        .hero-kicker {
            letter-spacing: 0.12em;
            text-transform: uppercase;
            font-size: 0.76rem;
            color: #8a6f1e;
            margin-bottom: 0.4rem;
        }
        .hero h1 {
            margin: 0 0 0.4rem 0;
            font-size: 2.1rem;
            line-height: 1.1;
        }
        .hero p {
            margin: 0;
            max-width: 54rem;
            color: #324640;
            font-size: 1rem;
        }
        .callout {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid rgba(23, 59, 47, 0.08);
            border-radius: 14px;
            padding: 0.95rem 1rem;
            box-shadow: 0 12px 26px rgba(23, 59, 47, 0.06);
            margin-bottom: 0.75rem;
            color: #173b2f;
        }
        .callout strong {
            color: #173b2f;
        }
        .section-note {
            color: #476057;
            font-size: 0.95rem;
            margin: 0.2rem 0 0.8rem 0;
        }
        code, pre, [data-testid="stCodeBlock"] pre, [data-testid="stCode"] {
            color: #f4f7fb !important;
        }
        :not(pre) > code {
            background: #1c2228 !important;
            color: #f4f7fb !important;
            padding: 0.12rem 0.34rem;
            border-radius: 0.35rem;
        }
        .location-calculation-shell {
            overflow-x: auto;
            overflow-y: visible;
            border: 1px solid rgba(23, 59, 47, 0.12);
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.97);
            box-shadow: 0 12px 24px rgba(23, 59, 47, 0.06);
            margin-bottom: 0.75rem;
        }
        .location-calculation-shell table {
            width: max-content;
            min-width: 100%;
            border-collapse: separate;
            border-spacing: 0;
        }
        .location-calculation-shell thead th {
            position: sticky;
            top: 0;
            z-index: 3;
            background: #eef3ef;
            color: #173b2f;
            border-bottom: 1px solid rgba(23, 59, 47, 0.12);
        }
        .location-calculation-shell th,
        .location-calculation-shell td {
            padding: 0.58rem 0.75rem;
            white-space: nowrap;
            border-bottom: 1px solid rgba(23, 59, 47, 0.08);
        }
        .location-calculation-shell tbody tr:nth-child(even) td {
            background: rgba(244, 247, 243, 0.7);
        }
        .location-calculation-shell th:first-child,
        .location-calculation-shell td:first-child {
            position: sticky;
            left: 0;
            z-index: 2;
            background: #ffffff;
            box-shadow: 4px 0 10px rgba(23, 59, 47, 0.06);
        }
        .location-calculation-shell thead th:first-child {
            z-index: 4;
            background: #e7efe9;
        }
        .calc-popover {
            position: relative;
            display: block;
            min-width: 6.5rem;
            text-align: left;
        }
        .calc-popover summary {
            list-style: none;
            cursor: pointer;
            font-weight: 700;
            display: inline-block;
            text-decoration: underline;
            text-decoration-style: dotted;
            text-underline-offset: 0.16rem;
        }
        .calc-popover summary::-webkit-details-marker {
            display: none;
        }
        .calc-popover-card {
            position: static;
            margin-top: 0.45rem;
            width: min(28rem, calc(100vw - 5rem));
            min-width: 18rem;
            max-width: 28rem;
            max-height: min(22rem, calc(100vh - 6rem));
            overflow-y: auto;
            padding: 0.85rem 0.95rem;
            border-radius: 12px;
            border: 1px solid rgba(23, 59, 47, 0.16);
            background: #ffffff;
            box-shadow: 0 18px 36px rgba(23, 59, 47, 0.16);
            box-sizing: border-box;
            text-align: left;
            white-space: normal !important;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .calc-popover-title {
            color: #173b2f;
            font-weight: 700;
            margin-bottom: 0.35rem;
            white-space: normal !important;
            overflow-wrap: anywhere;
        }
        .calc-popover-text {
            color: #324640;
            font-size: 0.92rem;
            line-height: 1.4;
            margin-bottom: 0.55rem;
            white-space: normal !important;
            overflow-wrap: anywhere;
        }
        .calc-popover-fact {
            color: #324640;
            font-size: 0.9rem;
            line-height: 1.4;
            margin-bottom: 0.55rem;
            padding: 0.45rem 0.55rem;
            border-radius: 10px;
            background: #f5f8f6;
            white-space: normal !important;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .calc-popover-label {
            display: block;
            font-weight: 700;
            color: #173b2f;
            margin-bottom: 0.12rem;
            font-size: 0.76rem;
            letter-spacing: 0.02em;
            text-transform: uppercase;
        }
        .calc-popover-value {
            white-space: normal !important;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_item_option(row: pd.Series) -> str:
    return f"{row['supplier']} | {row['item']} | {row['description']}"


def ordered_month_labels(monthly_columns: list[str]) -> list[str]:
    def sort_key(label: str) -> tuple[int, datetime | str]:
        try:
            return (0, datetime.strptime(label, "%b-%y"))
        except ValueError:
            return (1, label)

    return [label for label in sorted(monthly_columns, key=sort_key)]


def sort_location_values(values: list[object]) -> list[str]:
    def sort_key(value: object) -> tuple[int, int | str]:
        text = str(value).strip()
        if text.isdigit():
            return (0, int(text))
        return (1, text)

    normalized = [str(value).strip() for value in values if str(value).strip()]
    return sorted(dict.fromkeys(normalized), key=sort_key)


def select_unique_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    deduped_frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    requested: list[str] = []
    seen: set[str] = set()
    for column in columns:
        if column in deduped_frame.columns and column not in seen:
            requested.append(column)
            seen.add(column)
    return deduped_frame.loc[:, requested].copy()


def format_boolean_cell(value: object) -> str:
    return "Yes" if bool(value) else ""


def numeric_value(value: object) -> float:
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        coerced = pd.to_numeric(pd.Series([value]), errors="coerce").fillna(0.0).iloc[0]
        return float(coerced)


def format_quantity(value: object, decimals: int = 0) -> str:
    number = numeric_value(value)
    return f"{number:,.{decimals}f}"


def service_level_policy_summary(service_levels_pct: dict[str, float]) -> str:
    return " | ".join(
        f"{code} {service_levels_pct.get(code, DEFAULT_SERVICE_LEVELS[code] * 100):.0f}%"
        for code in SERVICE_LEVEL_ORDER
    )


def service_level_input_key(code: str) -> str:
    return f"service_level_{code}"


def reset_service_level_inputs() -> None:
    for code in SERVICE_LEVEL_ORDER:
        st.session_state[service_level_input_key(code)] = float(DEFAULT_SERVICE_LEVELS[code] * 100)


def using_custom_service_levels(service_levels_pct: dict[str, float]) -> bool:
    for code in SERVICE_LEVEL_ORDER:
        default_pct = float(DEFAULT_SERVICE_LEVELS[code] * 100)
        if abs(float(service_levels_pct.get(code, default_pct)) - default_pct) > 0.001:
            return True
    return False


def render_excel_like_filter(
    container,
    label: str,
    options: list[object],
    key: str,
    default_values: list[object] | None = None,
    help_text: str | None = None,
    expanded: bool = False,
) -> list[str]:
    normalized_options = list(dict.fromkeys(str(value) for value in options if str(value)))
    normalized_defaults = (
        normalized_options.copy()
        if default_values is None
        else [str(value) for value in default_values if str(value) in normalized_options]
    )
    selection_key = f"{key}_selection"
    options_signature_key = f"{key}_options_signature"
    options_signature = "||".join(normalized_options)
    previous_signature = st.session_state.get(options_signature_key)
    raw_selection = st.session_state.get(selection_key)
    if raw_selection is None:
        st.session_state[selection_key] = normalized_defaults
    else:
        raw_selection_list = [str(value) for value in raw_selection]
        current_selection = [value for value in raw_selection_list if value in normalized_options]
        if previous_signature != options_signature:
            st.session_state[selection_key] = current_selection if (current_selection or raw_selection_list == []) else normalized_defaults
        elif current_selection != raw_selection_list:
            st.session_state[selection_key] = current_selection
    st.session_state[options_signature_key] = options_signature

    current_selection = [str(value) for value in st.session_state.get(selection_key, []) if str(value) in normalized_options]
    heading = f"{label} ({len(current_selection)}/{len(normalized_options)})"

    with container.expander(heading, expanded=expanded):
        if help_text:
            st.caption(help_text)
        button_col1, button_col2 = st.columns(2)
        if button_col1.button("Select all", key=f"{key}_select_all", use_container_width=True):
            st.session_state[selection_key] = normalized_options.copy()
        if button_col2.button("Clear all", key=f"{key}_clear_all", use_container_width=True):
            st.session_state[selection_key] = []
        selected_values = st.multiselect(
            "Choose values",
            options=normalized_options,
            key=selection_key,
            label_visibility="collapsed",
            placeholder=f"Choose one or more {label.lower()}",
        )
        current_selection = [str(value) for value in selected_values if str(value) in normalized_options]
        if normalized_options:
            st.caption(f"{len(current_selection)} of {len(normalized_options)} selected")
        else:
            st.caption("No values available")

    return current_selection


def build_calc_popover_html(
    display_value: object,
    title: str,
    summary_text: str,
    facts: list[tuple[str, str]],
) -> str:
    safe_title = html.escape(title)
    safe_summary = html.escape(summary_text)
    facts_html = "".join(
        (
            "<div class='calc-popover-fact'>"
            f"<div class='calc-popover-label'>{html.escape(label)}</div>"
            f"<div class='calc-popover-value'>{html.escape(value)}</div>"
            "</div>"
        )
        for label, value in facts
        if value
    )
    return (
        "<details class='calc-popover'>"
        f"<summary>{html.escape(str(display_value))}</summary>"
        "<div class='calc-popover-card'>"
        f"<div class='calc-popover-title'>{safe_title}</div>"
        f"<div class='calc-popover-text'>{safe_summary}</div>"
        f"{facts_html}"
        "</div>"
        "</details>"
    )


def branch_base_recommendation(current_max: object, rounded_mean: object) -> float:
    current_max_value = numeric_value(current_max)
    rounded_mean_value = numeric_value(rounded_mean)
    if current_max_value > 0:
        return 1.0 if rounded_mean_value == 0 else rounded_mean_value
    return 0.0


def build_highest_outlier_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("highest_outlier_removed")):
        return None

    threshold_pct = numeric_value(row.get("highest_outlier_threshold_pct"))
    parts: list[str] = []
    if bool(row.get("highest_outlier_removed_from_mean")):
        parts.append(
            f"{str(row.get('highest_outlier_removed_month_mean', '') or 'the highest scoped month')} at {format_quantity(row.get('highest_outlier_removed_value_mean'), 1)} was {numeric_value(row.get('highest_outlier_trigger_pct_mean')):.0f}% of the remaining non-zero baseline of {format_quantity(row.get('highest_outlier_baseline_value_mean'), 1)}, so it was reset to {format_quantity(row.get('highest_outlier_baseline_value_mean'), 1)} for the mean input."
        )
    if bool(row.get("highest_outlier_removed_from_std")):
        same_month = (
            bool(row.get("highest_outlier_removed_from_mean"))
            and str(row.get("highest_outlier_removed_month_std", "") or "") == str(row.get("highest_outlier_removed_month_mean", "") or "")
            and abs(numeric_value(row.get("highest_outlier_removed_value_std")) - numeric_value(row.get("highest_outlier_removed_value_mean"))) < 0.001
        )
        if same_month:
            parts.append("That same month was also reset to that standard-month baseline for the variability input.")
        else:
            parts.append(
                f"{str(row.get('highest_outlier_removed_month_std', '') or 'the highest scoped month')} at {format_quantity(row.get('highest_outlier_removed_value_std'), 1)} was {numeric_value(row.get('highest_outlier_trigger_pct_std')):.0f}% of the remaining non-zero baseline of {format_quantity(row.get('highest_outlier_baseline_value_std'), 1)}, so it was reset to {format_quantity(row.get('highest_outlier_baseline_value_std'), 1)} for the variability input."
            )
    if not parts:
        return None
    return (
        "Highest-month filter: ",
        f"The dashboard threshold is {threshold_pct:.0f}%. " + " ".join(parts),
    )


def build_two_point_spike_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("two_point_spike_normalized")):
        return None

    parts: list[str] = []
    if bool(row.get("two_point_spike_normalized_from_mean")):
        parts.append(
            f"{str(row.get('two_point_spike_normalized_month_mean', '') or 'the top scoped month')} at {format_quantity(row.get('two_point_spike_normalized_value_mean'), 1)} was {numeric_value(row.get('two_point_spike_normalized_ratio_mean')):.1f}x the second active month of {format_quantity(row.get('two_point_spike_normalized_baseline_value_mean'), 1)}, so it was reset to {format_quantity(row.get('two_point_spike_normalized_baseline_value_mean'), 1)} for the mean input."
        )
    if bool(row.get("two_point_spike_normalized_from_std")):
        same_month = (
            bool(row.get("two_point_spike_normalized_from_mean"))
            and str(row.get("two_point_spike_normalized_month_std", "") or "") == str(row.get("two_point_spike_normalized_month_mean", "") or "")
            and abs(numeric_value(row.get("two_point_spike_normalized_value_std")) - numeric_value(row.get("two_point_spike_normalized_value_mean"))) < 0.001
        )
        if same_month:
            parts.append("That same month was also reset to that second-month baseline for the variability input.")
        else:
            parts.append(
                f"{str(row.get('two_point_spike_normalized_month_std', '') or 'the top scoped month')} at {format_quantity(row.get('two_point_spike_normalized_value_std'), 1)} was {numeric_value(row.get('two_point_spike_normalized_ratio_std')):.1f}x the second active month of {format_quantity(row.get('two_point_spike_normalized_baseline_value_std'), 1)}, so it was reset to {format_quantity(row.get('two_point_spike_normalized_baseline_value_std'), 1)} for the variability input."
            )
    if not parts:
        return None
    return (
        "Two-point spike rule: ",
        " ".join(parts),
    )


def build_single_period_pool_guard_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("single_period_pool_guard_applied")):
        return None
    return (
        "Single-period pooling guard: ",
        f"{str(row.get('single_period_pool_guard_reason', '') or 'This branch only has a single scoped selling month and the item lacks repeat proof.')}. "
        "That thin branch signal is allowed to inform the local branch floor, but it is not allowed to create pooled DC stock yet.",
    )


def build_single_stocked_branch_hold_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("single_stocked_branch_hold_applied")):
        return None
    stocked_location = str(row.get("single_stocked_branch_hold_location", "") or "").strip() or "the only stocked branch"
    current_location = str(row.get("location", "") or "").strip()
    if current_location == stocked_location:
        return (
            "Single-stocked branch hold: ",
            f"This item is only currently stocked at location {stocked_location} outside the DC, and the status is not Regional. That stocked branch keeps its own local need and does not create pooled DC stock.",
        )
    return (
        "Single-stocked branch hold: ",
        f"This item is only currently stocked at location {stocked_location} outside the DC, and the status is not Regional. Other locations cannot seed DC stock for it.",
    )


def build_non_stockable_location_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("non_stockable_location_blocked")):
        return None
    return (
        "Non-stockable location: ",
        "This location is marked as not stockable, so it cannot seed a new branch max or create pooled DC stock.",
    )


def build_dc_sparse_active_mean_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("dc_sparse_active_mean_fallback_applied")):
        return None
    return (
        "DC sparse active-demand fallback: ",
        f"{str(row.get('dc_sparse_active_mean_fallback_reason', '') or 'The DC only had very thin scoped history and no pooled branch stock, so the model used the inclusive scoped mean instead of the active-month mean.')}.",
    )


def build_intermittent_transfer_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("intermittent_branch_protection_applied")):
        return None
    raw_transfer = numeric_value(row.get("raw_intermittent_direct_transfer"))
    if raw_transfer <= 0:
        return None
    if bool(row.get("intermittent_direct_transfer_suppressed")):
        return (
            "Direct transfer policy: ",
            f"The intermittent branch rule identified {format_quantity(raw_transfer, 1)} units of direct spike-transfer stock, but no explicit spike rule fired here, so that amount is not sent to the DC. Only pooled variance is used.",
        )
    if bool(row.get("intermittent_direct_transfer_allowed")):
        return (
            "Direct transfer policy: ",
            f"{format_quantity(row.get('intermittent_spike_pooled_to_dc'), 1)} units of direct spike-transfer stock are allowed into the DC because an explicit spike rule fired on this row.",
        )
    return None


def build_seasonal_ramp_fact(row: pd.Series) -> tuple[str, str] | None:
    if not bool(row.get("seasonal_ramp_applied")):
        return None
    return (
        "Current window seasonality: ",
        f"This item has enough seasonal history to use the next replenishment window instead of the whole season. "
        f"The forward window starts {str(row.get('seasonal_ramp_start_date', '') or '')} and spans {str(row.get('seasonal_ramp_window', '') or '')}. "
        f"That window averages {format_quantity(row.get('seasonal_ramp_window_average'), 1)} units per month versus {format_quantity(row.get('seasonal_ramp_full_season_average'), 1)} across the full season, so the demand basis is scaled by {numeric_value(row.get('seasonal_ramp_factor')):.2f}x."
        + (
            f" Peak seasonal month is {str(row.get('seasonal_ramp_peak_month', '') or '')}."
            if str(row.get("seasonal_ramp_peak_month", "") or "").strip()
            else ""
        ),
    )


def balancing_recommendation_value(row: pd.Series, item_rows: pd.DataFrame) -> float:
    current_location = str(row.get("location", ""))
    source = item_rows.loc[:, ~item_rows.columns.duplicated()].copy()
    others = source[source["location"].astype(str) != current_location]
    max_total_dev = math.ceil(pd.to_numeric(source["total_dev"], errors="coerce").fillna(0.0).max())
    if "variability_pooled_to_dc" in others.columns or "direct_transfer_pooled_to_dc" in others.columns:
        pooled_variance = math.sqrt(
            (
                pd.to_numeric(others.get("variability_pooled_to_dc"), errors="coerce").fillna(0.0) ** 2
            ).sum()
        )
        pooled_direct_transfer = pd.to_numeric(
            others.get("direct_transfer_pooled_to_dc"), errors="coerce"
        ).fillna(0.0).sum()
        pooled_branch_deviation = pooled_variance + pooled_direct_transfer
    else:
        pooled_branch_deviation = pd.to_numeric(others.get("deviation_pooled_to_dc"), errors="coerce").fillna(0.0).sum()
    balancing_value = numeric_value(row.get("rounded_mean")) + (
        pd.to_numeric(others.get("rounded_mean"), errors="coerce").fillna(0.0).sum()
        - pd.to_numeric(others.get("recommended_new_max"), errors="coerce").fillna(0.0).sum()
    ) + max_total_dev + math.ceil(float(pooled_branch_deviation))
    return max(float(balancing_value), 1.0)


def build_min_explanation(row: pd.Series) -> tuple[str, str, list[tuple[str, str]]]:
    location = str(row.get("location", ""))
    recommended_min = numeric_value(row.get("recommended_min_amount"))
    current_min = numeric_value(row.get("min_value"))
    daily_demand = numeric_value(row.get("daily_demand"))
    lead_time_days = numeric_value(row.get("lead_time_days"))
    frequency_days = numeric_value(row.get("frequency_days"))
    protection_days = numeric_value(row.get("protection_days"))
    demand_basis = numeric_value(row.get("trend_adjusted_mean"))
    mean_source = str(row.get("mean_source", "Historical demand")) or "Historical demand"
    min_delta = recommended_min - current_min
    project_spike_suppressed = bool(row.get("project_spike_suppressed"))
    if bool(row.get("dc_location_reserve_rule_applied")):
        title = f"Why location {location} new min is {format_quantity(recommended_min)}"
        summary_text = (
            f"Location {location} is treated as the DC, so its min only covers that location's own demand during the protected cycle."
        )
        facts = [
            (
                "Demand basis: ",
                f"{format_quantity(demand_basis, 1)} per month from {mean_source}, or {format_quantity(daily_demand, 2)} per day.",
            ),
            (
                "Protected cycle: ",
                f"{format_quantity(lead_time_days)} lead-time days plus {format_quantity(frequency_days)} order-cycle days, using {format_quantity(protection_days)} total days.",
            ),
            (
                "DC min rule: ",
                f"{format_quantity(row.get('protected_cycle_demand'), 1)} units across that cycle, rounded up to {format_quantity(row.get('dc_transfer_reserve_amount'))}.",
            ),
            (
                "Change from current: ",
                f"Current min is {format_quantity(current_min)}, so the recommendation changes it by {format_quantity(min_delta)}.",
            ),
        ]
        dc_sparse_active_fact = build_dc_sparse_active_mean_fact(row)
        if dc_sparse_active_fact is not None:
            facts.insert(1, dc_sparse_active_fact)
    else:
        title = f"Why location {location} new min is {format_quantity(recommended_min)}"
        if project_spike_suppressed:
            summary_text = "This branch usage was treated as a one-time project/non-replenishment event, so it does not create a replenishment min."
        else:
            summary_text = "Branch min covers what this location is expected to need while waiting for replenishment to arrive."
        facts = [
            (
                "Demand basis: ",
                f"{format_quantity(demand_basis, 1)} per month from {mean_source}, or {format_quantity(daily_demand, 2)} per day.",
            ),
            (
                "Lead-time need: ",
                f"{format_quantity(lead_time_days)} lead-time days x {format_quantity(daily_demand, 2)} per day = {format_quantity(row.get('lead_time_demand'), 1)} units.",
            ),
            (
                "Branch min rule: ",
                f"That lead-time demand is rounded up to {format_quantity(row.get('demand_only_min_amount'))} for the new min.",
            ),
            (
                "Change from current: ",
                f"Current min is {format_quantity(current_min)}, so the recommendation changes it by {format_quantity(min_delta)}.",
            ),
        ]
    if project_spike_suppressed:
        facts.insert(
            1,
            (
                "Project spike suppression: ",
                f"{str(row.get('project_spike_top_month_label', '') or 'The top month')} had {format_quantity(row.get('project_spike_top_month_value'), 1)} units. "
                f"That is {numeric_value(row.get('project_spike_branch_top_month_share_pct')):.0f}% of this branch's last-12-month usage and "
                f"{numeric_value(row.get('project_spike_company_top_month_share_pct')):.0f}% of company last-12-month usage, so it is excluded from replenishment math.",
            ),
        )
    if numeric_value(row.get("negative_usage_netted_months")) > 0:
        facts.insert(
            1,
            (
                "Returns netted backward: ",
                f"{format_quantity(row.get('negative_usage_netted_units'), 1)} units of negative monthly activity across {format_quantity(row.get('negative_usage_netted_months'))} month(s) were applied back to the closest earlier positive month(s) within 12 months."
                + (
                    f" {format_quantity(row.get('negative_usage_unmatched_units'), 1)} units had no earlier positive month and were dropped."
                    if numeric_value(row.get('negative_usage_unmatched_units')) > 0
                    else ""
                ),
            ),
        )
    if not project_spike_suppressed and bool(row.get("intermittent_branch_protection_applied")):
        facts.insert(
            1,
            (
                "Intermittent branch rule: ",
                f"This branch only sold in {format_quantity(row.get('intermittent_non_zero_months'))} of {format_quantity(row.get('intermittent_scope_months'))} scoped months. "
                f"ADI is {numeric_value(row.get('intermittent_adi')):.1f}, the top two months make up {numeric_value(row.get('intermittent_top_two_share_pct')):.0f}% of scoped demand, "
                f"and the branch mean is reduced from {format_quantity(row.get('raw_trend_adjusted_mean'), 1)} to {format_quantity(row.get('trend_adjusted_mean'), 1)}.",
            ),
        )
    intermittent_transfer_fact = build_intermittent_transfer_fact(row)
    if intermittent_transfer_fact is not None:
        facts.insert(1, intermittent_transfer_fact)
    non_stockable_fact = build_non_stockable_location_fact(row)
    if non_stockable_fact is not None:
        facts.insert(1, non_stockable_fact)
    single_stocked_hold_fact = build_single_stocked_branch_hold_fact(row)
    if single_stocked_hold_fact is not None:
        facts.insert(1, single_stocked_hold_fact)
    single_period_pool_guard_fact = build_single_period_pool_guard_fact(row)
    if single_period_pool_guard_fact is not None:
        facts.insert(1, single_period_pool_guard_fact)
    two_point_spike_fact = build_two_point_spike_fact(row)
    if two_point_spike_fact is not None:
        facts.insert(1, two_point_spike_fact)
    highest_outlier_fact = build_highest_outlier_fact(row)
    if highest_outlier_fact is not None:
        facts.insert(1, highest_outlier_fact)
    seasonal_ramp_fact = build_seasonal_ramp_fact(row)
    if seasonal_ramp_fact is not None:
        facts.insert(1, seasonal_ramp_fact)
    if bool(row.get("minimum_28_day_rule_applied")):
        facts.insert(
            2,
            (
                "28-day minimum: ",
                f"Lead time plus order cycle was under 28 days, so policy calculations were lifted to {format_quantity(protection_days)} days.",
            ),
        )
    if bool(row.get("override_flag")) and recommended_min < numeric_value(row.get("demand_only_min_amount")):
        facts.append(
            (
                "Override cap: ",
                "The max is manually overridden, so the min cannot be raised above that overridden max.",
            )
        )
    return title, summary_text, facts


def build_max_explanation(row: pd.Series, item_rows: pd.DataFrame) -> tuple[str, str, list[tuple[str, str]]]:
    location = str(row.get("location", ""))
    recommended_max = numeric_value(row.get("recommended_new_max"))
    current_max = numeric_value(row.get("current_max"))
    max_delta = recommended_max - current_max
    demand_basis = numeric_value(row.get("trend_adjusted_mean"))
    rounded_mean = numeric_value(row.get("rounded_mean"))
    policy_order_up_to = numeric_value(row.get("policy_order_up_to"))
    recommended_min = numeric_value(row.get("recommended_min_amount"))
    mean_source = str(row.get("mean_source", "Historical demand")) or "Historical demand"
    mac_value = numeric_value(row.get("mac"))
    local_cutoff = numeric_value(row.get("low_cost_local_deviation_threshold"))
    keep_dev_local = bool(row.get("low_cost_local_deviation_applied"))
    kept_local_amount = numeric_value(row.get("low_cost_local_deviation_kept_amount"))
    branch_zero_alert = bool(row.get("branch_zero_max_recommendation_alert"))
    regional_zero_pool = bool(row.get("regional_zero_max_branch_pool_applied"))
    project_spike_suppressed = bool(row.get("project_spike_suppressed"))
    pooled_variance_to_dc = numeric_value(row.get("variability_pooled_to_dc"))
    direct_transfer_to_dc = numeric_value(row.get("direct_transfer_pooled_to_dc"))
    pooled_variance_absorbed = numeric_value(row.get("pooled_variance_absorbed_by_dc"))
    pooled_direct_absorbed = numeric_value(row.get("pooled_direct_transfer_absorbed_by_dc"))

    if bool(row.get("override_flag")):
        title = f"Why location {location} new max is {format_quantity(recommended_max)}"
        summary_text = "A manual override is active, so the model locks the new max to the current max instead of changing it."
        facts = [
            ("Current max: ", f"{format_quantity(current_max)}."),
            ("Override owner: ", str(row.get("per", "")) or "Not provided."),
            ("Override date: ", str(row.get("override_date", "")) or "Not provided."),
            ("Without override: ", f"The policy floor would have been at least {format_quantity(policy_order_up_to)}."),
        ]
        two_point_spike_fact = build_two_point_spike_fact(row)
        if two_point_spike_fact is not None:
            facts.insert(1, two_point_spike_fact)
        single_period_pool_guard_fact = build_single_period_pool_guard_fact(row)
        if single_period_pool_guard_fact is not None:
            facts.insert(1, single_period_pool_guard_fact)
        highest_outlier_fact = build_highest_outlier_fact(row)
        if highest_outlier_fact is not None:
            facts.insert(1, highest_outlier_fact)
        seasonal_ramp_fact = build_seasonal_ramp_fact(row)
        if seasonal_ramp_fact is not None:
            facts.insert(1, seasonal_ramp_fact)
        return title, summary_text, facts

    if bool(row.get("is_balancing_location")):
        balancing_target = balancing_recommendation_value(row, item_rows)
        title = f"Why location {location} new max is {format_quantity(recommended_max)}"
        if bool(row.get("primary_stock_gate_blocked")):
            summary_text = "This is the balancing/DC location, but it was not allowed to become a new stocking point because there is not enough recent selling proof outside of DC pooling."
        else:
            summary_text = "This is the balancing/DC location, so it holds the coverage and variability that should not sit at the branches."
        facts = [
            (
                "Demand basis: ",
                f"{format_quantity(demand_basis, 1)} per month from {mean_source}, rounded to {format_quantity(rounded_mean)} for the balancing rule.",
            ),
            (
                "Balancing target: ",
                f"Company balancing math produced {format_quantity(balancing_target)} after comparing branch rounded demand to branch new max targets.",
            ),
            (
                "Pooled branch protection: ",
                f"{format_quantity(pooled_variance_absorbed, 1)} units come from pooled branch variability using root-sum-square, plus {format_quantity(pooled_direct_absorbed, 1)} direct transfer units from branch spikes or blocked branch stock. That is {format_quantity(row.get('deviation_absorbed_by_dc'), 1)} extra units held here instead of at the branches.",
            ),
            (
                "Final max rule: ",
                f"The model takes the highest of balancing target {format_quantity(balancing_target)}, policy floor {format_quantity(policy_order_up_to)}, and min {format_quantity(recommended_min)}.",
            ),
            (
                "Change from current: ",
                f"Current max is {format_quantity(current_max)}, so the recommendation changes it by {format_quantity(max_delta)}.",
            ),
        ]
        two_point_spike_fact = build_two_point_spike_fact(row)
        if two_point_spike_fact is not None:
            facts.insert(2, two_point_spike_fact)
        non_stockable_fact = build_non_stockable_location_fact(row)
        if non_stockable_fact is not None:
            facts.insert(2, non_stockable_fact)
        single_stocked_hold_fact = build_single_stocked_branch_hold_fact(row)
        if single_stocked_hold_fact is not None:
            facts.insert(2, single_stocked_hold_fact)
        if bool(row.get("primary_stock_gate_blocked")):
            facts.insert(
                3,
                (
                    "New-stock gate: ",
                    f"Location {location} is not getting stocked from its own local signal because the item only sold in {format_quantity(row.get('branch_stock_gate_recent_12_usage_periods'))} months across the last 12 months and is only stocked in {format_quantity(row.get('branch_stock_gate_stocked_locations'))} locations. This gate is skipped only when DC pooling is what creates the recommendation.",
                ),
            )
        if bool(row.get("dc_pooling_zero_max_alert")):
            facts.insert(
                3,
                (
                    "Review flag: ",
                    "The designated DC currently has a max of 0, but pooled branch stock is creating a positive recommendation here. This item should be reviewed before treating the DC as a stocking point.",
                ),
            )
        dc_sparse_active_fact = build_dc_sparse_active_mean_fact(row)
        if dc_sparse_active_fact is not None:
            facts.insert(2, dc_sparse_active_fact)
        highest_outlier_fact = build_highest_outlier_fact(row)
        if highest_outlier_fact is not None:
            facts.insert(1, highest_outlier_fact)
        seasonal_ramp_fact = build_seasonal_ramp_fact(row)
        if seasonal_ramp_fact is not None:
            facts.insert(1, seasonal_ramp_fact)
        return title, summary_text, facts

    base_recommendation = branch_base_recommendation(current_max, rounded_mean)
    branch_target = max(base_recommendation, policy_order_up_to, recommended_min)
    service_level_target = max(
        base_recommendation,
        numeric_value(row.get("service_level_order_up_to")),
        numeric_value(row.get("service_level_min_amount")),
    )
    total_pooled_to_dc = numeric_value(row.get("deviation_pooled_to_dc"))
    title = f"Why location {location} new max is {format_quantity(recommended_max)}"
    if regional_zero_pool:
        summary_text = "This branch stays non-stocked because its current max is 0 and the status contains Regional, so the demand is intentionally handled through the DC instead."
    elif project_spike_suppressed:
        summary_text = "This branch usage was treated as a one-time project/non-replenishment event, so it does not create stock here or at the DC."
    elif keep_dev_local:
        summary_text = "This branch keeps its extra deviation locally because the item cost is below the MAC cutoff set in the dashboard."
    else:
        summary_text = "Branch max is set to cover expected demand and the order cycle without holding the extra deviation buffer locally."
    facts = [
        (
            "Demand basis: ",
            f"{format_quantity(demand_basis, 1)} per month from {mean_source}, rounded to {format_quantity(rounded_mean)}.",
        ),
        (
            "Item cost rule: ",
            f"MAC is ${mac_value:,.2f}. The local-deviation cutoff is ${local_cutoff:,.2f}.",
        ),
        (
            "Base branch target: ",
            f"The branch rule starts at {format_quantity(base_recommendation)} based on the current max and rounded demand.",
        ),
        (
            "Policy floor: ",
            f"Lead time, order cycle, and the branch min create a floor of {format_quantity(policy_order_up_to)} with a minimum of {format_quantity(recommended_min)}.",
        ),
        (
            "Change from current: ",
            f"Current max is {format_quantity(current_max)}, so the recommendation changes it by {format_quantity(max_delta)}.",
        ),
    ]
    if regional_zero_pool:
        facts.insert(
            3,
            (
                "Regional zero-max rule: ",
                "This branch currently has max 0 and the status contains Regional, so the branch is kept non-stocked and its demand signal is pooled to the DC.",
            ),
        )
    if project_spike_suppressed:
        facts.insert(
            2,
            (
                "Project spike suppression: ",
                f"{str(row.get('project_spike_top_month_label', '') or 'The top month')} had {format_quantity(row.get('project_spike_top_month_value'), 1)} units. "
                f"That is {numeric_value(row.get('project_spike_branch_top_month_share_pct')):.0f}% of this branch's last-12-month usage and "
                f"{numeric_value(row.get('project_spike_company_top_month_share_pct')):.0f}% of company last-12-month usage. "
                f"The next-highest company month was only {format_quantity(row.get('project_spike_next_company_month_value'), 1)}, so the event is excluded from both branch and DC replenishment math.",
            ),
        )
    if numeric_value(row.get("negative_usage_netted_months")) > 0:
        facts.insert(
            2,
            (
                "Returns netted backward: ",
                f"{format_quantity(row.get('negative_usage_netted_units'), 1)} units of negative monthly activity across {format_quantity(row.get('negative_usage_netted_months'))} month(s) were applied back to the closest earlier positive month(s) within 12 months so returns do not inflate branch or DC stock."
                + (
                    f" {format_quantity(row.get('negative_usage_unmatched_units'), 1)} units had no earlier positive month and were dropped."
                    if numeric_value(row.get('negative_usage_unmatched_units')) > 0
                    else ""
                ),
            ),
        )
    elif bool(row.get("intermittent_branch_protection_applied")):
        facts.insert(
            2,
            (
                "Intermittent branch rule: ",
                f"This branch only sold in {format_quantity(row.get('intermittent_non_zero_months'))} of {format_quantity(row.get('intermittent_scope_months'))} scoped months. "
                f"ADI is {numeric_value(row.get('intermittent_adi')):.1f}, the top two months make up {numeric_value(row.get('intermittent_top_two_share_pct')):.0f}% of scoped demand, "
                f"and the branch mean is reduced from {format_quantity(row.get('raw_trend_adjusted_mean'), 1)} to {format_quantity(row.get('trend_adjusted_mean'), 1)}.",
            ),
        )
    intermittent_transfer_fact = build_intermittent_transfer_fact(row)
    if intermittent_transfer_fact is not None:
        facts.insert(2, intermittent_transfer_fact)
    non_stockable_fact = build_non_stockable_location_fact(row)
    if non_stockable_fact is not None:
        facts.insert(2, non_stockable_fact)
    single_stocked_hold_fact = build_single_stocked_branch_hold_fact(row)
    if single_stocked_hold_fact is not None:
        facts.insert(2, single_stocked_hold_fact)
    two_point_spike_fact = build_two_point_spike_fact(row)
    if two_point_spike_fact is not None:
        facts.insert(2, two_point_spike_fact)
    highest_outlier_fact = build_highest_outlier_fact(row)
    if highest_outlier_fact is not None:
        facts.insert(2, highest_outlier_fact)
    seasonal_ramp_fact = build_seasonal_ramp_fact(row)
    if seasonal_ramp_fact is not None:
        facts.insert(2, seasonal_ramp_fact)
    if regional_zero_pool:
        facts.insert(
            5,
            (
                "Final max rule: ",
                "The final branch max is forced to 0 so the branch stays non-stocked. The DC carries the pooled demand instead.",
            ),
        )
    elif keep_dev_local:
        facts.insert(
            4,
            (
                "Low-cost local deviation: ",
                f"Because MAC is below the cutoff, {format_quantity(kept_local_amount, 1)} units of deviation stay at this branch instead of moving to the DC.",
            ),
        )
        facts.insert(
            5,
            (
                "Final max rule: ",
                f"The model takes the branch target {format_quantity(branch_target)} and then keeps {format_quantity(kept_local_amount, 1)} extra units locally because the item is below the MAC cutoff.",
            ),
        )
    elif total_pooled_to_dc > 0:
        facts.insert(
            4,
            (
                "Deviation moved to DC: ",
                f"{format_quantity(pooled_variance_to_dc, 1)} units of branch variability are sent to the DC as a pooled-variance input, plus {format_quantity(direct_transfer_to_dc, 1)} direct transfer units from branch spikes or blocked branch stock. That is {format_quantity(total_pooled_to_dc, 1)} total units sent away from this branch.",
            ),
        )
        facts.insert(
            5,
            (
                "Final max rule: ",
                f"The model takes the highest of base {format_quantity(base_recommendation)}, policy floor {format_quantity(policy_order_up_to)}, and min {format_quantity(recommended_min)}.",
            ),
        )
    else:
        facts.insert(
            4,
            (
                "Final max rule: ",
                f"The model takes the highest of base {format_quantity(base_recommendation)}, policy floor {format_quantity(policy_order_up_to)}, and min {format_quantity(recommended_min)}.",
            ),
        )
    if branch_zero_alert:
        facts.append(
            (
                "Review flag: ",
                "This branch currently has max 0, but the model is recommending a positive branch max here. Review whether the branch should start stocking the item.",
            ),
        )
    return title, summary_text, facts


def render_location_calculation_table(item_rows: pd.DataFrame) -> None:
    source_rows = item_rows.loc[:, ~item_rows.columns.duplicated()].copy().reset_index(drop=True)
    if "location_sort" in source_rows.columns:
        source_rows = source_rows.sort_values(["location_sort", "location"], kind="stable").reset_index(drop=True)
    else:
        source_rows["_location_sort"] = source_rows["location"].map(
            lambda value: (0, int(str(value).strip())) if str(value).strip().isdigit() else (1, str(value).strip())
        )
        source_rows = source_rows.sort_values(["_location_sort", "location"], kind="stable").drop(columns="_location_sort").reset_index(drop=True)
    priority_columns = [
        "location",
        "status",
        "mac",
        "override_flag",
        "branch_zero_max_recommendation_alert",
        "regional_zero_max_branch_pool_applied",
        "low_cost_local_deviation_applied",
        "low_cost_local_deviation_kept_amount",
        "dc_pooling_zero_max_alert",
        "min_value",
        "recommended_min_amount",
        "recommended_min_delta",
        "current_max",
        "recommended_new_max",
        "recommendation_delta",
        "net_qoh",
        "policy_order_up_to",
        "protection_days",
        "daily_demand",
        "total_dev",
        "forecast_mode",
        "autogluon_forecast_mean",
        "mean_source",
        "filtered_mean",
        "trend_adjusted_mean",
        "filtered_std_dev",
        "service_level_pct",
        "frequency",
        "lead_time",
        "reference_window_months",
        "yoy_change_pct",
        "seasonal_ramp_applied",
        "seasonal_ramp_factor",
        "seasonal_ramp_window",
        "deviation_pooled_to_dc",
        "deviation_absorbed_by_dc",
        "is_balancing_location",
        "planning_season",
    ]
    display = select_unique_columns(source_rows, priority_columns)
    if display.empty:
        st.info("No location calculations are available for this item.")
        return

    display = display.reset_index(drop=True).copy()
    display["_min_changed"] = (
        pd.to_numeric(display.get("recommended_min_amount"), errors="coerce").fillna(0).round(6)
        != pd.to_numeric(display.get("min_value"), errors="coerce").fillna(0).round(6)
    )
    display["_max_changed"] = (
        pd.to_numeric(display.get("recommended_new_max"), errors="coerce").fillna(0).round(6)
        != pd.to_numeric(display.get("current_max"), errors="coerce").fillna(0).round(6)
    )

    for column in ["override_flag", "is_balancing_location", "low_cost_local_deviation_applied", "regional_zero_max_branch_pool_applied", "seasonal_ramp_applied"]:
        if column in display.columns:
            display[column] = display[column].map(format_boolean_cell)
    if "branch_zero_max_recommendation_alert" in display.columns:
        display["branch_zero_max_recommendation_alert"] = display["branch_zero_max_recommendation_alert"].map(
            lambda value: "Review branch new stock" if bool(value) else ""
        )
    if "dc_pooling_zero_max_alert" in display.columns:
        display["dc_pooling_zero_max_alert"] = display["dc_pooling_zero_max_alert"].map(
            lambda value: "Review DC zero-max" if bool(value) else ""
        )
    if "intermittent_branch_protection_applied" in display.columns:
        display["intermittent_branch_protection_applied"] = display["intermittent_branch_protection_applied"].map(
            format_boolean_cell
        )

    renamed = display.rename(
        columns={
            "location": "Location ID",
            "status": "Status",
            "mac": "MAC",
            "override_flag": "Override",
            "branch_zero_max_recommendation_alert": "Branch Stock Alert",
            "regional_zero_max_branch_pool_applied": "Regional Pool Rule",
            "low_cost_local_deviation_applied": "Keep Dev Local",
            "low_cost_local_deviation_kept_amount": "Dev Kept Local",
            "dc_pooling_zero_max_alert": "DC Pool Alert",
            "min_value": "Current Min",
            "recommended_min_amount": "New Min",
            "recommended_min_delta": "Min Delta",
            "current_max": "Current Max",
            "recommended_new_max": "New Max",
            "recommendation_delta": "Max Delta",
            "net_qoh": "Net QOH",
            "policy_order_up_to": "Policy Max",
            "protection_days": "Protection Days",
            "daily_demand": "Daily Demand",
            "total_dev": "Deviation",
            "forecast_mode": "Forecast Mode",
            "autogluon_forecast_mean": "AI Forecast",
            "mean_source": "Mean Source",
            "intermittent_branch_protection_applied": "Intermittent Rule",
            "filtered_mean": "Historical Mean",
            "raw_filtered_mean": "Raw Active Mean",
            "trend_adjusted_mean": "Demand Basis",
            "raw_trend_adjusted_mean": "Raw Demand Basis",
            "filtered_std_dev": "Std Dev",
            "raw_rounded_mean": "Raw Rounded Mean",
            "service_level_pct": "Service Level %",
            "frequency": "Frequency",
            "lead_time": "Lead Time",
            "reference_window_months": "Ref Months",
            "yoy_change_pct": "YOY %",
            "seasonal_ramp_applied": "Current Window Ramp",
            "seasonal_ramp_factor": "Ramp Factor",
            "seasonal_ramp_window": "Ramp Window",
            "deviation_pooled_to_dc": "Pooled to DC",
            "deviation_absorbed_by_dc": "Absorbed by DC",
            "is_balancing_location": "Balancing Loc",
            "planning_season": "Planning Season",
        }
    )
    renamed = renamed.reset_index(drop=True)

    renamed["New Min"] = [
        build_calc_popover_html(
            format_quantity(row.get("recommended_min_amount")),
            *build_min_explanation(row),
        )
        for _, row in source_rows.iterrows()
    ]
    renamed["New Max"] = [
        build_calc_popover_html(
            format_quantity(row.get("recommended_new_max")),
            *build_max_explanation(row, source_rows),
        )
        for _, row in source_rows.iterrows()
    ]

    def highlight_changes(row: pd.Series) -> pd.Series:
        styles = pd.Series("", index=row.index)
        min_changed = bool(row.get("_min_changed", False))
        max_changed = bool(row.get("_max_changed", False))
        branch_zero_alert = bool(str(row.get("Branch Stock Alert", "")).strip())
        dc_pool_alert = bool(str(row.get("DC Pool Alert", "")).strip())
        if min_changed:
            for column in ["Current Min", "New Min", "Min Delta"]:
                if column in styles.index:
                    styles[column] = "background-color: #fff2c2; color: #5f4600; font-weight: 700;"
        if max_changed:
            for column in ["Current Max", "New Max", "Max Delta", "Policy Max"]:
                if column in styles.index:
                    styles[column] = "background-color: #dff3e6; color: #173b2f; font-weight: 700;"
        if branch_zero_alert:
            for column in ["Location ID", "Current Max", "New Max", "Max Delta", "Branch Stock Alert"]:
                if column in styles.index:
                    styles[column] = "background-color: #ffe6c7; color: #7c3f00; font-weight: 800;"
        if dc_pool_alert:
            for column in ["Location ID", "Current Max", "New Max", "Max Delta", "Absorbed by DC", "DC Pool Alert"]:
                if column in styles.index:
                    styles[column] = "background-color: #ffd9d9; color: #7f1d1d; font-weight: 800;"
        if "Location ID" in styles.index:
            if dc_pool_alert:
                styles["Location ID"] = "font-weight: 800; border-left: 4px solid #c53030;"
            elif branch_zero_alert:
                styles["Location ID"] = "font-weight: 800; border-left: 4px solid #dd6b20;"
            elif min_changed or max_changed:
                styles["Location ID"] = "font-weight: 700; border-left: 4px solid #8a6f1e;"
            else:
                styles["Location ID"] = "font-weight: 700;"
        return styles

    format_map = {
        "MAC": "{:,.2f}",
        "Current Min": "{:,.0f}",
        "Min Delta": "{:,.0f}",
        "Current Max": "{:,.0f}",
        "Max Delta": "{:,.0f}",
        "Dev Kept Local": "{:,.2f}",
        "Net QOH": "{:,.0f}",
        "Policy Max": "{:,.0f}",
        "Protection Days": "{:,.0f}",
        "Daily Demand": "{:,.2f}",
        "Deviation": "{:,.2f}",
        "AI Forecast": "{:,.2f}",
        "Historical Mean": "{:,.2f}",
        "Raw Active Mean": "{:,.2f}",
        "Demand Basis": "{:,.2f}",
        "Raw Demand Basis": "{:,.2f}",
        "Std Dev": "{:,.2f}",
        "Raw Rounded Mean": "{:,.0f}",
        "Service Level %": "{:,.0f}",
        "Ref Months": "{:,.0f}",
        "YOY %": "{:,.1f}",
        "Ramp Factor": "{:,.2f}",
        "Pooled to DC": "{:,.2f}",
        "Absorbed by DC": "{:,.2f}",
    }

    styler = (
        renamed.style
        .format(format_map, na_rep="")
        .apply(highlight_changes, axis=1)
        .hide(axis="index")
        .hide(axis="columns", subset=["_min_changed", "_max_changed"])
        .set_uuid("location_calculation")
    )

    st.caption("Location stays pinned on the left. Highlighted min and max cells show where the recommendation changes the current setting. Orange-highlighted rows mean a branch currently at max 0 is being recommended stock. Red-highlighted DC rows mean pooled branch stock is creating a max where the DC currently has none. `Current Window Ramp` shows where seasonality narrowed the demand basis to the next protected replenishment window instead of the whole season. Click a New Min or New Max value to open a plain-English explanation.")
    st.markdown(f'<div class="location-calculation-shell">{styler.to_html()}</div>', unsafe_allow_html=True)

    with st.expander("Show full calculation fields"):
        full_columns = [
            "location",
            "season",
            "status",
            "mac",
            "abc",
            "service_level_pct",
            "override_flag",
            "per",
            "override_date",
            "frequency",
            "frequency_days",
            "lead_time",
            "lead_time_days",
            "raw_protection_days",
            "protection_days",
            "demand_only_min_amount",
            "service_level_min_amount",
            "dc_transfer_reserve_amount",
            "demand_only_order_up_to",
            "service_level_order_up_to",
            "minimum_28_day_rule_applied",
            "dc_location_reserve_rule_applied",
            "deviation_pooled_to_dc",
            "deviation_absorbed_by_dc",
            "dc_sparse_active_mean_fallback_applied",
            "dc_sparse_active_mean_fallback_reason",
            "dc_sparse_active_mean_fallback_active_mean",
            "dc_sparse_active_mean_fallback_inclusive_mean",
            "single_stocked_branch_hold_applied",
            "single_stocked_branch_hold_location",
            "non_stockable_location_blocked",
            "single_period_pool_guard_applied",
            "single_period_pool_guard_reason",
            "forecast_mode",
            "forecast_used",
            "autogluon_forecast_mean",
            "mean_source",
            "two_point_spike_normalized",
            "two_point_spike_normalized_month_mean",
            "two_point_spike_normalized_value_mean",
            "two_point_spike_normalized_baseline_value_mean",
            "two_point_spike_normalized_ratio_mean",
            "reference_window_months",
            "yoy_change_pct",
            "reference_window_rule",
            "product_group_trend_label",
            "product_group_trend_factor",
            "product_group_trend_source",
            "product_group_recent_avg",
            "product_group_prior_avg",
            "product_group_trend_scope",
            "seasonal_ramp_applied",
            "seasonal_ramp_factor",
            "seasonal_ramp_mode",
            "seasonal_ramp_reason",
            "seasonal_ramp_window",
            "seasonal_ramp_start_date",
            "seasonal_ramp_window_average",
            "seasonal_ramp_full_season_average",
            "seasonal_ramp_non_zero_points",
            "seasonal_ramp_distinct_months",
            "seasonal_ramp_peak_month",
            "highest_outlier_filter_enabled",
            "highest_outlier_threshold_pct",
            "highest_outlier_removed",
            "highest_outlier_removed_from_mean",
            "highest_outlier_removed_from_std",
            "highest_outlier_removed_month_mean",
            "highest_outlier_removed_month_std",
            "highest_outlier_removed_value_mean",
            "highest_outlier_removed_value_std",
            "highest_outlier_baseline_value_mean",
            "highest_outlier_baseline_value_std",
            "highest_outlier_trigger_pct_mean",
            "highest_outlier_trigger_pct_std",
            "intermittent_branch_protection_applied",
            "intermittent_scope_months",
            "intermittent_non_zero_months",
            "intermittent_adi",
            "intermittent_top_two_share_pct",
            "intermittent_inclusive_mean",
            "intermittent_reason",
            "raw_intermittent_direct_transfer",
            "intermittent_direct_transfer_allowed",
            "intermittent_direct_transfer_suppressed",
            "intermittent_spike_pooled_to_dc",
            "branch_zero_max_recommendation_alert",
            "regional_zero_max_branch_pool_applied",
            "low_cost_local_deviation_threshold",
            "low_cost_local_deviation_applied",
            "low_cost_local_deviation_kept_amount",
            "dc_pooling_zero_max_alert",
            "pre_phase_filtered_mean",
            "pre_phase_trend_adjusted_mean",
            "raw_filtered_mean",
            "raw_filtered_std_dev",
            "raw_trend_adjusted_mean",
            "raw_rounded_mean",
            "min_value",
            "recommended_min_amount",
            "recommended_min_delta",
            "net_qoh",
            "current_max",
            "policy_order_up_to",
            "recommended_new_max",
            "recommendation_delta",
            "filtered_mean",
            "trend_adjusted_mean",
            "daily_demand",
            "filtered_std_dev",
            "rounded_mean",
            "delta",
            "total_dev",
            "review_cycle_days",
            "active_months_mean",
            "active_months_std",
            "planning_season",
            "mean_month_scope",
            "std_month_scope",
            "is_balancing_location",
            "seasonality_note",
            "recommendation_explanation",
        ]
        st.dataframe(
            select_unique_columns(item_rows, full_columns),
            use_container_width=True,
            hide_index=True,
        )


def render_usage_trend_chart(item_rows: pd.DataFrame, monthly_columns: list[str], selection_key: str) -> None:
    if item_rows.empty:
        st.info("No location history is available for this item.")
        return

    month_order = ordered_month_labels(monthly_columns)
    location_options = sort_location_values(item_rows["location"].astype(str).tolist())
    selected_locations = render_excel_like_filter(
        st,
        "Locations to show",
        location_options,
        key=f"trend_locations_{selection_key}",
        default_values=location_options,
        help_text="Use Select all, Clear all, or choose multiple locations like an Excel filter.",
        expanded=True,
    )
    if not selected_locations:
        st.info("Select at least one location to draw the 24-month usage trend.")
        return

    chart_rows: list[dict[str, object]] = []
    total_recommended_max = float(pd.to_numeric(item_rows.get("recommended_new_max"), errors="coerce").fillna(0).sum())
    for row in item_rows.to_dict(orient="records"):
        location = str(row["location"])
        if location not in selected_locations:
            continue
        recommended_min = float(row["recommended_min_amount"])
        recommended_max = float(row["recommended_new_max"])
        for month_label in month_order:
            chart_rows.append(
                {
                    "month": month_label,
                    "location": location,
                    "usage": float(row.get(month_label, 0.0)),
                    "recommended_min": recommended_min,
                    "recommended_max": recommended_max,
                }
            )

    chart_frame = pd.DataFrame(chart_rows)
    total_max_frame = pd.DataFrame(
        {
            "month": month_order,
            "recommended_max_total": [total_recommended_max] * len(month_order),
            "series": ["Total Company Recommended Max"] * len(month_order),
        }
    )
    usage_chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", sort=month_order, title="Month"),
            y=alt.Y("usage:Q", title="Usage"),
            color=alt.Color("location:N", title="Location"),
            tooltip=[
                alt.Tooltip("month:N", title="Month"),
                alt.Tooltip("location:N", title="Location"),
                alt.Tooltip("usage:Q", title="Usage", format=",.0f"),
                alt.Tooltip("recommended_min:Q", title="Recommended Min", format=",.0f"),
                alt.Tooltip("recommended_max:Q", title="Recommended Max", format=",.0f"),
            ],
        )
        .properties(height=360)
    )
    total_max_chart = (
        alt.Chart(total_max_frame)
        .mark_line(color="#173b2f", strokeDash=[8, 5], size=2)
        .encode(
            x=alt.X("month:N", sort=month_order, title="Month"),
            y=alt.Y("recommended_max_total:Q", title="Usage"),
            tooltip=[
                alt.Tooltip("month:N", title="Month"),
                alt.Tooltip("series:N", title="Reference"),
                alt.Tooltip("recommended_max_total:Q", title="Recommended Max Total", format=",.0f"),
            ],
        )
    )
    chart = alt.layer(total_max_chart, usage_chart).resolve_scale(y="shared")
    st.caption("Use Select all or Clear all to control the location lines. The dashed line is the total company recommended max.")
    st.altair_chart(chart, use_container_width=True)


def build_monthly_usage_matrix(item_rows: pd.DataFrame, monthly_columns: list[str]) -> pd.DataFrame:
    month_order = ordered_month_labels(monthly_columns)
    matrix = select_unique_columns(item_rows, ["location", *month_order])
    if matrix.empty:
        return matrix

    matrix = matrix.copy()
    matrix["_location_sort"] = matrix["location"].map(
        lambda value: (0, int(str(value).strip())) if str(value).strip().isdigit() else (1, str(value).strip())
    )
    matrix = matrix.sort_values("_location_sort", kind="stable").drop(columns="_location_sort").reset_index(drop=True)
    for month_label in month_order:
        matrix[month_label] = pd.to_numeric(matrix[month_label], errors="coerce").fillna(0.0)

    total_row: dict[str, object] = {"location": "Total Usage"}
    for month_label in month_order:
        total_row[month_label] = float(matrix[month_label].sum())

    return pd.concat([matrix, pd.DataFrame([total_row])], ignore_index=True)


def build_supplier_summary(summary: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(
            columns=[
                "supplier",
                "items_count",
                "changed_items",
                "changed_locations",
                "forecast_coverage_locations",
                "total_current_min",
                "total_recommended_min_amount",
                "recommended_min_delta",
                "total_current_max",
                "total_recommended_new_max",
                "recommendation_delta",
                "total_deviation_pooled_to_dc",
                "low_cost_local_deviation_locations",
                "dc_zero_max_pool_alert_items",
                "avg_yoy_change_pct",
                "top_change_item",
                "top_change_delta",
            ]
        )

    supplier_summary = (
        summary.groupby("supplier", dropna=False)
        .agg(
            items_count=("item", "nunique"),
            changed_items=("recommendation_delta", lambda values: int((values != 0).sum())),
            forecast_coverage_locations=("forecast_coverage_locations", "sum"),
            total_current_min=("total_current_min", "sum"),
            total_recommended_min_amount=("total_recommended_min_amount", "sum"),
            recommended_min_delta=("recommended_min_delta", "sum"),
            total_current_max=("total_current_max", "sum"),
            total_recommended_new_max=("total_recommended_new_max", "sum"),
            recommendation_delta=("recommendation_delta", "sum"),
            total_deviation_pooled_to_dc=("total_deviation_pooled_to_dc", "sum"),
            low_cost_local_deviation_locations=("low_cost_local_deviation_locations", "sum"),
            dc_zero_max_pool_alert_items=("dc_pooling_zero_max_alert", lambda values: int(pd.Series(values).fillna(False).astype(bool).sum())),
            avg_yoy_change_pct=("yoy_change_pct", "mean"),
        )
        .reset_index()
    )

    if detail.empty:
        detail_rollup = pd.DataFrame(columns=["supplier", "changed_locations"])
    else:
        detail_rollup = (
            detail.groupby("supplier", dropna=False)
            .agg(changed_locations=("recommendation_delta", lambda values: int((values != 0).sum())))
            .reset_index()
        )

    ranked_items = summary.assign(abs_recommendation_delta=summary["recommendation_delta"].abs()).sort_values(
        ["supplier", "abs_recommendation_delta", "item"],
        ascending=[True, False, True],
        kind="stable",
    )
    top_changes = (
        ranked_items.groupby("supplier", dropna=False)
        .first()
        .reset_index()[["supplier", "item", "recommendation_delta"]]
        .rename(columns={"item": "top_change_item", "recommendation_delta": "top_change_delta"})
    )

    supplier_summary = supplier_summary.merge(detail_rollup, on="supplier", how="left")
    supplier_summary = supplier_summary.merge(top_changes, on="supplier", how="left")
    supplier_summary["changed_locations"] = supplier_summary["changed_locations"].fillna(0).astype(int)
    supplier_summary["top_change_item"] = supplier_summary["top_change_item"].fillna("")
    supplier_summary["top_change_delta"] = pd.to_numeric(
        supplier_summary["top_change_delta"], errors="coerce"
    ).fillna(0.0)
    supplier_summary["abs_recommendation_delta"] = supplier_summary["recommendation_delta"].abs()
    supplier_summary = supplier_summary.sort_values(
        ["abs_recommendation_delta", "changed_items", "supplier"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)
    return supplier_summary


def apply_filters(
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    raw: pd.DataFrame,
    supplier_filter: list[str],
    status_filter: list[str],
    prod_group_filter: list[str],
    abc_filter: list[str],
    season_filter: list[str],
    changed_only: bool,
    search_text: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    filtered_summary = summary.copy()

    if supplier_filter is not None:
        filtered_summary = filtered_summary[filtered_summary["supplier"].isin(supplier_filter)]
    if status_filter is not None:
        filtered_summary = filtered_summary[filtered_summary["status"].isin(status_filter)]
    if prod_group_filter is not None:
        filtered_summary = filtered_summary[filtered_summary["prod_group"].isin(prod_group_filter)]
    if abc_filter is not None:
        filtered_summary = filtered_summary[filtered_summary["abc"].isin(abc_filter)]
    if season_filter is not None:
        filtered_summary = filtered_summary[filtered_summary["season"].isin(season_filter)]
    if changed_only:
        filtered_summary = filtered_summary[filtered_summary["recommendation_delta"] != 0]
    if search_text:
        search_value = search_text.casefold()
        mask = (
            filtered_summary["item"].str.casefold().str.contains(search_value)
            | filtered_summary["description"].str.casefold().str.contains(search_value)
            | filtered_summary["supplier"].str.casefold().str.contains(search_value)
        )
        filtered_summary = filtered_summary[mask]

    keys = filtered_summary[["supplier", "item"]].drop_duplicates()
    filtered_detail = detail.merge(keys, on=["supplier", "item"], how="inner")
    filtered_raw = raw.merge(keys, on=["supplier", "item"], how="inner")
    return filtered_summary, filtered_detail, filtered_raw


def display_metric_strip(summary: pd.DataFrame, detail: pd.DataFrame) -> None:
    suppliers = int(summary["supplier"].nunique()) if not summary.empty else 0
    items = int(summary["item"].nunique()) if not summary.empty else 0
    current_min_total = float(summary["total_current_min"].sum()) if ("total_current_min" in summary.columns and not summary.empty) else 0.0
    recommended_min_total = float(summary["total_recommended_min_amount"].sum()) if ("total_recommended_min_amount" in summary.columns and not summary.empty) else 0.0
    current_total = float(summary["total_current_max"].sum()) if not summary.empty else 0.0
    new_total = float(summary["total_recommended_new_max"].sum()) if not summary.empty else 0.0
    changed_locations = int((detail["recommendation_delta"] != 0).sum()) if not detail.empty else 0

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Suppliers", suppliers)
    col2.metric("Items", items)
    col3.metric("Current Min Total", f"{current_min_total:,.0f}")
    col4.metric("Recommended Min Total", f"{recommended_min_total:,.0f}", delta=f"{recommended_min_total - current_min_total:,.0f}")
    col5.metric("Recommended Max Total", f"{new_total:,.0f}", delta=f"{new_total - current_total:,.0f}")
    col6.metric("Changed Locations", f"{changed_locations:,}")


def split_dashboard_views(
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    raw: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    summary = ensure_dashboard_category(summary)
    detail = ensure_dashboard_category(detail)
    main_summary = summary.copy()
    main_detail = detail.copy()
    main_raw = raw.copy()
    supplier_summary = build_supplier_summary(main_summary, main_detail)

    return {
        "main_summary": main_summary,
        "main_detail": main_detail,
        "main_raw": main_raw,
        "supplier_summary": supplier_summary,
    }


def subset_by_summary(
    summary_subset: pd.DataFrame,
    detail: pd.DataFrame,
    raw: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if summary_subset.empty:
        return detail.iloc[0:0].copy(), raw.iloc[0:0].copy()

    keys = summary_subset[["supplier", "item"]].drop_duplicates()
    detail_subset = detail.merge(keys, on=["supplier", "item"], how="inner")
    raw_subset = raw.merge(keys, on=["supplier", "item"], how="inner")
    return detail_subset, raw_subset


def selected_rows_from_event(event: object) -> list[int]:
    if event is None:
        return []

    selection = getattr(event, "selection", None)
    if selection is not None:
        rows = getattr(selection, "rows", None)
        if rows is not None:
            return list(rows)
        if isinstance(selection, dict):
            return list(selection.get("rows", []))

    if isinstance(event, dict):
        return list(event.get("selection", {}).get("rows", []))

    return []


def jump_to_supplier_drilldown(supplier_subset: pd.DataFrame, selected_row_index: int) -> None:
    if supplier_subset.empty:
        return

    selected_supplier = supplier_subset.iloc[selected_row_index]["supplier"]
    st.session_state["selected_supplier"] = selected_supplier
    st.session_state["pending_dashboard_view"] = "Supplier Drill-Down"
    st.rerun()


def jump_to_drilldown(summary_subset: pd.DataFrame, selected_row_index: int) -> None:
    if summary_subset.empty:
        return

    selected_key = summary_subset.iloc[selected_row_index]["group_key"]
    st.session_state["selected_group_key"] = selected_key
    st.session_state["pending_dashboard_view"] = "Item Drill-Down"
    st.rerun()


def render_supplier_summary_table(
    supplier_subset: pd.DataFrame,
    table_key: str,
    empty_message: str,
) -> None:
    if supplier_subset.empty:
        st.info(empty_message)
        return

    display_source = supplier_subset.reset_index(drop=True)
    display_frame = display_source[
        [
            "supplier",
            "items_count",
            "changed_items",
            "changed_locations",
            "forecast_coverage_locations",
            "total_current_min",
            "total_recommended_min_amount",
            "recommended_min_delta",
            "total_current_max",
            "total_recommended_new_max",
            "recommendation_delta",
            "total_deviation_pooled_to_dc",
            "low_cost_local_deviation_locations",
            "dc_zero_max_pool_alert_items",
            "avg_yoy_change_pct",
            "top_change_item",
            "top_change_delta",
        ]
    ].copy()
    display_frame = display_frame.rename(
        columns={
            "low_cost_local_deviation_locations": "Low-Cost Local Dev Locs",
            "dc_zero_max_pool_alert_items": "DC Zero-Max Pool Alerts",
        }
    )

    event = st.dataframe(
        display_frame,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
    )
    selected_rows = selected_rows_from_event(event)
    if selected_rows:
        selected_supplier = display_source.iloc[selected_rows[0]]["supplier"]
        selection_token = f"{table_key}:{selected_supplier}"
        if st.session_state.get("last_handled_selection") != selection_token:
            st.session_state["last_handled_selection"] = selection_token
            jump_to_supplier_drilldown(display_source, selected_rows[0])

    st.caption("Click a supplier row to open the supplier drill-down.")


def render_summary_table(
    summary_subset: pd.DataFrame,
    table_key: str,
    empty_message: str,
) -> None:
    if summary_subset.empty:
        st.info(empty_message)
        return

    display_source = summary_subset.reset_index(drop=True)
    display_frame = display_source[
        [
            "supplier",
            "prod_group",
            "item",
            "description",
            "status",
            "abc",
            "service_level_pct",
            "season",
            "frequency",
            "lead_time",
            "branch_zero_max_recommendation_locations",
            "regional_zero_max_branch_pool_locations",
            "branch_zero_max_recommendation_alert",
            "low_cost_local_deviation_locations",
            "dc_pooling_zero_max_alert",
            "has_override",
            "override_locations",
            "primary_location",
            "total_current_min",
            "total_recommended_min_amount",
            "recommended_min_delta",
            "total_current_max",
            "total_recommended_new_max",
            "recommendation_delta",
            "total_deviation_pooled_to_dc",
            "forecast_mode",
            "forecast_coverage_locations",
            "changed_locations",
            "reference_window_months",
            "yoy_change_pct",
            "reference_window_rule",
            "product_group_trend_label",
            "product_group_trend_factor",
            "product_group_trend_source",
            "planning_season",
            "seasonal_months_used",
            "max_company_month",
            "max_total_dev",
            "peak_month",
            "seasonality_note",
        ]
    ].copy()
    if "dc_pooling_zero_max_alert" in display_frame.columns:
        display_frame["dc_pooling_zero_max_alert"] = display_frame["dc_pooling_zero_max_alert"].map(
            lambda value: "Review DC zero-max" if bool(value) else ""
        )
    if "branch_zero_max_recommendation_alert" in display_frame.columns:
        display_frame["branch_zero_max_recommendation_alert"] = display_frame["branch_zero_max_recommendation_alert"].map(
            lambda value: "Review branch new stock" if bool(value) else ""
        )
    display_frame = display_frame.rename(
        columns={
            "branch_zero_max_recommendation_locations": "Branch Zero-Max Recs",
            "regional_zero_max_branch_pool_locations": "Regional Pooled Branches",
            "branch_zero_max_recommendation_alert": "Branch Stock Alert",
            "low_cost_local_deviation_locations": "Low-Cost Local Dev Locs",
            "dc_pooling_zero_max_alert": "DC Pool Alert",
        }
    )

    event = st.dataframe(
        display_frame,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
    )
    selected_rows = selected_rows_from_event(event)
    if selected_rows:
        selected_key = display_source.iloc[selected_rows[0]]["group_key"]
        selection_token = f"{table_key}:{selected_key}"
        if st.session_state.get("last_handled_selection") != selection_token:
            st.session_state["last_handled_selection"] = selection_token
            jump_to_drilldown(display_source, selected_rows[0])

    st.caption("Click a row to open the item drill-down.")


def resolve_selected_supplier(supplier_summary: pd.DataFrame) -> str:
    if supplier_summary.empty:
        return ""

    selected_supplier = st.session_state.get("selected_supplier", "")
    available_suppliers = set(supplier_summary["supplier"])
    if selected_supplier not in available_suppliers:
        selected_supplier = supplier_summary.iloc[0]["supplier"]
        st.session_state["selected_supplier"] = selected_supplier
    return str(selected_supplier)


def resolve_selected_item(summary: pd.DataFrame, preferred_summary: pd.DataFrame) -> pd.Series | None:
    summary = ensure_dashboard_category(summary)
    if summary.empty:
        return None

    selected_key = st.session_state.get("selected_group_key", "")
    available_keys = set(summary["group_key"])
    if selected_key not in available_keys:
        if not preferred_summary.empty:
            selected_key = preferred_summary.iloc[0]["group_key"]
        else:
            selected_key = summary.iloc[0]["group_key"]
        st.session_state["selected_group_key"] = selected_key

    match = summary[summary["group_key"] == selected_key]
    if match.empty:
        return None
    return match.iloc[0]


def render_override_popovers(item_rows: pd.DataFrame) -> None:
    override_rows = item_rows[item_rows["override_flag"]].reset_index(drop=True)
    if override_rows.empty:
        return

    st.markdown("#### Override details")
    st.markdown(
        '<p class="section-note">Click an override max below to see the manual override notes from the source data.</p>',
        unsafe_allow_html=True,
    )

    columns = st.columns(min(4, max(len(override_rows), 1)))
    for index, row in override_rows.iterrows():
        column = columns[index % len(columns)]
        with column:
            with st.popover(f"Loc {row['location']} Max {float(row['recommended_new_max']):,.0f}"):
                st.write(f"Supplier: {row['supplier']}")
                st.write(f"Item: {row['item']}")
                st.write(f"Location: {row['location']}")
                st.write(f"Override: {row['override'] or 'Y'}")
                st.write(f"Per: {row['per'] or '-'}")
                st.write(f"Oride Date: {row['override_date'] or '-'}")
                st.write(f"Current Max: {float(row['current_max']):,.0f}")
                st.write(f"Recommended Max: {float(row['recommended_new_max']):,.0f}")


def ensure_dashboard_category(frame: pd.DataFrame) -> pd.DataFrame:
    if "dashboard_category" in frame.columns:
        return frame

    normalized = frame.copy()
    if "status" in normalized.columns:
        normalized["dashboard_category"] = normalized["status"].map(classify_dashboard_category)
    else:
        normalized["dashboard_category"] = "Recommendations"
    return normalized


def classify_dashboard_category(status: object) -> str:
    return "Recommendations"


def main() -> None:
    inject_styles()
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">Deviation Dash</div>
            <h1>Replenishment Workbench</h1>
            <p>Upload raw supplier demand, review recommendation outputs by item and location, and drill into the exact math behind each recommendation before anything becomes a buying decision.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    uploaded_file = st.sidebar.file_uploader("Import raw Excel data", type=["xlsx", "xlsm"])
    st.sidebar.caption("Use the workbook that contains the raw `Data` tab. Multiple suppliers can be present in the same file.")

    if not uploaded_file:
        st.markdown(
            """
            <div class="callout">
                <strong>How this first version works:</strong> upload the raw workbook, pick a recommendation method, then review the item summary, location recommendations, and drill-down math for any item.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.info("Upload a workbook in the sidebar to start the dashboard.")
        return

    try:
        file_bytes = uploaded_file.getvalue()
        simulation_as_of_date = st.sidebar.date_input(
            "Simulation as-of date",
            value=date.today(),
            help="Use this date to simulate what the model would recommend at that point in time.",
        )
        if isinstance(simulation_as_of_date, datetime):
            simulation_as_of_date = simulation_as_of_date.date()
        suggested_season = default_planning_season(simulation_as_of_date)
        seasonality_enabled = st.sidebar.checkbox("Apply seasonality focus", value=True)
        historical_replay_mode = st.sidebar.checkbox(
            "Historical replay mode",
            value=True,
            help="When enabled, months after the simulation date are hidden from the model so a past-date simulation does not use future history.",
        )
        prefer_gpu = st.sidebar.checkbox("Use GPU acceleration when available", value=False)
        acceleration = detect_acceleration(prefer_gpu=prefer_gpu)
        autogluon_status = detect_autogluon()
        saved_forecast = load_saved_forecast_artifact(default_model_dir(PROJECT_ROOT))
        planning_season = st.sidebar.selectbox(
            "Planning season",
            options=["Summer", "Winter"],
            index=0 if suggested_season == "Summer" else 1,
            disabled=not seasonality_enabled,
        )
        service_levels_pct: dict[str, float] = {}
        with st.sidebar.expander("Service level policy", expanded=True):
            st.caption("Changing any percentage recalculates min and max recommendations immediately.")
            st.button(
                "Reset to defaults",
                key="reset_service_levels",
                on_click=reset_service_level_inputs,
                use_container_width=True,
            )
            service_level_columns = st.columns(2)
            for index, code in enumerate(SERVICE_LEVEL_ORDER):
                with service_level_columns[index % 2]:
                    service_levels_pct[code] = float(
                        st.number_input(
                            f"Class {code} %",
                            min_value=1.0,
                            max_value=99.9,
                            value=float(DEFAULT_SERVICE_LEVELS[code] * 100),
                            step=0.5,
                            format="%.1f",
                            key=service_level_input_key(code),
                        )
                    )
        cheap_local_deviation_threshold = float(
            st.sidebar.number_input(
                "Keep deviation local below MAC $",
                min_value=0.0,
                value=1.0,
                step=0.25,
                format="%.2f",
                help="If MAC is below this dollar amount, the branch keeps its deviation locally instead of pooling it to the DC.",
            )
        )
        remove_highest_outlier_enabled = True
        st.sidebar.caption(
            "Highest-month normalization is on by default. The model compares the highest non-zero scoped month to the median of the other non-zero scoped months and resets one highest month down to a standard-month baseline when it exceeds the threshold."
        )
        highest_outlier_threshold_pct = float(
            st.sidebar.number_input(
                "Highest month threshold %",
                min_value=100.0,
                value=float(DEFAULT_HIGHEST_OUTLIER_THRESHOLD_PCT),
                step=25.0,
                format="%.0f",
                help="Example: 200% means the highest non-zero month is normalized only if it is more than 2x the median of the other non-zero scoped months. The rule only applies when at least 3 non-zero months exist in scope.",
            )
        )
        service_levels = {code: value / 100.0 for code, value in service_levels_pct.items()}
        service_levels_json = json.dumps(service_levels, sort_keys=True)
        st.sidebar.caption("Summer uses April-September months. Winter uses October-March months.")
        if using_custom_service_levels(service_levels_pct):
            st.sidebar.caption(f"Custom service levels active: {service_level_policy_summary(service_levels_pct)}")
        else:
            st.sidebar.caption(f"Default service levels active: {service_level_policy_summary(service_levels_pct)}")
        st.sidebar.caption(
            f"Low-cost branch rule: items with MAC below `${cheap_local_deviation_threshold:,.2f}` keep deviation at the branch."
        )
        st.sidebar.caption(
            f"Highest-month outlier filter: normalize one highest scoped month to a standard-month baseline when it exceeds `{highest_outlier_threshold_pct:,.0f}%` of the median of the other non-zero scoped months."
        )
        st.sidebar.caption(f"Simulation date: `{simulation_as_of_date.isoformat()}`")
        if historical_replay_mode:
            st.sidebar.caption("Historical replay is on: months after the simulation date are excluded from the model.")
        else:
            st.sidebar.caption("Historical replay is off: the simulation date shifts the planning window but keeps full workbook history available.")
        st.sidebar.caption(f"{acceleration.label}: {acceleration.detail}")
        if acceleration.backend == "gpu-wsl-cudf":
            st.sidebar.caption("Interactive recalculations are often faster on CPU than WSL GPU. Turn GPU on only when it helps.")
        if remove_highest_outlier_enabled and acceleration.backend == "gpu-wsl-cudf":
            st.sidebar.caption("Highest-month outlier normalization currently uses the CPU rule path to keep the calculations exact.")
        if seasonality_enabled and acceleration.backend == "gpu-wsl-cudf":
            st.sidebar.caption("Current replenishment-window seasonality currently uses the CPU rule path so the seasonal ramp math stays exact.")
        st.sidebar.caption(f"AutoGluon: {autogluon_status.detail}")

        use_ai_forecast = False
        forecast_csv_bytes = None
        ai_forecast_simulation_supported = not historical_replay_mode and simulation_as_of_date == date.today()
        if saved_forecast is not None:
            metadata = saved_forecast.metadata
            source_name = str(metadata.get("source_name", "") or "-")
            trained_at = str(metadata.get("trained_at", "") or "-")
            series_count = int(metadata.get("series_count", 0) or 0)
            st.sidebar.caption(
                f"Saved AI forecast found from `{source_name}` trained `{trained_at}` across `{series_count}` series."
            )
            if ai_forecast_simulation_supported:
                use_ai_forecast = st.sidebar.checkbox("Use AI Forecast + Rules", value=False)
                forecast_csv_bytes = saved_forecast.forecasts.to_csv(index=False).encode("utf-8")
            else:
                st.sidebar.checkbox("Use AI Forecast + Rules", value=False, disabled=True)
                st.sidebar.caption(
                    "AI Forecast + Rules is disabled for simulated dates or historical replay because the saved forecast artifact is not date-aware."
                )
        else:
            st.sidebar.caption(
                "No saved AutoGluon forecast is available yet. Run `install_autogluon.bat`, then `train_autogluon.bat` to create one."
            )

        method_key = st.sidebar.selectbox(
            "Recommendation method",
            options=[method.key for method in METHODS],
            format_func=lambda key: METHOD_LOOKUP[key].label,
        )
        method = METHOD_LOOKUP[method_key]

        loaded, active_detail, active_summary = load_dashboard_data(
            DATA_CACHE_VERSION,
            file_bytes,
            uploaded_file.name,
            method_key,
            seasonality_enabled,
            planning_season,
            simulation_as_of_date.isoformat(),
            historical_replay_mode,
            acceleration.backend,
            prefer_gpu,
            forecast_csv_bytes if use_ai_forecast else None,
            service_levels_json,
            cheap_local_deviation_threshold,
            remove_highest_outlier_enabled,
            highest_outlier_threshold_pct,
        )
        masked_replay_labels = []
        if historical_replay_mode:
            masked_replay_labels = [
                label
                for label in loaded.monthly_columns
                if (month_end := month_label_end(label)) is not None and month_end > simulation_as_of_date
            ]
    except Exception as exc:
        st.error(f"Could not read the workbook: {exc}")
        return

    active_summary = ensure_dashboard_category(active_summary)
    active_detail = ensure_dashboard_category(active_detail)

    suppliers = sorted(value for value in active_summary["supplier"].dropna().unique() if value)
    statuses = sorted(value for value in active_summary["status"].dropna().unique() if value)
    prod_groups = sorted(value for value in active_summary["prod_group"].dropna().unique() if value)
    abc_codes = sorted(value for value in active_summary["abc"].dropna().unique() if value)
    seasons = sorted(value for value in active_summary["season"].dropna().unique() if value)

    st.sidebar.markdown("#### Filters")
    selected_suppliers = render_excel_like_filter(
        st.sidebar,
        "Supplier",
        suppliers,
        key="sidebar_supplier_filter",
        default_values=suppliers,
        help_text="Select all, clear all, or choose multiple suppliers like an Excel filter.",
        expanded=True,
    )
    selected_statuses = render_excel_like_filter(
        st.sidebar,
        "Status",
        statuses,
        key="sidebar_status_filter",
        default_values=statuses,
        help_text="Filter the dashboard to one or more item statuses.",
    )
    selected_prod_groups = render_excel_like_filter(
        st.sidebar,
        "Prod Group",
        prod_groups,
        key="sidebar_prod_group_filter",
        default_values=prod_groups,
        help_text="Filter the dashboard to one or more product groups.",
    )
    selected_abcs = render_excel_like_filter(
        st.sidebar,
        "ABC",
        abc_codes,
        key="sidebar_abc_filter",
        default_values=abc_codes,
        help_text="Filter the dashboard to one or more ABC classes.",
    )
    selected_seasons = render_excel_like_filter(
        st.sidebar,
        "Season",
        seasons,
        key="sidebar_season_filter",
        default_values=seasons,
        help_text="Filter the dashboard to one or more season tags.",
    )
    changed_only = st.sidebar.checkbox("Only changed recommendations", value=False)
    search_text = st.sidebar.text_input("Search item / description / supplier")

    summary, detail, raw = apply_filters(
        summary=active_summary,
        detail=active_detail,
        raw=loaded.data,
        supplier_filter=selected_suppliers,
        status_filter=selected_statuses,
        prod_group_filter=selected_prod_groups,
        abc_filter=selected_abcs,
        season_filter=selected_seasons,
        changed_only=changed_only,
        search_text=search_text,
    )

    highest_outlier_rule_summary = (
        f" Highest-month outlier filter is on at `{highest_outlier_threshold_pct:,.0f}%`, so one highest scoped month is reset to a standard-month baseline when it rises above that share of the other non-zero months."
        if remove_highest_outlier_enabled
        else ""
    )
    seasonal_ramp_summary = (
        " Seasonality now uses the next protected replenishment window for items with enough in-season history, so maxes ramp up and down through the season instead of using the whole season equally."
        if seasonality_enabled
        else ""
    )
    simulation_summary = (
        f" | Simulation as of: {simulation_as_of_date.isoformat()}"
        + (
            f" | Historical replay: On ({len(masked_replay_labels)} future month{'s' if len(masked_replay_labels) != 1 else ''} hidden)"
            if historical_replay_mode
            else " | Historical replay: Off"
        )
    )
    st.markdown(
        f"""
        <div class="callout">
            <strong>Active method:</strong> {method.label}<br/>
            {method.description}<br/>
            <strong>Forecast mode:</strong> {"AI Forecast + Rules" if use_ai_forecast else "Rules Only"}<br/>
            <strong>Seasonality:</strong> {"On" if seasonality_enabled else "Off"}
            {" | Planning season: " + planning_season if seasonality_enabled else ""}
            {simulation_summary}
            <br/><strong>Processing:</strong> {acceleration.label} - {acceleration.detail}
            <br/><strong>Rules:</strong> Service, Special, Inactive, Ok to Sell Below Cost, Substitute, and Exception are ignored. Stock is ignored when it has no max. Location `9999` is ignored. Frequency `Local` is treated as 4 weeks. Items within +/-33% year over year use 24 months; otherwise they use 12 months. Product-group trend signals are blended into the item mean. Items with MAC below `${cheap_local_deviation_threshold:,.2f}` keep deviation at the branch instead of pooling it to the DC.{highest_outlier_rule_summary}{seasonal_ramp_summary}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if historical_replay_mode and masked_replay_labels:
        st.caption(
            f"Historical replay is hiding future months after `{simulation_as_of_date.isoformat()}`: {', '.join(masked_replay_labels[:6])}"
            + (" ..." if len(masked_replay_labels) > 6 else "")
        )
    if use_ai_forecast and saved_forecast is not None:
        forecast_source = str(saved_forecast.metadata.get("source_name", "") or "")
        if forecast_source and forecast_source != uploaded_file.name:
            st.warning(
                f"Saved AutoGluon forecasts were trained from `{forecast_source}`, while the uploaded workbook is `{uploaded_file.name}`. "
                "Rows without a matching AI forecast will fall back to the standard rules-only mean."
            )
    views = split_dashboard_views(summary, detail, raw)

    pending_dashboard_view = st.session_state.pop("pending_dashboard_view", None)
    if pending_dashboard_view in VIEW_OPTIONS:
        st.session_state["dashboard_view"] = pending_dashboard_view

    if "dashboard_view" not in st.session_state or st.session_state["dashboard_view"] not in VIEW_OPTIONS:
        st.session_state["dashboard_view"] = "Supplier Overview"

    current_view = st.radio(
        "Dashboard view",
        options=VIEW_OPTIONS,
        horizontal=True,
        key="dashboard_view",
    )

    location_recommendation_detail_view = views["main_detail"].copy()
    location_recommendation_summary_view = views["main_summary"].copy()
    if current_view == "Location Recommendations":
        location_table_suppliers = sorted(
            value
            for value in location_recommendation_detail_view.get("supplier", pd.Series(dtype=str)).dropna().unique()
            if value
        )
        selected_location_table_suppliers = render_excel_like_filter(
            st,
            "Location table supplier filter",
            location_table_suppliers,
            key="location_recommendation_supplier_filter",
            default_values=location_table_suppliers,
            help_text="Select all, clear all, or choose multiple suppliers like an Excel filter.",
            expanded=True,
        )
        if location_table_suppliers:
            location_recommendation_detail_view = location_recommendation_detail_view[
                location_recommendation_detail_view["supplier"].isin(selected_location_table_suppliers)
            ].copy()
        if "group_key" in location_recommendation_detail_view.columns and "group_key" in location_recommendation_summary_view.columns:
            location_recommendation_summary_view = location_recommendation_summary_view[
                location_recommendation_summary_view["group_key"].isin(
                    location_recommendation_detail_view["group_key"].dropna().unique().tolist()
                )
            ].copy()
        elif location_table_suppliers:
            location_recommendation_summary_view = location_recommendation_summary_view[
                location_recommendation_summary_view["supplier"].isin(selected_location_table_suppliers)
            ].copy()

    selected_supplier = resolve_selected_supplier(views["supplier_summary"])
    preferred_summary = summary[summary["supplier"] == selected_supplier] if selected_supplier else views["main_summary"]
    selected_item = resolve_selected_item(summary, preferred_summary)

    if current_view == "Supplier Drill-Down" and selected_supplier:
        metric_summary = summary[summary["supplier"] == selected_supplier]
        metric_detail = detail[detail["supplier"] == selected_supplier]
    elif current_view == "Supplier Overview":
        metric_summary = views["main_summary"]
        metric_detail = views["main_detail"]
    elif current_view == "Location Recommendations":
        metric_summary = location_recommendation_summary_view
        metric_detail = location_recommendation_detail_view
    elif current_view == "Item Drill-Down" and selected_item is not None:
        metric_summary = summary[summary["group_key"] == selected_item["group_key"]]
        metric_detail = detail[detail["group_key"] == selected_item["group_key"]]
    elif current_view == "Raw Data":
        metric_summary = summary
        metric_detail = detail
    else:
        metric_summary = views["main_summary"]
        metric_detail = views["main_detail"]

    display_metric_strip(metric_summary, metric_detail)

    if current_view == "Supplier Overview":
        st.markdown('<p class="section-note">Rank suppliers by total recommendation change, then click one to review its item-level detail.</p>', unsafe_allow_html=True)
        render_supplier_summary_table(
            views["supplier_summary"],
            table_key="supplier_overview_table",
            empty_message="No suppliers match the current filters.",
        )
        if not views["supplier_summary"].empty:
            supplier_export = views["supplier_summary"][
                [
                    "supplier",
                    "items_count",
                    "changed_items",
                    "changed_locations",
                    "forecast_coverage_locations",
                    "total_current_min",
                    "total_recommended_min_amount",
                    "recommended_min_delta",
                    "total_current_max",
                    "total_recommended_new_max",
                    "recommendation_delta",
                    "total_deviation_pooled_to_dc",
                    "avg_yoy_change_pct",
                    "top_change_item",
                    "top_change_delta",
                ]
            ]
            st.download_button(
                "Download supplier overview CSV",
                data=supplier_export.to_csv(index=False).encode("utf-8"),
                file_name=f"deviation_dash_supplier_overview_{method.key}.csv",
                mime="text/csv",
            )

    elif current_view == "Supplier Drill-Down":
        if not selected_supplier:
            st.warning("No suppliers match the current filters.")
        else:
            supplier_options = views["supplier_summary"].reset_index(drop=True)
            selected_supplier_index = int(
                supplier_options.index[supplier_options["supplier"] == selected_supplier][0]
            )
            selected_supplier_label = st.selectbox(
                "Choose a supplier",
                options=supplier_options.index.tolist(),
                index=selected_supplier_index,
                format_func=lambda index: str(supplier_options.loc[index, "supplier"]),
            )
            supplier_row = supplier_options.loc[selected_supplier_label]
            selected_supplier = str(supplier_row["supplier"])
            st.session_state["selected_supplier"] = selected_supplier

            supplier_items = summary[summary["supplier"] == selected_supplier].copy()
            supplier_detail = detail[detail["supplier"] == selected_supplier].copy()

            header_col1, header_col2, header_col3, header_col4, header_col5 = st.columns([1.5, 1, 1, 1, 1])
            header_col1.markdown(f"### {selected_supplier}\n**Supplier recommendation rollup**")
            header_col2.metric("Items", f"{int(supplier_row['items_count']):,}")
            header_col3.metric("Changed Items", f"{int(supplier_row['changed_items']):,}")
            header_col4.metric("Changed Locations", f"{int(supplier_row['changed_locations']):,}")
            header_col5.metric(
                "Recommended Max Delta",
                f"{float(supplier_row['recommendation_delta']):,.0f}",
            )
            st.markdown(
                f'<p class="section-note">Current max `{float(supplier_row["total_current_max"]):,.0f}` | Recommended max `{float(supplier_row["total_recommended_new_max"]):,.0f}` | Current min `{float(supplier_row["total_current_min"]):,.0f}` | Recommended min `{float(supplier_row["total_recommended_min_amount"]):,.0f}` | Branch pool input to DC `{float(supplier_row["total_deviation_pooled_to_dc"]):,.0f}` | Low-cost local deviation locations `{int(supplier_row["low_cost_local_deviation_locations"])}` | DC zero-max pool alerts `{int(supplier_row["dc_zero_max_pool_alert_items"])}` | Top change item `{supplier_row["top_change_item"] or "-"}`</p>',
                unsafe_allow_html=True,
            )

            ranked_supplier_items = supplier_items.assign(
                abs_recommendation_delta=supplier_items["recommendation_delta"].abs()
            ).sort_values(
                ["abs_recommendation_delta", "item"],
                ascending=[False, True],
                kind="stable",
            ).drop(columns=["abs_recommendation_delta"])

            render_summary_table(
                ranked_supplier_items,
                table_key="supplier_item_table",
                empty_message="No items match the current supplier filters.",
            )
            if not supplier_items.empty:
                supplier_item_export = ranked_supplier_items[
                    [
                        "supplier",
                        "prod_group",
                        "item",
                        "description",
                        "status",
                        "abc",
                        "service_level_pct",
                        "season",
                        "frequency",
                        "lead_time",
                        "branch_zero_max_recommendation_locations",
                        "regional_zero_max_branch_pool_locations",
                        "branch_zero_max_recommendation_alert",
                        "low_cost_local_deviation_threshold",
                        "low_cost_local_deviation_locations",
                        "dc_pooling_zero_max_alert",
                        "has_override",
                        "override_locations",
                        "primary_location",
                        "total_current_min",
                        "total_recommended_min_amount",
                        "recommended_min_delta",
                        "total_current_max",
                        "total_recommended_new_max",
                        "recommendation_delta",
                        "total_deviation_pooled_to_dc",
                        "forecast_mode",
                        "forecast_coverage_locations",
                        "changed_locations",
                        "reference_window_months",
                        "yoy_change_pct",
                        "reference_window_rule",
                        "product_group_trend_label",
                        "product_group_trend_factor",
                        "product_group_trend_source",
                        "planning_season",
                        "seasonal_months_used",
                        "max_company_month",
                        "max_total_dev",
                        "peak_month",
                        "seasonality_note",
                    ]
                ]
                st.download_button(
                    "Download supplier item detail CSV",
                    data=supplier_item_export.to_csv(index=False).encode("utf-8"),
                    file_name=f"deviation_dash_supplier_items_{selected_supplier}_{method.key}.csv",
                    mime="text/csv",
                )

    elif current_view == "Item Overview":
        st.markdown('<p class="section-note">Main replenishment recommendations after the ignore-status rules are applied.</p>', unsafe_allow_html=True)
        dc_alert_items = int(views["main_summary"].get("dc_pooling_zero_max_alert", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
        branch_zero_alert_items = int(
            views["main_summary"].get("branch_zero_max_recommendation_alert", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()
        )
        if branch_zero_alert_items:
            st.warning(
                f"{branch_zero_alert_items} items have at least one branch currently at max 0 but still receiving a positive branch recommendation. Look for `Branch Stock Alert` in the table."
            )
        if dc_alert_items:
            st.warning(
                f"{dc_alert_items} items have location 1 currently at max 0 but still receive a positive DC recommendation because branch pooling is landing there. Look for `DC Pool Alert` in the table."
            )
        render_summary_table(
            views["main_summary"],
            table_key="item_overview_table",
            empty_message="No recommendation items match the current filters.",
        )
        if not views["main_summary"].empty:
            overview_export = views["main_summary"][
                [
                    "supplier",
                    "prod_group",
                    "item",
                    "description",
                    "status",
                    "abc",
                    "service_level_pct",
                    "season",
                    "frequency",
                    "lead_time",
                    "branch_zero_max_recommendation_locations",
                    "regional_zero_max_branch_pool_locations",
                    "branch_zero_max_recommendation_alert",
                    "low_cost_local_deviation_threshold",
                    "low_cost_local_deviation_locations",
                    "dc_pooling_zero_max_alert",
                    "has_override",
                    "override_locations",
                    "primary_location",
                    "total_current_min",
                    "total_recommended_min_amount",
                    "recommended_min_delta",
                    "total_current_max",
                    "total_recommended_new_max",
                    "recommendation_delta",
                    "total_deviation_pooled_to_dc",
                    "forecast_mode",
                    "forecast_coverage_locations",
                    "changed_locations",
                    "reference_window_months",
                    "yoy_change_pct",
                    "reference_window_rule",
                    "product_group_trend_label",
                    "product_group_trend_factor",
                    "product_group_trend_source",
                    "planning_season",
                    "seasonal_months_used",
                    "max_company_month",
                    "max_total_dev",
                    "peak_month",
                    "seasonality_note",
                ]
            ]
            st.download_button(
                "Download item overview CSV",
                data=overview_export.to_csv(index=False).encode("utf-8"),
                file_name=f"deviation_dash_item_overview_{method.key}.csv",
                mime="text/csv",
            )

    elif current_view == "Location Recommendations":
        st.markdown('<p class="section-note">Location-level recommendation outputs for standard replenishment items.</p>', unsafe_allow_html=True)
        location_detail_view = location_recommendation_detail_view.copy()
        branch_zero_alert_rows = int(
            location_detail_view.get("branch_zero_max_recommendation_alert", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()
        )
        if branch_zero_alert_rows:
            st.warning(
                f"{branch_zero_alert_rows} branch rows currently have max 0 but receive a positive branch recommendation. Look for `Review branch new stock` in the table."
            )
        dc_alert_rows = int(location_detail_view.get("dc_pooling_zero_max_alert", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
        if dc_alert_rows:
            st.warning(
                f"{dc_alert_rows} location 1 rows currently have max 0 but receive a positive DC recommendation because pooled branch stock is landing there. Look for `Review DC zero-max` in the table."
            )
        detail_display = select_unique_columns(
            location_detail_view,
            [
                "supplier",
                "prod_group",
                "item",
                "description",
                "location",
                "status",
                "abc",
                "service_level_pct",
                "frequency",
                "frequency_days",
                "lead_time",
                "lead_time_days",
                "mac",
                "branch_zero_max_recommendation_alert",
                "regional_zero_max_branch_pool_applied",
                "low_cost_local_deviation_threshold",
                "low_cost_local_deviation_applied",
                "low_cost_local_deviation_kept_amount",
                "dc_pooling_zero_max_alert",
                "raw_protection_days",
                "protection_days",
                "demand_only_min_amount",
                "service_level_min_amount",
                "dc_transfer_reserve_amount",
                "demand_only_order_up_to",
                "service_level_order_up_to",
                "minimum_28_day_rule_applied",
                "dc_location_reserve_rule_applied",
                "deviation_pooled_to_dc",
                "deviation_absorbed_by_dc",
                "dc_sparse_active_mean_fallback_applied",
                "dc_sparse_active_mean_fallback_reason",
                "dc_sparse_active_mean_fallback_active_mean",
                "dc_sparse_active_mean_fallback_inclusive_mean",
                "single_stocked_branch_hold_applied",
                "single_stocked_branch_hold_location",
                "non_stockable_location_blocked",
                "single_period_pool_guard_applied",
                "single_period_pool_guard_reason",
                "two_point_spike_normalized",
                "two_point_spike_normalized_month_mean",
                "two_point_spike_normalized_value_mean",
                "two_point_spike_normalized_baseline_value_mean",
                "two_point_spike_normalized_ratio_mean",
                "forecast_mode",
                "forecast_used",
                "autogluon_forecast_mean",
                "mean_source",
                "reference_window_months",
                "yoy_change_pct",
                "reference_window_rule",
                "product_group_trend_label",
                "product_group_trend_factor",
                "product_group_trend_source",
                "product_group_recent_avg",
                "product_group_prior_avg",
                "product_group_trend_scope",
                "seasonal_ramp_applied",
                "seasonal_ramp_factor",
                "seasonal_ramp_window",
                "raw_intermittent_direct_transfer",
                "intermittent_direct_transfer_allowed",
                "intermittent_direct_transfer_suppressed",
                "highest_outlier_removed",
                "highest_outlier_removed_month_mean",
                "highest_outlier_removed_value_mean",
                "highest_outlier_baseline_value_mean",
                "highest_outlier_trigger_pct_mean",
                "override_flag",
                "min_value",
                "recommended_min_amount",
                "recommended_min_delta",
                "net_qoh",
                "current_max",
                "policy_order_up_to",
                "recommended_new_max",
                "recommendation_delta",
                "filtered_mean",
                "daily_demand",
                "filtered_std_dev",
                "rounded_mean",
                "delta",
                "total_dev",
                "review_cycle_days",
                "active_months_mean",
                "active_months_std",
                "per",
                "override_date",
                "planning_season",
                "mean_month_scope",
                "std_month_scope",
                "is_balancing_location",
                "seasonality_note",
                "recommendation_explanation",
            ],
        )
        if detail_display.empty:
            st.info("No location recommendations match the current filters.")
        else:
            if "low_cost_local_deviation_applied" in detail_display.columns:
                detail_display["low_cost_local_deviation_applied"] = detail_display["low_cost_local_deviation_applied"].map(
                    format_boolean_cell
                )
            if "regional_zero_max_branch_pool_applied" in detail_display.columns:
                detail_display["regional_zero_max_branch_pool_applied"] = detail_display["regional_zero_max_branch_pool_applied"].map(
                    format_boolean_cell
                )
            if "seasonal_ramp_applied" in detail_display.columns:
                detail_display["seasonal_ramp_applied"] = detail_display["seasonal_ramp_applied"].map(
                    format_boolean_cell
                )
            if "branch_zero_max_recommendation_alert" in detail_display.columns:
                detail_display["branch_zero_max_recommendation_alert"] = detail_display["branch_zero_max_recommendation_alert"].map(
                    lambda value: "Review branch new stock" if bool(value) else ""
                )
            if "dc_pooling_zero_max_alert" in detail_display.columns:
                detail_display["dc_pooling_zero_max_alert"] = detail_display["dc_pooling_zero_max_alert"].map(
                    lambda value: "Review DC zero-max" if bool(value) else ""
                )
            st.dataframe(detail_display, use_container_width=True, hide_index=True)
            st.download_button(
                "Download location recommendations CSV",
                data=detail_display.to_csv(index=False).encode("utf-8"),
                file_name=f"deviation_dash_location_recommendations_{method.key}.csv",
                mime="text/csv",
            )

    elif current_view == "Item Drill-Down":
        if selected_item is None:
            st.warning("No items match the current filters.")
        else:
            item_options = summary.reset_index(drop=True)
            selected_index = int(item_options.index[item_options["group_key"] == selected_item["group_key"]][0])
            selected_label = st.selectbox(
                "Choose an item",
                options=item_options.index.tolist(),
                index=selected_index,
                format_func=lambda index: format_item_option(item_options.loc[index]),
            )
            selected_item = item_options.loc[selected_label]
            st.session_state["selected_group_key"] = selected_item["group_key"]
            item_rows = detail[
                (detail["supplier"] == selected_item["supplier"]) & (detail["item"] == selected_item["item"])
            ].copy()

            header_col1, header_col2, header_col3, header_col4 = st.columns([1.4, 1.1, 1.1, 1.1])
            header_col5, header_col6 = st.columns([1.0, 1.0])
            header_col1.markdown(
                f"### {selected_item['item']}\n**{selected_item['description']}**\n\nSupplier: `{selected_item['supplier']}`\n\nDashboard: `{selected_item['dashboard_category']}`"
            )
            header_col2.metric("Current Min", f"{selected_item['total_current_min']:,.0f}")
            header_col3.metric(
                "Recommended Min",
                f"{selected_item['total_recommended_min_amount']:,.0f}",
                delta=f"{selected_item['recommended_min_delta']:,.0f}",
            )
            header_col4.metric("Current Max", f"{selected_item['total_current_max']:,.0f}")
            header_col5.metric(
                "Recommended Max",
                f"{selected_item['total_recommended_new_max']:,.0f}",
                delta=f"{selected_item['recommendation_delta']:,.0f}",
            )
            header_col6.metric("Service Level", f"{selected_item['service_level_pct']:,.0f}%")
            st.markdown(
                f'<p class="section-note">Forecast mode `{selected_item["forecast_mode"]}` | AI-covered locations `{int(selected_item["forecast_coverage_locations"])}` | ABC `{selected_item["abc"]}` | Frequency `{selected_item["frequency"]}` | Lead time `{selected_item["lead_time"]}` days | Planning season `{selected_item["planning_season"]}` | Overrides `{int(selected_item["override_locations"])}` | Branch zero-max recommendations `{int(selected_item["branch_zero_max_recommendation_locations"])}` | Regional zero-max branches pooled `{int(selected_item["regional_zero_max_branch_pool_locations"])}` | Branch pool input to DC `{selected_item["total_deviation_pooled_to_dc"]:,.0f}` | Low-cost deviation kept local `{int(selected_item["low_cost_local_deviation_locations"])}` locations below `${selected_item["low_cost_local_deviation_threshold"]:,.2f}` MAC | DC sparse active fallback hits `{int(selected_item.get("dc_sparse_active_mean_fallback_locations", 0))}` locations | Single-stocked branch hold hits `{int(selected_item.get("single_stocked_branch_hold_locations", 0))}` locations | Non-stockable blocks `{int(selected_item.get("non_stockable_location_blocked_locations", 0))}` locations | Single-period pooling guard hits `{int(selected_item.get("single_period_pool_guard_locations", 0))}` locations | Two-point spike normalization hits `{int(selected_item.get("two_point_spike_normalized_locations", 0))}` locations | Highest-month normalization hits `{int(selected_item.get("highest_outlier_filtered_locations", 0))}` locations | Current-window seasonal ramp hits `{int(selected_item.get("seasonal_ramp_locations", 0))}` locations | YOY `{selected_item["yoy_change_pct"]:.1f}%` using `{int(selected_item["reference_window_months"])}` months | Prod-group trend `{selected_item["product_group_trend_label"]}` at `{selected_item["product_group_trend_factor"]:.2f}x` from `{selected_item["product_group_trend_source"]}`</p>',
                unsafe_allow_html=True,
            )
            if bool(selected_item.get("branch_zero_max_recommendation_alert")):
                st.warning(
                    "At least one branch currently has max 0 but is receiving a positive branch recommendation for this item. Review the orange-highlighted rows in Location calculations."
                )
            if bool(selected_item.get("dc_pooling_zero_max_alert")):
                st.warning(
                    "The designated DC currently has a max of 0, but pooled branch protection is creating a positive DC recommendation for this item. Review whether the DC should be stocked."
                )
            st.metric("Peak Company Month", f"{selected_item['max_company_month']:,.0f}")

            st.markdown("#### Method comparison")
            compare_methods = st.toggle(
                "Load comparison for all methods",
                value=False,
                help="This loads the other recommendation methods on demand so normal recalculations stay faster.",
            )
            if compare_methods:
                comparison_rows = [
                    {
                        "method": method.label,
                        "service level %": selected_item["service_level_pct"],
                        "recommended min total": selected_item["total_recommended_min_amount"],
                        "recommended max total": selected_item["total_recommended_new_max"],
                        "override locations": selected_item["override_locations"],
                        "delta vs current": selected_item["recommendation_delta"],
                        "peak company month": selected_item["max_company_month"],
                        "dashboard": selected_item["dashboard_category"],
                    }
                ]
                for candidate_method in METHODS:
                    if candidate_method.key == method.key:
                        continue
                    _, _, candidate_summary = load_dashboard_data(
                        DATA_CACHE_VERSION,
                        file_bytes,
                        uploaded_file.name,
                        candidate_method.key,
                        seasonality_enabled,
                        planning_season,
                        simulation_as_of_date.isoformat(),
                        historical_replay_mode,
                        acceleration.backend,
                        prefer_gpu,
                        forecast_csv_bytes if use_ai_forecast else None,
                        service_levels_json,
                        cheap_local_deviation_threshold,
                        remove_highest_outlier_enabled,
                        highest_outlier_threshold_pct,
                    )
                    candidate_summary = ensure_dashboard_category(candidate_summary)
                    match = candidate_summary[
                        (candidate_summary["supplier"] == selected_item["supplier"])
                        & (candidate_summary["item"] == selected_item["item"])
                    ]
                    if match.empty:
                        continue
                    row = match.iloc[0]
                    comparison_rows.append(
                        {
                            "method": candidate_method.label,
                            "service level %": row["service_level_pct"],
                            "recommended min total": row["total_recommended_min_amount"],
                            "recommended max total": row["total_recommended_new_max"],
                            "override locations": row["override_locations"],
                            "delta vs current": row["recommendation_delta"],
                            "peak company month": row["max_company_month"],
                            "dashboard": row["dashboard_category"],
                        }
                    )
                st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("Comparison methods are loaded only when you turn this on, which keeps service-level recalculations much faster.")

            st.markdown("#### Location calculations")
            render_location_calculation_table(item_rows)

            render_override_popovers(item_rows)

            st.markdown("#### 24-month usage trend by location")
            monthly_order = ordered_month_labels(loaded.monthly_columns)
            render_usage_trend_chart(item_rows, loaded.monthly_columns, selected_item["group_key"])

            st.markdown("#### Monthly usage matrix")
            monthly_matrix = build_monthly_usage_matrix(item_rows, loaded.monthly_columns)
            st.dataframe(
                monthly_matrix,
                use_container_width=True,
                hide_index=True,
            )

            st.markdown(
                """
                #### Formula notes
                - Service, Special, Inactive, Ok to Sell Below Cost, Substitute, and Exception are ignored before recommendations are grouped.
                - Stock is also ignored when it has no max, and location `9999` is ignored entirely.
                - If `Override = Y`, the recommended max is locked to the current max and the drill-down shows the `Per` and `Oride Date` details in an override popup.
                - Frequency is treated as the supplier review cycle, lead time is treated as days in transit before replenishment arrives, and `Local` frequency is treated as 4 weeks.
                - If item demand is between -33% and +33% year over year, the model uses both years. Otherwise it falls back to the last 12 months as the model reference.
                - Recommended Min is normally a reorder-point style floor: lead-time demand plus ABC-based safety stock.
                - Location `1` is treated as the DC. Its recommended min is set to only location `1` demand across the protected cycle, so deviation and balancing stock stays above min and remains available for branch transfers.
                - Branch locations do not keep their local deviation buffers in the recommendation. That variability is pooled into the DC or balancing location instead.
                - In `Active Demand with Active Variability`, branch locations with very sparse spike-driven demand are protected from treating those spikes as steady branch demand. The branch base falls back to inclusive scoped mean, and the excess spike coverage is pooled to the DC.
                - Product-group trend uses recent product-group demand versus the prior product-group window to apply a bounded trend multiplier to the item mean before rounding.
                - Recommended Max is floored to an order-up-to policy based on lead time + supplier frequency, while still respecting the selected demand method and balancing logic.
                - If frequency + lead time is less than 28 days, the policy uses 28 days of total protection instead.
                - Non-balancing locations use the Excel continuity rule: if a location already has a max, it stays alive with at least 1 even when rounded demand falls to 0.
                - The balancing location absorbs the remaining demand gap from the rest of the item group and adds the company deviation buffer.
                - This build assumes the first location in the standard location order is the balancing location.
                - When seasonality focus is on, the method window is narrowed to Summer months (Apr-Sep) or Winter months (Oct-Mar) before the averages and deviation are calculated.
                """
            )

    elif current_view == "Raw Data":
        st.markdown('<p class="section-note">Filtered raw rows that are still eligible for dashboard logic after the status rules are applied.</p>', unsafe_allow_html=True)
        raw_display_columns = [
            "supplier",
            "prod_group",
            "price_group",
            "item",
            "description",
            "location",
            "status",
            "frequency",
            "override",
            "per",
            "override_date",
            "abc",
            "season",
            "lead_time",
            "net_qoh",
            "min_value",
            "current_max",
            "usage_24m_total",
            "usage_12m_total",
            "usage_13_24m_total",
            *loaded.monthly_columns,
        ]
        if raw.empty:
            st.info("No raw rows match the current filters.")
        else:
            st.dataframe(raw[raw_display_columns], use_container_width=True, hide_index=True)
            st.caption(f"Source workbook: {loaded.source_name}")


if __name__ == "__main__":
    main()
