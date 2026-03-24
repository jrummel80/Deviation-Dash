from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, timedelta
import calendar
from functools import lru_cache
import json
import math
from pathlib import Path
import re
from statistics import NormalDist, median, stdev
import tempfile

import numpy as np
import pandas as pd

try:
    from .acceleration import (
        AccelerationStatus,
        aggregate_monthly_sum,
        detect_acceleration,
        run_wsl_rapids_script,
        windows_to_wsl_path,
    )
except ImportError:
    from acceleration import (
        AccelerationStatus,
        aggregate_monthly_sum,
        detect_acceleration,
        run_wsl_rapids_script,
        windows_to_wsl_path,
    )

LOCATION_ORDER = ["1", "30", "40", "115", "116", "117", "118", "119"]
IGNORED_LOCATIONS = {"9999"}
DAYS_PER_MONTH = 30.4375
SUMMER_MONTHS = {4, 5, 6, 7, 8, 9}
WINTER_MONTHS = {10, 11, 12, 1, 2, 3}
IGNORED_STATUSES = {
    "service",
    "ok to sell below cost",
    "special",
    "inactive",
    "substitute",
    "exception",
}
IGNORE_IF_ZERO_MAX_STATUSES = {"stock", "stock with no max"}
DEFAULT_SERVICE_LEVELS = {
    "A": 0.99,
    "B": 0.92,
    "C": 0.88,
    "D": 0.84,
    "E": 0.80,
    "X": 0.80,
}
SERVICE_LEVEL_ORDER = ["A", "B", "C", "D", "E", "X"]
FREQUENCY_PATTERN = re.compile(r"(?P<count>\d+(?:\.\d+)?)?\s*(?P<unit>day|days|week|weeks|month|months|quarter|quarters)", re.IGNORECASE)
REGIONAL_STATUS_PATTERN = re.compile(r"\bregional\b", re.IGNORECASE)
SEASON_MONTHS = {
    "Summer": SUMMER_MONTHS,
    "Winter": WINTER_MONTHS,
}
PRODUCT_GROUP_TREND_WEIGHT = 0.35
PRODUCT_GROUP_TREND_MIN_FACTOR = 0.85
PRODUCT_GROUP_TREND_MAX_FACTOR = 1.15
PRODUCT_GROUP_TREND_THRESHOLD = 0.08
YOY_STABLE_THRESHOLD = 33.0
INTERMITTENT_BRANCH_METHOD_KEY = "excl_0_devmean_24_round"
INTERMITTENT_BRANCH_MIN_NON_ZERO_MONTHS = 2
INTERMITTENT_BRANCH_ADI_THRESHOLD = 4.0
INTERMITTENT_BRANCH_TOP_TWO_SHARE_THRESHOLD = 0.70
DEFAULT_HIGHEST_OUTLIER_THRESHOLD_PCT = 200.0
HIGHEST_OUTLIER_MIN_NON_ZERO_MONTHS = 3
TWO_POINT_INTERMITTENT_SPIKE_RATIO_THRESHOLD = 5.0
SEASONAL_RAMP_MIN_NON_ZERO_POINTS = 4
SEASONAL_RAMP_MIN_DISTINCT_MONTHS = 3
SPARSE_SEASONAL_COMPANY_CEILING_BUFFER_FACTOR = 1.15
SPARSE_SEASONAL_COMPANY_CEILING_NON_ZERO_MONTHS_THRESHOLD = 3
SPARSE_SEASONAL_COMPANY_CEILING_PROTECTION_DAYS_THRESHOLD = 90.0
THIN_HISTORY_SEASONAL_DC_MIN_PROTECTION_DAYS = 56.0
THIN_HISTORY_SEASONAL_DC_MAX_NON_ZERO_POINTS = 2
THIN_HISTORY_SEASONAL_DC_MAX_POSITIVE_SEASONS = 1
DC_SPARSE_ACTIVE_MEAN_MAX_NON_ZERO_POINTS = 2
WSL_PRECOMPUTE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wsl_cudf_precompute_recommendations.py"
NON_HUB_MANAGED_SUPPLIER_PATTERNS = (
    "M&M MANUFACTURING",
    "ATCO RUBBER",
    "MCDANIEL METALS",
    "CONKLIN METAL INDUSTRIES",
    "RYERSON & SON, JOSEPH T.",
)
SUPPLIER_DC_LOCATION_OVERRIDES = {
    "HAILIANG AMERICA": "118",
    "REFLECTIX": "119",
}
NEW_BRANCH_STOCK_MIN_USAGE_PERIODS = 3
NEW_BRANCH_STOCK_MIN_EXISTING_STOCK_LOCATIONS = 3
SPARSE_REGIONAL_POOL_MAX_BRANCH_NON_ZERO_PERIODS = 2
SINGLE_PERIOD_POOL_GUARD_MAX_BRANCH_NON_ZERO_PERIODS = 1
PROJECT_SPIKE_MAX_BRANCH_USAGE_PERIODS = 2
PROJECT_SPIKE_BRANCH_SHARE_THRESHOLD = 0.80
PROJECT_SPIKE_COMPANY_SHARE_THRESHOLD = 0.80
PROJECT_SPIKE_STOCKED_COMPANY_SHARE_THRESHOLD = 0.60
PROJECT_SPIKE_NEXT_MONTH_MULTIPLE = 10.0
PROJECT_SPIKE_CURRENT_MAX_MULTIPLE = 5.0
RETURN_NETTING_MAX_LOOKBACK_MONTHS = 12


@dataclass(frozen=True)
class MethodConfig:
    key: str
    label: str
    description: str
    mean_months: int
    mean_include_zeros: bool
    std_months: int
    std_include_zeros: bool
    rounding_mode: str


@dataclass(frozen=True)
class SeasonalityConfig:
    enabled: bool
    planning_season: str
    as_of_date: date


METHODS = [
    MethodConfig(
        key="excl_0_devmean_24_round",
        label="Active Demand with Active Variability",
        description="Uses non-zero demand months across 24 months for both the average and variability, then rounds with standard rounding.",
        mean_months=24,
        mean_include_zeros=False,
        std_months=24,
        std_include_zeros=False,
        rounding_mode="round",
    ),
    MethodConfig(
        key="incl_0_mean_12_roundup",
        label="Recent Mean with Active Variability",
        description="Uses the recent 12-month window for mean with zeros included, pairs it with non-zero variability across the longer window, then rounds up.",
        mean_months=12,
        mean_include_zeros=True,
        std_months=24,
        std_include_zeros=False,
        rounding_mode="roundup",
    ),
    MethodConfig(
        key="incl_0_devmean_12_roundup",
        label="Recent Mean with Full Variability",
        description="Uses the recent 12-month window for both mean and variability with zeros included, then rounds up.",
        mean_months=12,
        mean_include_zeros=True,
        std_months=12,
        std_include_zeros=True,
        rounding_mode="roundup",
    ),
]

METHOD_LOOKUP = {method.key: method for method in METHODS}


def default_planning_season(as_of_date: date | None = None) -> str:
    reference_date = as_of_date or date.today()
    if reference_date.month in {3, 4, 5, 6, 7, 8}:
        return "Summer"
    if reference_date.month == 9:
        return "Winter"
    return "Winter"


def calculate_method(
    data: pd.DataFrame,
    monthly_columns: list[str],
    method: MethodConfig,
    seasonality: SeasonalityConfig | None = None,
    acceleration: AccelerationStatus | None = None,
    forecast_lookup: dict[tuple[str, str, str], float] | None = None,
    service_levels: dict[str, float] | None = None,
    cheap_local_deviation_threshold: float = 1.0,
    remove_highest_outlier_enabled: bool = False,
    highest_outlier_threshold_pct: float = DEFAULT_HIGHEST_OUTLIER_THRESHOLD_PCT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    acceleration = acceleration or detect_acceleration(prefer_gpu=False)
    resolved_service_levels = normalize_service_levels(service_levels)
    detail_records: list[dict[str, object]] = []
    item_records: list[dict[str, object]] = []
    order_lookup = {location: index for index, location in enumerate(LOCATION_ORDER)}
    filtered_data: pd.DataFrame
    prepared_data = None
    calculation_data = _apply_negative_return_netting(data, monthly_columns)

    if (
        acceleration.backend == "gpu-wsl-cudf"
        and method.key != INTERMITTENT_BRANCH_METHOD_KEY
        and not remove_highest_outlier_enabled
        and not (seasonality and seasonality.enabled)
        and _supports_precomputed_policies(calculation_data)
    ):
        try:
            prepared_data = _precompute_method_frame_wsl(
                calculation_data,
                monthly_columns,
                method,
                seasonality,
                forecast_lookup,
                resolved_service_levels,
                remove_highest_outlier_enabled,
                highest_outlier_threshold_pct,
            )
        except Exception:
            prepared_data = None

    if prepared_data is not None:
        filtered_data = prepared_data
        supplier_prod_group_profiles: dict[tuple[str, str], dict[str, object]] = {}
        global_prod_group_profiles: dict[str, dict[str, object]] = {}
    else:
        filtered_data = _apply_status_rules(calculation_data)
        supplier_prod_group_profiles, global_prod_group_profiles = _build_product_group_profiles(
            filtered_data,
            monthly_columns,
            acceleration,
        )

    grouped = filtered_data.groupby(["supplier", "item"], sort=False, dropna=False)

    for (_, _), group in grouped:
        ordered = group.copy()
        supplier_policy = _supplier_inventory_policy(ordered["supplier"].iloc[0] if not ordered.empty else "")
        location_series = ordered["location"].map(lambda value: str(value or "").strip())
        location_sort = location_series.map(order_lookup).fillna(len(order_lookup))
        designated_dc_location = str(supplier_policy["dc_location"] or "").strip()
        if supplier_policy["hub_managed"] and designated_dc_location:
            location_sort = location_sort.where(location_series != designated_dc_location, -1)
        ordered["location_sort"] = location_sort
        ordered = ordered.sort_values(["location_sort", "location"], kind="stable")

        if prepared_data is not None:
            records = _finalize_group_records(
                ordered.to_dict(orient="records"),
                cheap_local_deviation_threshold,
            )
        else:
            records = _build_group_records(
                ordered,
                monthly_columns,
                method,
                seasonality,
                supplier_prod_group_profiles,
                global_prod_group_profiles,
                forecast_lookup,
                resolved_service_levels,
                cheap_local_deviation_threshold,
                remove_highest_outlier_enabled,
                highest_outlier_threshold_pct,
            )
        if not records:
            continue

        _apply_sparse_seasonal_company_ceiling(
            records,
            monthly_columns,
            seasonality,
        )

        base = records[0]
        summary_month_labels = _summary_month_labels(base)
        group_monthly = ordered[summary_month_labels].sum(numeric_only=True) if summary_month_labels else ordered[monthly_columns].sum(numeric_only=True)
        max_company_month = float(group_monthly.max()) if not group_monthly.empty else 0.0
        peak_month = group_monthly.idxmax() if not group_monthly.empty else ""

        total_current_max = sum(float(record["current_max"]) for record in records)
        total_new_max = sum(float(record["recommended_new_max"]) for record in records)
        total_current_min = sum(float(record["min_value"]) for record in records)
        total_recommended_min = sum(float(record["recommended_min_amount"]) for record in records)
        override_count = sum(1 for record in records if bool(record["override_flag"]))
        total_deviation_pooled_to_dc = sum(float(record["deviation_pooled_to_dc"]) for record in records)
        total_deviation_absorbed_by_dc = sum(float(record["deviation_absorbed_by_dc"]) for record in records)
        branch_zero_max_recommendation_locations = sum(
            1 for record in records if bool(record.get("branch_zero_max_recommendation_alert"))
        )
        regional_zero_max_branch_pool_locations = sum(
            1 for record in records if bool(record.get("regional_zero_max_branch_pool_applied"))
        )

        item_records.append(
            {
                "supplier": base["supplier"],
                "item": base["item"],
                "group_key": base["group_key"],
                "prod_group": base["prod_group"],
                "price_group": base["price_group"],
                "description": base["description"],
                "status": base["status"],
                "abc": base["abc"],
                "season": base["season"],
                "frequency": base["frequency"],
                "lead_time": base["lead_time"],
                "frequency_days": base["frequency_days"],
                "service_level_pct": base["service_level_pct"],
                "locations_count": len(records),
                "primary_location": base["location"],
                "total_net_qoh": sum(float(record["net_qoh"]) for record in records),
                "total_current_min": total_current_min,
                "total_recommended_min_amount": total_recommended_min,
                "total_current_max": total_current_max,
                "total_recommended_new_max": total_new_max,
                "recommended_min_delta": total_recommended_min - total_current_min,
                "recommendation_delta": total_new_max - total_current_max,
                "has_override": override_count > 0,
                "override_locations": override_count,
                "total_deviation_pooled_to_dc": total_deviation_pooled_to_dc,
                "total_deviation_absorbed_by_dc": total_deviation_absorbed_by_dc,
                "branch_zero_max_recommendation_alert": branch_zero_max_recommendation_locations > 0,
                "branch_zero_max_recommendation_locations": branch_zero_max_recommendation_locations,
                "regional_zero_max_branch_pool_locations": regional_zero_max_branch_pool_locations,
                "regional_sparse_pool_suppressed_locations": sum(
                    1 for record in records if bool(record.get("regional_sparse_pool_suppressed"))
                ),
                "project_spike_suppressed_locations": sum(
                    1 for record in records if bool(record.get("project_spike_suppressed"))
                ),
                "single_stocked_branch_hold_locations": sum(
                    1 for record in records if bool(record.get("single_stocked_branch_hold_applied"))
                ),
                "dc_sparse_active_mean_fallback_locations": sum(
                    1 for record in records if bool(record.get("dc_sparse_active_mean_fallback_applied"))
                ),
                "non_stockable_location_blocked_locations": sum(
                    1 for record in records if bool(record.get("non_stockable_location_blocked"))
                ),
                "single_period_pool_guard_locations": sum(
                    1 for record in records if bool(record.get("single_period_pool_guard_applied"))
                ),
                "two_point_spike_normalized_locations": sum(
                    1 for record in records if bool(record.get("two_point_spike_normalized"))
                ),
                "low_cost_local_deviation_threshold": float(cheap_local_deviation_threshold),
                "low_cost_local_deviation_locations": sum(
                    1 for record in records if bool(record.get("low_cost_local_deviation_applied"))
                ),
                "low_cost_local_deviation_total": sum(
                    float(record.get("low_cost_local_deviation_kept_amount", 0.0)) for record in records
                ),
                "highest_outlier_filtered_locations": sum(
                    1 for record in records if bool(record.get("highest_outlier_removed"))
                ),
                "seasonal_ramp_locations": sum(
                    1 for record in records if bool(record.get("seasonal_ramp_applied"))
                ),
                "sparse_seasonal_company_ceiling_applied": bool(
                    base.get("sparse_seasonal_company_ceiling_applied")
                ),
                "sparse_seasonal_company_ceiling": float(
                    base.get("sparse_seasonal_company_ceiling", 0.0)
                ),
                "sparse_seasonal_company_reference_total": float(
                    base.get("sparse_seasonal_company_reference_total", 0.0)
                ),
                "sparse_seasonal_company_reference_season": str(
                    base.get("sparse_seasonal_company_reference_season", "")
                ),
                "sparse_seasonal_company_non_zero_months": int(
                    base.get("sparse_seasonal_company_non_zero_months", 0)
                ),
                "sparse_seasonal_company_positive_seasons": int(
                    base.get("sparse_seasonal_company_positive_seasons", 0)
                ),
                "sparse_seasonal_company_trimmed_total": sum(
                    float(record.get("sparse_seasonal_company_trimmed_amount", 0.0)) for record in records
                ),
                "sparse_seasonal_company_trimmed_locations": sum(
                    1 for record in records if float(record.get("sparse_seasonal_company_trimmed_amount", 0.0)) > 0
                ),
                "dc_pooling_zero_max_alert": any(
                    bool(record.get("dc_pooling_zero_max_alert")) for record in records
                ),
                "max_company_month": max_company_month,
                "max_total_dev": max(float(record["total_dev"]) for record in records),
                "peak_month": peak_month,
                "changed_locations": sum(
                    1 for record in records if float(record["recommended_new_max"]) != float(record["current_max"])
                ),
                "method_key": method.key,
                "method_label": method.label,
                "method_description": method.description,
                "dashboard_category": base["dashboard_category"],
                "seasonality_enabled": base["seasonality_enabled"],
                "planning_season": base["planning_season"],
                "seasonal_months_used": base["summary_month_scope"],
                "reference_window_months": base["reference_window_months"],
                "yoy_change_pct": base["yoy_change_pct"],
                "reference_window_rule": base["reference_window_rule"],
                "forecast_mode": base["forecast_mode"],
                "forecast_coverage_locations": sum(1 for record in records if bool(record["forecast_used"])),
                "product_group_trend_source": base["product_group_trend_source"],
                "product_group_trend_label": base["product_group_trend_label"],
                "product_group_trend_factor": base["product_group_trend_factor"],
                "product_group_recent_avg": base["product_group_recent_avg"],
                "product_group_prior_avg": base["product_group_prior_avg"],
                "seasonality_note": base["seasonality_note"],
            }
        )
        detail_records.extend(records)

    detail = pd.DataFrame(detail_records)
    item_summary = pd.DataFrame(item_records)

    if not detail.empty:
        detail = detail.sort_values(["supplier", "item", "location_sort"], kind="stable").reset_index(drop=True)
    if not item_summary.empty:
        item_summary = item_summary.sort_values(
            ["supplier", "prod_group", "item"], kind="stable"
        ).reset_index(drop=True)

    return detail, item_summary


def calculate_all_methods(
    data: pd.DataFrame,
    monthly_columns: list[str],
    seasonality: SeasonalityConfig | None = None,
    acceleration: AccelerationStatus | None = None,
    forecast_lookup: dict[tuple[str, str, str], float] | None = None,
    service_levels: dict[str, float] | None = None,
    cheap_local_deviation_threshold: float = 1.0,
    remove_highest_outlier_enabled: bool = False,
    highest_outlier_threshold_pct: float = DEFAULT_HIGHEST_OUTLIER_THRESHOLD_PCT,
) -> dict[str, dict[str, pd.DataFrame]]:
    results: dict[str, dict[str, pd.DataFrame]] = {}
    for method in METHODS:
        detail, item_summary = calculate_method(
            data,
            monthly_columns,
            method,
            seasonality,
            acceleration,
            forecast_lookup,
            service_levels,
            cheap_local_deviation_threshold,
            remove_highest_outlier_enabled,
            highest_outlier_threshold_pct,
        )
        results[method.key] = {"detail": detail, "summary": item_summary}
    return results


def _build_group_records(
    ordered: pd.DataFrame,
    monthly_columns: list[str],
    method: MethodConfig,
    seasonality: SeasonalityConfig | None,
    supplier_prod_group_profiles: dict[tuple[str, str], dict[str, object]],
    global_prod_group_profiles: dict[str, dict[str, object]],
    forecast_lookup: dict[tuple[str, str, str], float] | None,
    service_levels: dict[str, float],
    cheap_local_deviation_threshold: float,
    remove_highest_outlier_enabled: bool,
    highest_outlier_threshold_pct: float,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    reference_window = _determine_reference_window(ordered, monthly_columns)
    month_labels_for_mean = monthly_columns[: min(method.mean_months, reference_window["months"])]
    month_labels_for_std = monthly_columns[: min(method.std_months, reference_window["months"])]
    summary_month_labels = month_labels_for_mean

    planning_season = seasonality.planning_season if seasonality and seasonality.enabled else "All Months"
    seasonality_enabled = bool(seasonality and seasonality.enabled)

    for row in ordered.to_dict(orient="records"):
        reference_mean_labels = list(month_labels_for_mean)
        scoped_mean_labels = _apply_seasonality_window(
            month_labels_for_mean,
            row["season"],
            seasonality,
        )
        scoped_std_labels = _apply_seasonality_window(
            month_labels_for_std,
            row["season"],
            seasonality,
        )
        scoped_summary_labels = _apply_seasonality_window(
            summary_month_labels,
            row["season"],
            seasonality,
        )

        reference_mean_values = [_calculation_month_value(row[label]) for label in reference_mean_labels]
        raw_mean_values = [_calculation_month_value(row[label]) for label in scoped_mean_labels]
        raw_std_values = [_calculation_month_value(row[label]) for label in scoped_std_labels]
        forecast_key = (
            str(row.get("supplier", "")),
            str(row.get("item", "")),
            str(row.get("location", "")),
        )
        autogluon_forecast_mean = None if forecast_lookup is None else forecast_lookup.get(forecast_key)
        forecast_used = autogluon_forecast_mean is not None
        mean_two_point_spike = _normalize_two_point_intermittent_spike(
            scoped_mean_labels,
            raw_mean_values,
            method,
            row,
            forecast_used=forecast_used,
        )
        if scoped_std_labels == scoped_mean_labels:
            std_two_point_spike = mean_two_point_spike
        else:
            std_two_point_spike = _normalize_two_point_intermittent_spike(
                scoped_std_labels,
                raw_std_values,
                method,
                row,
                forecast_used=forecast_used,
            )
        mean_outlier = _remove_highest_outlier_month(
            scoped_mean_labels,
            list(mean_two_point_spike["values"]),
            enabled=remove_highest_outlier_enabled,
            threshold_pct=highest_outlier_threshold_pct,
        )
        if scoped_std_labels == scoped_mean_labels:
            std_outlier = mean_outlier
        else:
            std_outlier = _remove_highest_outlier_month(
                scoped_std_labels,
                list(std_two_point_spike["values"]),
                enabled=remove_highest_outlier_enabled,
                threshold_pct=highest_outlier_threshold_pct,
            )
        mean_values = list(mean_outlier["values"])
        std_values = list(std_outlier["values"])
        adjusted_reference_mean_values = _apply_outlier_value_to_reference_window(
            reference_mean_labels,
            reference_mean_values,
            mean_outlier,
        )

        raw_filtered_mean = _average(mean_values, include_zeros=method.mean_include_zeros)
        raw_filtered_std = _sample_std(std_values, include_zeros=method.std_include_zeros)
        product_group_trend = _resolve_product_group_trend(
            row,
            scoped_mean_labels,
            supplier_prod_group_profiles,
            global_prod_group_profiles,
        )
        lead_time_days = _lead_time_days(row.get("lead_time"))
        frequency_days = _frequency_days(row.get("frequency"))
        raw_protection_days = lead_time_days + frequency_days
        protection_days = max(raw_protection_days, 28.0)
        minimum_28_day_rule_applied = raw_protection_days < 28.0
        supplier_policy = _supplier_inventory_policy(row.get("supplier"))
        dc_location_reserve_rule_applied = (
            bool(supplier_policy["hub_managed"])
            and _is_dc_location(row.get("location"), row.get("supplier"))
        )
        intermittent_branch = _evaluate_intermittent_branch_protection(
            mean_values,
            method,
            row,
            forecast_used,
        )
        pre_phase_filtered_mean = (
            float(intermittent_branch["effective_mean"])
            if bool(intermittent_branch["applied"])
            else raw_filtered_mean
        )
        thin_history_dc_fallback = _evaluate_thin_history_seasonal_dc_mean_fallback(
            row=row,
            scoped_mean_labels=scoped_mean_labels,
            mean_values=mean_values,
            seasonality=seasonality,
            dc_location_reserve_rule_applied=dc_location_reserve_rule_applied,
            forecast_used=forecast_used,
            protection_days=protection_days,
        )
        if bool(thin_history_dc_fallback["applied"]):
            raw_filtered_mean = float(thin_history_dc_fallback["inclusive_mean"])
            pre_phase_filtered_mean = float(thin_history_dc_fallback["inclusive_mean"])
        seasonal_ramp = _resolve_replenishment_window_seasonal_ramp(
            reference_labels=reference_mean_labels,
            reference_values=adjusted_reference_mean_values,
            scoped_labels=scoped_mean_labels,
            scoped_values=mean_values,
            base_mean=pre_phase_filtered_mean,
            seasonality=seasonality,
            protection_days=protection_days,
            method=method,
            forecast_used=forecast_used,
            intermittent_branch_applied=bool(intermittent_branch["applied"]),
        )
        filtered_mean = pre_phase_filtered_mean * float(seasonal_ramp["factor"])
        filtered_std = raw_filtered_std * float(seasonal_ramp["factor"])
        if forecast_used:
            trend_adjusted_mean = max(float(autogluon_forecast_mean), 0.0)
            raw_trend_adjusted_mean = trend_adjusted_mean
            pre_phase_trend_adjusted_mean = trend_adjusted_mean
            forecast_mode = "AI Forecast + Rules"
            mean_source = "AutoGluon forecast"
            applied_product_group_factor = 1.0
        else:
            raw_trend_adjusted_mean = raw_filtered_mean * float(product_group_trend["factor"])
            pre_phase_trend_adjusted_mean = pre_phase_filtered_mean * float(product_group_trend["factor"])
            trend_adjusted_mean = filtered_mean * float(product_group_trend["factor"])
            forecast_mode = "Rules Only"
            mean_source = "Historical demand"
            applied_product_group_factor = float(product_group_trend["factor"])
        rounded_mean = _round_value(trend_adjusted_mean, method.rounding_mode)
        raw_rounded_mean = _round_value(pre_phase_trend_adjusted_mean, method.rounding_mode)
        delta = trend_adjusted_mean - rounded_mean
        total_dev = delta + filtered_std
        raw_intermittent_direct_transfer = max(raw_trend_adjusted_mean - pre_phase_trend_adjusted_mean, 0.0)
        intermittent_direct_transfer_allowed = bool(
            mean_outlier["applied"]
            or std_outlier["applied"]
            or mean_two_point_spike["applied"]
            or std_two_point_spike["applied"]
        )
        intermittent_spike_pooled_to_dc = (
            raw_intermittent_direct_transfer if intermittent_direct_transfer_allowed else 0.0
        )
        service_level = _service_level(row.get("abc"), service_levels)
        service_level_pct = round(service_level * 100, 1)
        service_z_score = NormalDist().inv_cdf(service_level)
        daily_mean = trend_adjusted_mean / DAYS_PER_MONTH if DAYS_PER_MONTH else 0.0
        lead_time_demand = daily_mean * lead_time_days
        cycle_demand = daily_mean * max(protection_days - lead_time_days, 0.0)
        protected_cycle_demand = lead_time_demand + cycle_demand
        lead_time_std = filtered_std * math.sqrt(lead_time_days / DAYS_PER_MONTH) if lead_time_days > 0 else 0.0
        protection_std = filtered_std * math.sqrt(protection_days / DAYS_PER_MONTH) if protection_days > 0 else 0.0
        demand_only_min_amount = math.ceil(max(lead_time_demand, 0.0))
        service_level_min_amount = math.ceil(max(lead_time_demand + (service_z_score * lead_time_std), 0.0))
        dc_transfer_reserve_amount = math.ceil(max(protected_cycle_demand, 0.0))
        demand_only_order_up_to = math.ceil(max(protected_cycle_demand, demand_only_min_amount))
        service_level_order_up_to = math.ceil(
            max(protected_cycle_demand + (service_z_score * protection_std), service_level_min_amount)
        )
        if dc_location_reserve_rule_applied:
            recommended_min_amount = dc_transfer_reserve_amount
            policy_order_up_to = service_level_order_up_to
        else:
            recommended_min_amount = demand_only_min_amount
            policy_order_up_to = demand_only_order_up_to
        override_flag = _override_flag(row.get("override"))

        records.append(
            {
                **row,
                "method_key": method.key,
                "method_label": method.label,
                "filtered_mean": filtered_mean,
                "raw_filtered_mean": raw_filtered_mean,
                "pre_phase_filtered_mean": pre_phase_filtered_mean,
                "trend_adjusted_mean": trend_adjusted_mean,
                "raw_trend_adjusted_mean": raw_trend_adjusted_mean,
                "pre_phase_trend_adjusted_mean": pre_phase_trend_adjusted_mean,
                "autogluon_forecast_mean": autogluon_forecast_mean,
                "forecast_used": forecast_used,
                "forecast_mode": forecast_mode,
                "mean_source": mean_source,
                "filtered_std_dev": filtered_std,
                "raw_filtered_std_dev": raw_filtered_std,
                "rounded_mean": rounded_mean,
                "raw_rounded_mean": raw_rounded_mean,
                "delta": delta,
                "total_dev": total_dev,
                "daily_demand": daily_mean,
                "service_level": service_level,
                "service_level_pct": service_level_pct,
                "service_z_score": service_z_score,
                "lead_time_days": lead_time_days,
                "frequency_days": frequency_days,
                "review_cycle_days": frequency_days,
                "raw_protection_days": raw_protection_days,
                "protection_days": protection_days,
                "minimum_28_day_rule_applied": minimum_28_day_rule_applied,
                "lead_time_demand": lead_time_demand,
                "cycle_demand": cycle_demand,
                "protected_cycle_demand": protected_cycle_demand,
                "lead_time_std": lead_time_std,
                "protection_std": protection_std,
                "demand_only_min_amount": demand_only_min_amount,
                "service_level_min_amount": service_level_min_amount,
                "dc_transfer_reserve_amount": dc_transfer_reserve_amount,
                "demand_only_order_up_to": demand_only_order_up_to,
                "service_level_order_up_to": service_level_order_up_to,
                "recommended_min_amount": recommended_min_amount,
                "policy_order_up_to": policy_order_up_to,
                "dc_location_reserve_rule_applied": dc_location_reserve_rule_applied,
                "supplier_hub_managed": bool(supplier_policy["hub_managed"]),
                "designated_dc_location": str(supplier_policy["dc_location"] or ""),
                "product_group_trend_source": product_group_trend["source"],
                "product_group_trend_label": product_group_trend["label"],
                "product_group_trend_factor": applied_product_group_factor,
                "product_group_recent_avg": product_group_trend["recent_avg"],
                "product_group_prior_avg": product_group_trend["prior_avg"],
                "product_group_trend_scope": product_group_trend["scope"],
                "intermittent_branch_protection_applied": bool(intermittent_branch["applied"]),
                "intermittent_scope_months": int(intermittent_branch["scope_months"]),
                "intermittent_non_zero_months": int(intermittent_branch["non_zero_months"]),
                "intermittent_adi": float(intermittent_branch["adi"]),
                "intermittent_top_two_share_pct": float(intermittent_branch["top_two_share_pct"]),
                "intermittent_inclusive_mean": float(intermittent_branch["inclusive_mean"]),
                "intermittent_reason": str(intermittent_branch["reason"]),
                "raw_intermittent_direct_transfer": raw_intermittent_direct_transfer,
                "intermittent_direct_transfer_allowed": bool(intermittent_direct_transfer_allowed),
                "intermittent_direct_transfer_suppressed": bool(
                    raw_intermittent_direct_transfer > 0 and not intermittent_direct_transfer_allowed
                ),
                "intermittent_spike_pooled_to_dc": intermittent_spike_pooled_to_dc,
                "two_point_spike_normalized": bool(mean_two_point_spike["applied"] or std_two_point_spike["applied"]),
                "two_point_spike_normalized_from_mean": bool(mean_two_point_spike["applied"]),
                "two_point_spike_normalized_from_std": bool(std_two_point_spike["applied"]),
                "two_point_spike_normalized_month_mean": str(mean_two_point_spike["normalized_label"]),
                "two_point_spike_normalized_month_std": str(std_two_point_spike["normalized_label"]),
                "two_point_spike_normalized_value_mean": float(mean_two_point_spike["normalized_value"]),
                "two_point_spike_normalized_value_std": float(std_two_point_spike["normalized_value"]),
                "two_point_spike_normalized_baseline_value_mean": float(mean_two_point_spike["baseline_value"]),
                "two_point_spike_normalized_baseline_value_std": float(std_two_point_spike["baseline_value"]),
                "two_point_spike_normalized_ratio_mean": float(mean_two_point_spike["ratio"]),
                "two_point_spike_normalized_ratio_std": float(std_two_point_spike["ratio"]),
                "highest_outlier_filter_enabled": bool(remove_highest_outlier_enabled),
                "highest_outlier_threshold_pct": float(highest_outlier_threshold_pct),
                "highest_outlier_removed": bool(mean_outlier["applied"] or std_outlier["applied"]),
                "highest_outlier_removed_from_mean": bool(mean_outlier["applied"]),
                "highest_outlier_removed_from_std": bool(std_outlier["applied"]),
                "highest_outlier_removed_month_mean": str(mean_outlier["removed_label"]),
                "highest_outlier_removed_month_std": str(std_outlier["removed_label"]),
                "highest_outlier_removed_value_mean": float(mean_outlier["removed_value"]),
                "highest_outlier_removed_value_std": float(std_outlier["removed_value"]),
                "highest_outlier_baseline_value_mean": float(mean_outlier["baseline_value"]),
                "highest_outlier_baseline_value_std": float(std_outlier["baseline_value"]),
                "highest_outlier_trigger_pct_mean": float(mean_outlier["ratio_pct"]),
                "highest_outlier_trigger_pct_std": float(std_outlier["ratio_pct"]),
                "highest_outlier_non_zero_months_mean": int(mean_outlier["non_zero_months"]),
                "highest_outlier_non_zero_months_std": int(std_outlier["non_zero_months"]),
                "seasonal_ramp_applied": bool(seasonal_ramp["applied"]),
                "seasonal_ramp_factor": float(seasonal_ramp["factor"]),
                "seasonal_ramp_mode": str(seasonal_ramp["mode"]),
                "seasonal_ramp_reason": str(seasonal_ramp["reason"]),
                "seasonal_ramp_window": str(seasonal_ramp["window_label"]),
                "seasonal_ramp_start_date": str(seasonal_ramp["start_date"]),
                "seasonal_ramp_window_average": float(seasonal_ramp["window_average"]),
                "seasonal_ramp_full_season_average": float(seasonal_ramp["full_season_average"]),
                "seasonal_ramp_non_zero_points": int(seasonal_ramp["non_zero_points"]),
                "seasonal_ramp_distinct_months": int(seasonal_ramp["distinct_months"]),
                "seasonal_ramp_peak_month": str(seasonal_ramp["peak_month"]),
                "deviation_pooled_to_dc": 0.0,
                "deviation_absorbed_by_dc": 0.0,
                "variability_pooled_to_dc": 0.0,
                "direct_transfer_pooled_to_dc": 0.0,
                "pooled_variance_absorbed_by_dc": 0.0,
                "pooled_direct_transfer_absorbed_by_dc": 0.0,
                "override_flag": override_flag,
                "active_months_mean": _value_count(mean_values, include_zeros=method.mean_include_zeros),
                "active_months_std": _value_count(std_values, include_zeros=method.std_include_zeros),
                "mean_months_window": len(scoped_mean_labels),
                "std_months_window": len(scoped_std_labels),
                "mean_month_scope": ", ".join(scoped_mean_labels),
                "std_month_scope": ", ".join(scoped_std_labels),
                "summary_month_scope": ", ".join(scoped_summary_labels),
                "summary_month_labels": scoped_summary_labels,
                "dashboard_category": _dashboard_category(row["status"]),
                "seasonality_enabled": seasonality_enabled,
                "planning_season": planning_season,
                "thin_history_seasonal_dc_mean_fallback_applied": bool(thin_history_dc_fallback["applied"]),
                "thin_history_seasonal_dc_inclusive_mean": float(thin_history_dc_fallback["inclusive_mean"]),
                "thin_history_seasonal_dc_non_zero_points": int(thin_history_dc_fallback["non_zero_points"]),
                "thin_history_seasonal_dc_positive_seasons": int(thin_history_dc_fallback["positive_seasons"]),
                "thin_history_seasonal_dc_reason": str(thin_history_dc_fallback["reason"]),
                "reference_window_months": reference_window["months"],
                "yoy_change_pct": reference_window["yoy_change_pct"],
                "reference_window_rule": reference_window["rule"],
                "negative_usage_netted_months": int(row.get("negative_usage_netted_months", 0) or 0),
                "negative_usage_netted_units": float(row.get("negative_usage_netted_units", 0.0) or 0.0),
                "negative_usage_unmatched_units": float(row.get("negative_usage_unmatched_units", 0.0) or 0.0),
                "seasonality_note": _seasonality_note(row["season"], seasonality, scoped_mean_labels),
                "recommendation_explanation": "",
                "recommended_new_max": 0.0,
                "is_balancing_location": False,
            }
        )

    return _finalize_group_records(records, cheap_local_deviation_threshold)

def _build_product_group_profiles(
    data: pd.DataFrame,
    monthly_columns: list[str],
    acceleration: AccelerationStatus,
) -> tuple[dict[tuple[str, str], dict[str, object]], dict[str, dict[str, object]]]:
    if data.empty or not monthly_columns:
        return {}, {}

    scoped = data.copy()
    scoped["prod_group"] = scoped["prod_group"].fillna("").map(str).map(str.strip)
    scoped = scoped[scoped["prod_group"] != ""]
    if scoped.empty:
        return {}, {}
    scoped.loc[:, monthly_columns] = scoped.loc[:, monthly_columns].clip(lower=0)

    supplier_monthly = aggregate_monthly_sum(
        scoped,
        ["supplier", "prod_group"],
        monthly_columns,
        acceleration,
    )
    global_monthly = aggregate_monthly_sum(
        scoped,
        ["prod_group"],
        monthly_columns,
        acceleration,
    )
    supplier_counts = (
        scoped.groupby(["supplier", "prod_group"], dropna=False)["item"]
        .nunique()
        .reset_index(name="item_count")
    )
    global_counts = (
        scoped.groupby(["prod_group"], dropna=False)["item"]
        .nunique()
        .reset_index(name="item_count")
    )

    supplier_joined = supplier_monthly.merge(supplier_counts, on=["supplier", "prod_group"], how="left")
    global_joined = global_monthly.merge(global_counts, on=["prod_group"], how="left")

    supplier_profiles = {
        (str(row["supplier"]), str(row["prod_group"])): {
            "item_count": int(row["item_count"]),
            "monthly_totals": {label: float(row[label]) for label in monthly_columns},
        }
        for row in supplier_joined.to_dict(orient="records")
    }
    global_profiles = {
        str(row["prod_group"]): {
            "item_count": int(row["item_count"]),
            "monthly_totals": {label: float(row[label]) for label in monthly_columns},
        }
        for row in global_joined.to_dict(orient="records")
    }
    return supplier_profiles, global_profiles


def _precompute_method_frame_wsl(
    data: pd.DataFrame,
    monthly_columns: list[str],
    method: MethodConfig,
    seasonality: SeasonalityConfig | None,
    forecast_lookup: dict[tuple[str, str, str], float] | None,
    service_levels: dict[str, float],
    remove_highest_outlier_enabled: bool,
    highest_outlier_threshold_pct: float,
) -> pd.DataFrame:
    with tempfile.TemporaryDirectory(prefix="deviation_dash_recs_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "recommendations_input.parquet"
        output_path = temp_path / "recommendations_output.parquet"
        params_path = temp_path / "recommendations_params.json"

        data.to_parquet(input_path, index=False)
        params = {
            "monthly_columns": monthly_columns,
            "method": {
                "key": method.key,
                "label": method.label,
                "description": method.description,
                "mean_months": method.mean_months,
                "mean_include_zeros": method.mean_include_zeros,
                "std_months": method.std_months,
                "std_include_zeros": method.std_include_zeros,
                "rounding_mode": method.rounding_mode,
            },
            "seasonality": {
                "enabled": bool(seasonality and seasonality.enabled),
                "planning_season": seasonality.planning_season if seasonality and seasonality.enabled else "All Months",
            },
            "service_levels": service_levels,
            "remove_highest_outlier_enabled": bool(remove_highest_outlier_enabled),
            "highest_outlier_threshold_pct": float(highest_outlier_threshold_pct),
        }
        params_path.write_text(json.dumps(params), encoding="utf-8")

        arguments: list[object] = [
            "--input",
            windows_to_wsl_path(input_path),
            "--output",
            windows_to_wsl_path(output_path),
            "--params",
            windows_to_wsl_path(params_path),
        ]

        forecast_path = None
        if forecast_lookup:
            forecast_path = temp_path / "forecast_lookup.parquet"
            forecast_frame = pd.DataFrame(
                [
                    {
                        "supplier": supplier,
                        "item": item,
                        "location": location,
                        "forecast_mean": float(value),
                    }
                    for (supplier, item, location), value in forecast_lookup.items()
                ]
            )
            forecast_frame.to_parquet(forecast_path, index=False)
            arguments.extend(["--forecast", windows_to_wsl_path(forecast_path)])

        run_wsl_rapids_script(
            WSL_PRECOMPUTE_SCRIPT,
            command_arguments=arguments,
            timeout_seconds=1800,
        )
        return pd.read_parquet(output_path)


def _summary_month_labels(record: dict[str, object]) -> list[str]:
    labels = record.get("summary_month_labels")
    if isinstance(labels, list):
        return labels
    scope = str(record.get("summary_month_scope", "") or "").strip()
    if not scope:
        return []
    return [label.strip() for label in scope.split(",") if label.strip()]


def _recent_month_labels(record: dict[str, object], limit: int = 12) -> list[str]:
    dated_labels: list[tuple[datetime, str]] = []
    for key in record.keys():
        label = str(key or "").strip()
        month_start = _month_start(label)
        if month_start is None:
            continue
        dated_labels.append((month_start, label))
    dated_labels.sort(key=lambda pair: pair[0], reverse=True)
    return [label for _, label in dated_labels[: max(limit, 0)]]


def _is_yes(value: object) -> bool:
    return str(value or "").strip().upper() in {"Y", "YES", "TRUE", "1"}


def _detect_project_spike_suppression(
    record: dict[str, object],
    recent_12_labels: list[str],
    company_recent_12_month_totals: dict[str, float],
) -> dict[str, object]:
    branch_month_totals = [(label, _calculation_month_value(record.get(label))) for label in recent_12_labels]
    branch_non_zero = [(label, total) for label, total in branch_month_totals if total > 0]
    branch_recent_12_total = sum(total for _, total in branch_month_totals)
    company_recent_12_total = sum(float(total) for total in company_recent_12_month_totals.values())

    if not branch_non_zero:
        return {
            "applied": False,
            "branch_recent_12_non_zero_months": 0,
            "branch_recent_12_total": branch_recent_12_total,
            "company_recent_12_total": company_recent_12_total,
            "top_month_label": "",
            "top_month_value": 0.0,
            "branch_top_month_share_pct": 0.0,
            "company_top_month_share_pct": 0.0,
            "next_company_month_value": 0.0,
            "company_month_multiple": 0.0,
            "top_month_vs_current_max": 0.0,
            "reason": "",
        }

    top_month_label, top_month_value = max(branch_non_zero, key=lambda pair: pair[1])
    branch_recent_12_non_zero_months = len(branch_non_zero)
    branch_top_month_share = (top_month_value / branch_recent_12_total) if branch_recent_12_total > 0 else 0.0
    company_top_month_share = (top_month_value / company_recent_12_total) if company_recent_12_total > 0 else 0.0
    next_company_month_value = max(
        (
            float(total)
            for label, total in company_recent_12_month_totals.items()
            if label != top_month_label
        ),
        default=0.0,
    )
    company_month_multiple = (
        math.inf
        if top_month_value > 0 and next_company_month_value <= 0
        else (top_month_value / next_company_month_value if next_company_month_value > 0 else 0.0)
    )
    status_is_bulk = _status_key(record.get("status")) == "bulk"
    status_is_regional = _status_contains_regional(record.get("status"))
    stockable = _is_yes(record.get("stockable"))
    current_max = float(record.get("current_max", 0.0))
    top_month_vs_current_max = (
        math.inf
        if top_month_value > 0 and current_max <= 0
        else (top_month_value / current_max if current_max > 0 else 0.0)
    )
    company_share_trigger = (
        company_top_month_share >= PROJECT_SPIKE_COMPANY_SHARE_THRESHOLD
        or company_month_multiple >= PROJECT_SPIKE_NEXT_MONTH_MULTIPLE
    )
    stocked_branch_trigger = (
        current_max > 0
        and top_month_vs_current_max >= PROJECT_SPIKE_CURRENT_MAX_MULTIPLE
        and (
            company_top_month_share >= PROJECT_SPIKE_STOCKED_COMPANY_SHARE_THRESHOLD
            or company_month_multiple >= PROJECT_SPIKE_NEXT_MONTH_MULTIPLE
        )
    )
    zero_max_or_non_stockable_trigger = current_max <= 0 and (status_is_bulk or not stockable)
    applied = (
        not bool(record.get("dc_location_reserve_rule_applied"))
        and not status_is_regional
        and branch_recent_12_non_zero_months <= PROJECT_SPIKE_MAX_BRANCH_USAGE_PERIODS
        and branch_top_month_share >= PROJECT_SPIKE_BRANCH_SHARE_THRESHOLD
        and (
            (zero_max_or_non_stockable_trigger and company_share_trigger)
            or stocked_branch_trigger
        )
    )
    reason = ""
    if applied:
        base_reason = (
            f"{top_month_label} supplied {top_month_value:.1f} units, which is "
            f"{branch_top_month_share * 100.0:.0f}% of this branch's last-12-month usage and "
            f"{company_top_month_share * 100.0:.0f}% of the company's last-12-month usage. "
            f"The next-highest company month is only {next_company_month_value:.1f}"
        )
        if current_max > 0:
            reason = (
                f"{base_reason}, and that month is {top_month_vs_current_max:.1f}x the branch's current max of {current_max:.1f}. "
                "This looks like a one-time project/non-replenishment hit rather than a repeat stocking signal."
            )
        else:
            reason = (
                f"{base_reason}, so this looks like a one-time project/non-replenishment hit."
            )

    return {
        "applied": applied,
        "branch_recent_12_non_zero_months": branch_recent_12_non_zero_months,
        "branch_recent_12_total": branch_recent_12_total,
        "company_recent_12_total": company_recent_12_total,
        "top_month_label": top_month_label,
        "top_month_value": top_month_value,
        "branch_top_month_share_pct": branch_top_month_share * 100.0,
        "company_top_month_share_pct": company_top_month_share * 100.0,
        "next_company_month_value": next_company_month_value,
        "company_month_multiple": 999999.0 if math.isinf(company_month_multiple) else company_month_multiple,
        "top_month_vs_current_max": 999999.0 if math.isinf(top_month_vs_current_max) else top_month_vs_current_max,
        "reason": reason,
    }


def _apply_project_spike_suppression(record: dict[str, object]) -> None:
    for key in (
        "filtered_mean",
        "filtered_std_dev",
        "trend_adjusted_mean",
        "rounded_mean",
        "delta",
        "total_dev",
        "daily_demand",
        "lead_time_demand",
        "cycle_demand",
        "protected_cycle_demand",
        "lead_time_std",
        "protection_std",
        "demand_only_min_amount",
        "service_level_min_amount",
        "dc_transfer_reserve_amount",
        "demand_only_order_up_to",
        "service_level_order_up_to",
        "recommended_min_amount",
        "policy_order_up_to",
        "base_branch_recommendation",
        "branch_demand_recommendation",
        "service_level_recommendation",
        "preliminary_deviation_pool",
        "intermittent_spike_pooled_to_dc",
        "variability_pooled_to_dc",
        "direct_transfer_pooled_to_dc",
        "deviation_pooled_to_dc",
        "low_cost_local_deviation_kept_amount",
        "recommended_new_max",
    ):
        if key in record:
            record[key] = 0.0
    _sync_branch_dc_pool(record)


def _apply_sparse_seasonal_company_ceiling(
    records: list[dict[str, object]],
    monthly_columns: list[str],
    seasonality: SeasonalityConfig | None,
) -> None:
    def ceiling_floor(record: dict[str, object]) -> float:
        floor = max(
            float(record.get("current_max", 0.0)),
            float(record.get("recommended_min_amount", 0.0)),
        )
        if float(record.get("recommended_new_max", 0.0)) > 0:
            floor = max(floor, _supplier_min_amount_floor(record.get("supplier_min_amount")))
        return floor

    for record in records:
        record["sparse_seasonal_company_ceiling_applied"] = False
        record["sparse_seasonal_company_ceiling"] = 0.0
        record["sparse_seasonal_company_reference_total"] = 0.0
        record["sparse_seasonal_company_reference_season"] = ""
        record["sparse_seasonal_company_non_zero_months"] = 0
        record["sparse_seasonal_company_positive_seasons"] = 0
        record["sparse_seasonal_company_trimmed_amount"] = 0.0
        record["sparse_seasonal_company_rule_reason"] = ""
        record["sparse_seasonal_company_dc_floor_capped"] = False

    if not records or not seasonality or not seasonality.enabled:
        return

    primary = records[0]
    item_season = str(primary.get("season", "") or "").strip()
    planning_season = str(seasonality.planning_season or "").strip()
    if not item_season or item_season.casefold() != planning_season.casefold():
        return

    max_protection_days = max(float(record.get("protection_days", 0.0)) for record in records)
    if max_protection_days <= SPARSE_SEASONAL_COMPANY_CEILING_PROTECTION_DAYS_THRESHOLD:
        return

    summary_labels = _summary_month_labels(primary)
    if not summary_labels:
        return

    scoped_month_totals = {
        label: sum(_mac_amount(record.get(label)) for record in records)
        for label in summary_labels
    }
    scoped_non_zero_months = sum(1 for total in scoped_month_totals.values() if total > 0)
    if scoped_non_zero_months > SPARSE_SEASONAL_COMPANY_CEILING_NON_ZERO_MONTHS_THRESHOLD:
        return

    season_blocks = _season_block_totals(records, monthly_columns, planning_season)
    positive_blocks = [block for block in season_blocks if float(block["total"]) > 0]
    if not positive_blocks:
        return

    latest_positive_block = positive_blocks[-1]
    previous_block_total = 0.0
    latest_index = next(
        (index for index, block in enumerate(season_blocks) if block["key"] == latest_positive_block["key"]),
        -1,
    )
    if latest_index > 0:
        previous_block_total = float(season_blocks[latest_index - 1]["total"])

    positive_season_count = len(positive_blocks)
    sparse_single_season_history = positive_season_count <= 1 or previous_block_total <= 0.0
    if not sparse_single_season_history:
        return

    company_reference_total = float(latest_positive_block["total"])
    if company_reference_total <= 0:
        return

    company_ceiling = float(max(1, math.ceil(company_reference_total * SPARSE_SEASONAL_COMPANY_CEILING_BUFFER_FACTOR)))
    current_network_total = sum(float(record.get("recommended_new_max", 0.0)) for record in records)
    if current_network_total <= company_ceiling:
        return

    reason = (
        f"the item only shows {positive_season_count} selling {planning_season.lower()} season"
        f"{'' if positive_season_count == 1 else 's'} in the available history, "
        f"the most recent positive season used {company_reference_total:.1f} units across "
        f"{scoped_non_zero_months} active in-season months, and the protection window is {max_protection_days:.1f} days"
    )

    excess_to_trim = current_network_total - company_ceiling

    zero_max_branch_candidates = sorted(
        (
            record for record in records[1:]
            if float(record.get("current_max", 0.0)) <= 0 and float(record.get("recommended_new_max", 0.0)) > 0
        ),
        key=lambda record: float(record.get("recommended_new_max", 0.0)),
        reverse=True,
    )
    for record in zero_max_branch_candidates:
        if excess_to_trim <= 0:
            break
        current_recommendation = float(record.get("recommended_new_max", 0.0))
        partial_floor = ceiling_floor(record)
        if excess_to_trim >= current_recommendation:
            reduction = current_recommendation
        else:
            reduction = min(excess_to_trim, max(current_recommendation - partial_floor, 0.0))
        if reduction <= 0:
            continue
        new_recommendation = current_recommendation - reduction
        if reduction >= current_recommendation:
            new_recommendation = 0.0
        elif 0.0 < new_recommendation < partial_floor:
            new_recommendation = partial_floor
        record["recommended_new_max"] = new_recommendation
        record["recommended_min_amount"] = min(
            float(record.get("recommended_min_amount", 0.0)),
            float(record.get("recommended_new_max", 0.0)),
        )
        _reduce_branch_dc_pool(record, reduction)
        record["sparse_seasonal_company_trimmed_amount"] += reduction
        excess_to_trim -= reduction

    _recompute_primary_dc_absorption(records)

    if excess_to_trim > 0:
        primary_floor = ceiling_floor(primary)
        primary_reducible = max(float(primary.get("recommended_new_max", 0.0)) - primary_floor, 0.0)
        reduction = min(excess_to_trim, primary_reducible)
        if reduction > 0:
            primary["recommended_new_max"] = max(float(primary.get("recommended_new_max", 0.0)) - reduction, primary_floor)
            _reduce_primary_dc_absorption(primary, reduction)
            primary["sparse_seasonal_company_trimmed_amount"] += reduction
            excess_to_trim -= reduction

    remaining_branch_candidates = sorted(
        (
            record for record in records[1:]
            if float(record.get("recommended_new_max", 0.0)) > ceiling_floor(record)
        ),
        key=lambda record: (
            float(record.get("recommended_new_max", 0.0)) - ceiling_floor(record)
        ),
        reverse=True,
    )
    for record in remaining_branch_candidates:
        if excess_to_trim <= 0:
            break
        branch_floor = ceiling_floor(record)
        reducible = max(float(record.get("recommended_new_max", 0.0)) - branch_floor, 0.0)
        reduction = min(excess_to_trim, reducible)
        if reduction <= 0:
            continue
        record["recommended_new_max"] = max(float(record.get("recommended_new_max", 0.0)) - reduction, branch_floor)
        record["recommended_min_amount"] = min(
            float(record.get("recommended_min_amount", 0.0)),
            float(record.get("recommended_new_max", 0.0)),
        )
        record["sparse_seasonal_company_trimmed_amount"] += reduction
        excess_to_trim -= reduction

    _recompute_primary_dc_absorption(records)
    remaining_primary_allowance = max(
        company_ceiling - sum(float(record.get("recommended_new_max", 0.0)) for record in records[1:]),
        0.0,
    )
    primary_target = (
        max(remaining_primary_allowance, ceiling_floor(primary))
        if float(primary.get("recommended_new_max", 0.0)) > 0
        else remaining_primary_allowance
    )
    primary_overage = max(float(primary.get("recommended_new_max", 0.0)) - primary_target, 0.0)
    if primary_overage > 0:
        primary["recommended_new_max"] = primary_target
        primary["recommended_min_amount"] = min(
            float(primary.get("recommended_min_amount", 0.0)),
            float(primary.get("recommended_new_max", 0.0)),
        )
        _reduce_primary_dc_absorption(primary, primary_overage)
        primary["sparse_seasonal_company_trimmed_amount"] += primary_overage
        primary["sparse_seasonal_company_dc_floor_capped"] = True
        excess_to_trim = max(excess_to_trim - primary_overage, 0.0)

    trimmed_total = sum(float(record.get("sparse_seasonal_company_trimmed_amount", 0.0)) for record in records)
    if trimmed_total <= 0:
        return

    reference_season_label = str(latest_positive_block["label"])
    for record in records:
        record["sparse_seasonal_company_ceiling_applied"] = True
        record["sparse_seasonal_company_ceiling"] = company_ceiling
        record["sparse_seasonal_company_reference_total"] = company_reference_total
        record["sparse_seasonal_company_reference_season"] = reference_season_label
        record["sparse_seasonal_company_non_zero_months"] = scoped_non_zero_months
        record["sparse_seasonal_company_positive_seasons"] = positive_season_count
        record["sparse_seasonal_company_rule_reason"] = reason

    for record in records:
        trimmed_amount = float(record.get("sparse_seasonal_company_trimmed_amount", 0.0))
        if trimmed_amount <= 0:
            continue
        destination = (
            "DC min/max floor"
            if bool(record.get("sparse_seasonal_company_dc_floor_capped"))
            else
            "DC seasonal overage above protected floor"
            if _is_dc_location(record.get("location"), record.get("supplier"))
            and float(record.get("deviation_absorbed_by_dc", 0.0)) <= 0
            else
            "new zero-max branch stock"
            if not _is_dc_location(record.get("location"), record.get("supplier")) and float(record.get("current_max", 0.0)) <= 0
            else "pooled DC coverage"
            if _is_dc_location(record.get("location"), record.get("supplier"))
            else "branch excess above current working need"
        )
        record["recommendation_explanation"] += (
            f" Sparse seasonal company ceiling trimmed {trimmed_amount:.1f} units from {destination} because "
            f"{reason}. The company ceiling for {reference_season_label} is {company_ceiling:.0f} units "
            f"after applying a {((SPARSE_SEASONAL_COMPANY_CEILING_BUFFER_FACTOR - 1.0) * 100.0):.0f}% buffer."
        )

    primary["dc_pooling_zero_max_alert"] = (
        float(primary.get("current_max", 0.0)) <= 0
        and float(primary.get("deviation_absorbed_by_dc", 0.0)) > 0
        and float(primary.get("recommended_new_max", 0.0)) > 0
    )
    for record in records[1:]:
        record["branch_zero_max_recommendation_alert"] = (
            float(record.get("current_max", 0.0)) <= 0
            and float(record.get("recommended_new_max", 0.0)) > 0
            and not bool(record.get("regional_zero_max_branch_pool_applied"))
        )

    for record in records:
        record["recommendation_delta"] = float(record.get("recommended_new_max", 0.0)) - float(record.get("current_max", 0.0))
        record["recommended_min_delta"] = float(record.get("recommended_min_amount", 0.0)) - float(record.get("min_value", 0.0))


def _season_block_totals(
    records: list[dict[str, object]],
    monthly_columns: list[str],
    planning_season: str,
) -> list[dict[str, object]]:
    allowed_months = SEASON_MONTHS.get(planning_season, set())
    if not allowed_months:
        return []

    blocks: dict[int, dict[str, object]] = {}
    ordered_labels = sorted(
        (label for label in monthly_columns if _month_start(label) is not None),
        key=lambda label: _month_start(label) or datetime.min,
    )
    for label in ordered_labels:
        month_start = _month_start(label)
        if month_start is None or month_start.month not in allowed_months:
            continue
        season_key = _season_block_key(month_start, planning_season)
        block = blocks.setdefault(
            season_key,
            {
                "key": season_key,
                "label": _season_block_label(season_key, planning_season),
                "total": 0.0,
            },
        )
        block["total"] = float(block["total"]) + sum(_calculation_month_value(record.get(label)) for record in records)

    return [blocks[key] for key in sorted(blocks)]


def _season_block_key(month_start: datetime, planning_season: str) -> int:
    if planning_season == "Winter":
        return month_start.year + 1 if month_start.month >= 10 else month_start.year
    return month_start.year


def _season_block_label(season_key: int, planning_season: str) -> str:
    if planning_season == "Winter":
        return f"Winter {season_key - 1}-{str(season_key)[-2:]}"
    return f"{planning_season} {season_key}"


def _evaluate_thin_history_seasonal_dc_mean_fallback(
    row: dict[str, object],
    scoped_mean_labels: list[str],
    mean_values: list[float],
    seasonality: SeasonalityConfig | None,
    dc_location_reserve_rule_applied: bool,
    forecast_used: bool,
    protection_days: float,
) -> dict[str, object]:
    result = {
        "applied": False,
        "inclusive_mean": 0.0,
        "non_zero_points": 0,
        "positive_seasons": 0,
        "reason": "",
    }

    if (
        not dc_location_reserve_rule_applied
        or forecast_used
        or not seasonality
        or not seasonality.enabled
        or protection_days <= THIN_HISTORY_SEASONAL_DC_MIN_PROTECTION_DAYS
    ):
        return result

    item_season = str(row.get("season", "") or "").strip()
    planning_season = str(seasonality.planning_season or "").strip()
    if not _season_matches_planning(item_season, planning_season):
        return result

    positive_points = [
        (label, float(value))
        for label, value in zip(scoped_mean_labels, mean_values, strict=False)
        if float(value) > 0
    ]
    non_zero_points = len(positive_points)
    positive_seasons = len(
        {
            _season_block_key(month_start, planning_season)
            for label, _ in positive_points
            for month_start in [_month_start(label)]
            if month_start is not None
        }
    )
    result["non_zero_points"] = non_zero_points
    result["positive_seasons"] = positive_seasons

    if non_zero_points == 0:
        return result

    inclusive_mean = _average(mean_values, include_zeros=True)
    active_mean = _average(mean_values, include_zeros=False)
    result["inclusive_mean"] = inclusive_mean

    if (
        inclusive_mean <= 0
        or active_mean <= 0
        or inclusive_mean >= active_mean
        or non_zero_points > THIN_HISTORY_SEASONAL_DC_MAX_NON_ZERO_POINTS
        or positive_seasons > THIN_HISTORY_SEASONAL_DC_MAX_POSITIVE_SEASONS
    ):
        return result

    result["applied"] = True
    result["reason"] = (
        f"the DC only has {non_zero_points} non-zero in-season month"
        f"{'' if non_zero_points == 1 else 's'} across {positive_seasons} positive selling season"
        f"{'' if positive_seasons == 1 else 's'}, so the mean falls back from the active-month average of {active_mean:.1f} "
        f"to the inclusive seasonal average of {inclusive_mean:.1f}"
    )
    return result


def _highest_outlier_explanation_text(record: dict[str, object]) -> str:
    if not bool(record.get("highest_outlier_removed")):
        return ""

    threshold_pct = max(_mac_amount(record.get("highest_outlier_threshold_pct")), 100.0)
    parts: list[str] = []

    if bool(record.get("highest_outlier_removed_from_mean")):
        removed_label = str(record.get("highest_outlier_removed_month_mean") or "the highest scoped month")
        removed_value = _mac_amount(record.get("highest_outlier_removed_value_mean"))
        baseline_value = _mac_amount(record.get("highest_outlier_baseline_value_mean"))
        ratio_pct = _mac_amount(record.get("highest_outlier_trigger_pct_mean"))
        parts.append(
            f"{removed_label} at {removed_value:.1f} was {ratio_pct:.0f}% of the remaining non-zero baseline of {baseline_value:.1f}, above the {threshold_pct:.0f}% threshold, so it was reset to {baseline_value:.1f} for the mean input"
        )

    if bool(record.get("highest_outlier_removed_from_std")):
        std_label = str(record.get("highest_outlier_removed_month_std") or "the highest scoped month")
        std_value = _mac_amount(record.get("highest_outlier_removed_value_std"))
        same_as_mean = (
            bool(record.get("highest_outlier_removed_from_mean"))
            and std_label == str(record.get("highest_outlier_removed_month_mean") or "")
            and abs(std_value - _mac_amount(record.get("highest_outlier_removed_value_mean"))) < 0.001
        )
        if same_as_mean:
            parts.append("the same month was also reset to that standard-month baseline for the variability input")
        else:
            std_baseline = _mac_amount(record.get("highest_outlier_baseline_value_std"))
            std_ratio_pct = _mac_amount(record.get("highest_outlier_trigger_pct_std"))
            parts.append(
                f"{std_label} at {std_value:.1f} was {std_ratio_pct:.0f}% of the remaining non-zero baseline of {std_baseline:.1f}, above the {threshold_pct:.0f}% threshold, so it was reset to {std_baseline:.1f} for the variability input"
            )

    if not parts:
        return ""
    return " Highest-month outlier filter is active because " + ". ".join(parts) + "."


def _seasonal_ramp_explanation_text(record: dict[str, object]) -> str:
    if not bool(record.get("seasonal_ramp_applied")):
        return ""

    return (
        " Current replenishment-window seasonality is active because "
        f"{str(record.get('seasonal_ramp_reason') or '').strip()} "
        f"The next protected window starts {str(record.get('seasonal_ramp_start_date') or '').strip()} and spans "
        f"{str(record.get('seasonal_ramp_window') or '').strip()}. "
        f"That forward window averages {float(record.get('seasonal_ramp_window_average', 0.0)):.1f} units per month versus "
        f"{float(record.get('seasonal_ramp_full_season_average', 0.0)):.1f} across the full season, so the demand basis is scaled by "
        f"{float(record.get('seasonal_ramp_factor', 1.0)):.2f}x."
    )


def _evaluate_dc_sparse_active_mean_fallback(
    primary: dict[str, object],
    others: list[dict[str, object]],
) -> dict[str, object]:
    result = {
        "applied": False,
        "non_zero_points": 0,
        "inclusive_mean": 0.0,
        "active_mean": 0.0,
        "pooled_input": 0.0,
        "reason": "",
    }
    if (
        not bool(primary.get("dc_location_reserve_rule_applied"))
        or bool(primary.get("forecast_used"))
        or str(primary.get("method_key", "") or "") != INTERMITTENT_BRANCH_METHOD_KEY
    ):
        return result

    pooled_input = sum(
        max(float(record.get("variability_pooled_to_dc", 0.0) or 0.0), 0.0)
        + max(float(record.get("direct_transfer_pooled_to_dc", 0.0) or 0.0), 0.0)
        for record in others
    )
    result["pooled_input"] = pooled_input
    if pooled_input > 0.0001:
        return result

    scoped_labels = [label.strip() for label in str(primary.get("mean_month_scope", "") or "").split(",") if label.strip()]
    if not scoped_labels:
        return result

    scoped_values = [_calculation_month_value(primary.get(label)) for label in scoped_labels]
    non_zero_points = sum(1 for value in scoped_values if value > 0)
    inclusive_mean = _average(scoped_values, include_zeros=True)
    active_mean = _average(scoped_values, include_zeros=False)
    result["non_zero_points"] = non_zero_points
    result["inclusive_mean"] = inclusive_mean
    result["active_mean"] = active_mean

    if (
        non_zero_points == 0
        or non_zero_points > DC_SPARSE_ACTIVE_MEAN_MAX_NON_ZERO_POINTS
        or inclusive_mean <= 0
        or active_mean <= inclusive_mean
    ):
        return result

    result["applied"] = True
    result["reason"] = (
        f"the DC only has {non_zero_points} non-zero scoped month"
        f"{'' if non_zero_points == 1 else 's'} and no pooled branch stock is creating the DC recommendation, "
        f"so the mean falls back from the active-month average of {active_mean:.1f} to the inclusive scoped average of {inclusive_mean:.1f}"
    )
    return result


def _apply_dc_sparse_active_mean_fallback(primary: dict[str, object], fallback: dict[str, object]) -> None:
    if not bool(fallback.get("applied")):
        return

    method = METHOD_LOOKUP.get(str(primary.get("method_key", "") or ""), METHODS[0])
    inclusive_mean = float(fallback.get("inclusive_mean", 0.0) or 0.0)
    seasonal_factor = float(primary.get("seasonal_ramp_factor", 1.0) or 1.0)
    trend_factor = 1.0 if bool(primary.get("forecast_used")) else float(primary.get("product_group_trend_factor", 1.0) or 1.0)
    filtered_std = float(primary.get("filtered_std_dev", 0.0) or 0.0)
    lead_time_days = float(primary.get("lead_time_days", 0.0) or 0.0)
    protection_days = float(primary.get("protection_days", 0.0) or 0.0)
    service_z_score = float(primary.get("service_z_score", 0.0) or 0.0)

    raw_filtered_mean = inclusive_mean
    pre_phase_filtered_mean = inclusive_mean
    filtered_mean = inclusive_mean * seasonal_factor
    raw_trend_adjusted_mean = raw_filtered_mean * trend_factor
    pre_phase_trend_adjusted_mean = pre_phase_filtered_mean * trend_factor
    trend_adjusted_mean = filtered_mean * trend_factor
    rounded_mean = _round_value(trend_adjusted_mean, method.rounding_mode)
    raw_rounded_mean = _round_value(pre_phase_trend_adjusted_mean, method.rounding_mode)
    delta = trend_adjusted_mean - rounded_mean
    total_dev = delta + filtered_std
    daily_demand = trend_adjusted_mean / DAYS_PER_MONTH if DAYS_PER_MONTH else 0.0
    lead_time_demand = daily_demand * lead_time_days
    cycle_demand = daily_demand * max(protection_days - lead_time_days, 0.0)
    protected_cycle_demand = lead_time_demand + cycle_demand
    lead_time_std = filtered_std * math.sqrt(lead_time_days / DAYS_PER_MONTH) if lead_time_days > 0 else 0.0
    protection_std = filtered_std * math.sqrt(protection_days / DAYS_PER_MONTH) if protection_days > 0 else 0.0
    demand_only_min_amount = math.ceil(max(lead_time_demand, 0.0))
    service_level_min_amount = math.ceil(max(lead_time_demand + (service_z_score * lead_time_std), 0.0))
    dc_transfer_reserve_amount = math.ceil(max(protected_cycle_demand, 0.0))
    demand_only_order_up_to = math.ceil(max(protected_cycle_demand, demand_only_min_amount))
    service_level_order_up_to = math.ceil(
        max(protected_cycle_demand + (service_z_score * protection_std), service_level_min_amount)
    )

    primary.update(
        {
            "raw_filtered_mean": raw_filtered_mean,
            "pre_phase_filtered_mean": pre_phase_filtered_mean,
            "filtered_mean": filtered_mean,
            "raw_trend_adjusted_mean": raw_trend_adjusted_mean,
            "pre_phase_trend_adjusted_mean": pre_phase_trend_adjusted_mean,
            "trend_adjusted_mean": trend_adjusted_mean,
            "rounded_mean": rounded_mean,
            "raw_rounded_mean": raw_rounded_mean,
            "delta": delta,
            "total_dev": total_dev,
            "daily_demand": daily_demand,
            "lead_time_demand": lead_time_demand,
            "cycle_demand": cycle_demand,
            "protected_cycle_demand": protected_cycle_demand,
            "lead_time_std": lead_time_std,
            "protection_std": protection_std,
            "demand_only_min_amount": demand_only_min_amount,
            "service_level_min_amount": service_level_min_amount,
            "dc_transfer_reserve_amount": dc_transfer_reserve_amount,
            "demand_only_order_up_to": demand_only_order_up_to,
            "service_level_order_up_to": service_level_order_up_to,
            "recommended_min_amount": dc_transfer_reserve_amount,
            "policy_order_up_to": service_level_order_up_to,
            "dc_sparse_active_mean_fallback_applied": True,
            "dc_sparse_active_mean_fallback_non_zero_points": int(fallback.get("non_zero_points", 0) or 0),
            "dc_sparse_active_mean_fallback_inclusive_mean": inclusive_mean,
            "dc_sparse_active_mean_fallback_active_mean": float(fallback.get("active_mean", 0.0) or 0.0),
            "dc_sparse_active_mean_fallback_reason": str(fallback.get("reason", "") or ""),
        }
    )


def _finalize_group_records(
    records: list[dict[str, object]],
    cheap_local_deviation_threshold: float = 1.0,
) -> list[dict[str, object]]:
    if not records:
        return records

    supplier_policy = _supplier_inventory_policy(records[0].get("supplier"))
    designated_dc_location = str(supplier_policy["dc_location"] or "").strip()
    hub_managed = bool(supplier_policy["hub_managed"])
    if hub_managed and designated_dc_location:
        dc_index = next(
            (
                index
                for index, record in enumerate(records)
                if str(record.get("location", "")).strip() == designated_dc_location
            ),
            None,
        )
        if dc_index not in (None, 0):
            records = [records[dc_index], *records[:dc_index], *records[dc_index + 1 :]]

    primary = records[0]
    others = records[1:]
    cheap_local_deviation_threshold = max(float(cheap_local_deviation_threshold), 0.0)
    summary_labels = _summary_month_labels(primary)
    recent_12_labels = _recent_month_labels(primary, 12)
    company_scoped_month_totals = {
        label: sum(_calculation_month_value(record.get(label)) for record in records)
        for label in summary_labels
    }
    company_recent_12_month_totals = {
        label: sum(_calculation_month_value(record.get(label)) for record in records)
        for label in recent_12_labels
    }
    company_usage_periods = sum(1 for total in company_scoped_month_totals.values() if total > 0)
    company_scoped_usage_total = sum(float(total) for total in company_scoped_month_totals.values())
    company_recent_12_usage_periods = sum(1 for total in company_recent_12_month_totals.values() if total > 0)
    company_recent_12_usage_total = sum(float(total) for total in company_recent_12_month_totals.values())
    stocked_location_count = sum(1 for record in records if float(record.get("current_max", 0.0)) > 0)
    branch_stock_gate_passed = (
        company_recent_12_usage_periods >= NEW_BRANCH_STOCK_MIN_USAGE_PERIODS
        and stocked_location_count >= NEW_BRANCH_STOCK_MIN_EXISTING_STOCK_LOCATIONS
    )

    for record in records:
        record["supplier_hub_managed"] = hub_managed
        record["designated_dc_location"] = designated_dc_location
        record["low_cost_local_deviation_threshold"] = cheap_local_deviation_threshold
        record["low_cost_local_deviation_applied"] = False
        record["low_cost_local_deviation_kept_amount"] = 0.0
        record["dc_pooling_zero_max_alert"] = False
        record["branch_zero_max_recommendation_alert"] = False
        record["regional_zero_max_branch_pool_applied"] = False
        record["regional_sparse_pool_suppressed"] = False
        record["dc_sparse_active_mean_fallback_applied"] = False
        record["dc_sparse_active_mean_fallback_non_zero_points"] = 0
        record["dc_sparse_active_mean_fallback_inclusive_mean"] = 0.0
        record["dc_sparse_active_mean_fallback_active_mean"] = 0.0
        record["dc_sparse_active_mean_fallback_reason"] = ""
        record["branch_stock_gate_company_usage_periods"] = company_usage_periods
        record["branch_stock_gate_company_scoped_usage_total"] = company_scoped_usage_total
        record["branch_stock_gate_recent_12_usage_periods"] = company_recent_12_usage_periods
        record["branch_stock_gate_recent_12_usage_total"] = company_recent_12_usage_total
        record["branch_stock_gate_stocked_locations"] = stocked_location_count
        record["branch_stock_gate_passed"] = branch_stock_gate_passed
        record["single_stocked_branch_hold_applied"] = False
        record["single_stocked_branch_hold_location"] = ""
        record["non_stockable_location_blocked"] = False
        record["branch_stock_gate_blocked"] = False
        record["primary_stock_gate_blocked"] = False
        record["project_spike_suppressed"] = False
        record["single_period_pool_guard_applied"] = False
        record["single_period_pool_guard_reason"] = ""
        record["project_spike_top_month_label"] = ""
        record["project_spike_top_month_value"] = 0.0
        record["project_spike_branch_recent_12_non_zero_months"] = 0
        record["project_spike_branch_recent_12_total"] = 0.0
        record["project_spike_company_recent_12_total"] = 0.0
        record["project_spike_branch_top_month_share_pct"] = 0.0
        record["project_spike_company_top_month_share_pct"] = 0.0
        record["project_spike_next_company_month_value"] = 0.0
        record["project_spike_company_month_multiple"] = 0.0
        record["project_spike_top_month_vs_current_max"] = 0.0
        record["project_spike_reason"] = ""

    branch_candidates = others if hub_managed else records
    stocked_non_dc_records = [
        record
        for record in branch_candidates
        if float(record.get("current_max", 0.0)) > 0
    ]
    single_stocked_branch_hold = (
        hub_managed
        and not _status_contains_regional(primary.get("status"))
        and float(primary.get("current_max", 0.0)) <= 0
        and len(stocked_non_dc_records) == 1
    )
    single_stocked_branch_location = (
        str(stocked_non_dc_records[0].get("location", "")).strip()
        if single_stocked_branch_hold and stocked_non_dc_records
        else ""
    )
    if single_stocked_branch_hold:
        for record in records:
            record["single_stocked_branch_hold_applied"] = True
            record["single_stocked_branch_hold_location"] = single_stocked_branch_location

    for record in branch_candidates:
        project_spike = _detect_project_spike_suppression(
            record,
            recent_12_labels,
            company_recent_12_month_totals,
        )
        record["project_spike_suppressed"] = bool(project_spike["applied"])
        record["project_spike_top_month_label"] = str(project_spike["top_month_label"])
        record["project_spike_top_month_value"] = float(project_spike["top_month_value"])
        record["project_spike_branch_recent_12_non_zero_months"] = int(project_spike["branch_recent_12_non_zero_months"])
        record["project_spike_branch_recent_12_total"] = float(project_spike["branch_recent_12_total"])
        record["project_spike_company_recent_12_total"] = float(project_spike["company_recent_12_total"])
        record["project_spike_branch_top_month_share_pct"] = float(project_spike["branch_top_month_share_pct"])
        record["project_spike_company_top_month_share_pct"] = float(project_spike["company_top_month_share_pct"])
        record["project_spike_next_company_month_value"] = float(project_spike["next_company_month_value"])
        record["project_spike_company_month_multiple"] = float(project_spike["company_month_multiple"])
        record["project_spike_top_month_vs_current_max"] = float(project_spike["top_month_vs_current_max"])
        record["project_spike_reason"] = str(project_spike["reason"])
        if bool(project_spike["applied"]):
            _apply_project_spike_suppression(record)
        base_recommendation = float(
            record.get("base_branch_recommendation", _location_rule(record["current_max"], record["rounded_mean"]))
        )
        branch_demand_recommendation = float(
            record.get(
                "branch_demand_recommendation",
                max(
                    base_recommendation,
                    float(record["policy_order_up_to"]),
                    float(record["recommended_min_amount"]),
                ),
            )
        )
        service_level_recommendation = float(
            record.get(
                "service_level_recommendation",
                max(
                    base_recommendation,
                    float(record["service_level_order_up_to"]),
                    float(record["service_level_min_amount"]),
                ),
            )
        )
        intermittent_spike_pooled_to_dc = float(record.get("intermittent_spike_pooled_to_dc", 0.0))
        preliminary_deviation_pool = float(
            record.get(
                "preliminary_deviation_pool",
                max(service_level_recommendation - branch_demand_recommendation, 0.0),
            )
        )
        regional_zero_max_branch_pool = (
            not record["dc_location_reserve_rule_applied"]
            and float(record.get("current_max", 0.0)) <= 0
            and _status_contains_regional(record.get("status"))
        )
        suppress_sparse_regional_pool = (
            hub_managed
            and not regional_zero_max_branch_pool
            and not record["dc_location_reserve_rule_applied"]
            and _status_contains_regional(record.get("status"))
            and (
                (
                    bool(record.get("intermittent_branch_protection_applied"))
                    and int(record.get("intermittent_non_zero_months", 0)) <= SPARSE_REGIONAL_POOL_MAX_BRANCH_NON_ZERO_PERIODS
                )
                or int(record.get("project_spike_branch_recent_12_non_zero_months", 0)) <= SPARSE_REGIONAL_POOL_MAX_BRANCH_NON_ZERO_PERIODS
            )
        )
        single_period_pool_guard = (
            hub_managed
            and not regional_zero_max_branch_pool
            and not record["dc_location_reserve_rule_applied"]
            and not _status_contains_regional(record.get("status"))
            and not bool(record.get("project_spike_suppressed"))
            and int(record.get("intermittent_non_zero_months", 0)) <= SINGLE_PERIOD_POOL_GUARD_MAX_BRANCH_NON_ZERO_PERIODS
            and not branch_stock_gate_passed
            and (
                preliminary_deviation_pool > 0
                or intermittent_spike_pooled_to_dc > 0
                or (float(record.get("current_max", 0.0)) <= 0 and branch_demand_recommendation > 0)
            )
        )
        if single_period_pool_guard:
            record["single_period_pool_guard_applied"] = True
            record["single_period_pool_guard_reason"] = (
                f"this branch only has {int(record.get('intermittent_non_zero_months', 0))} non-zero scoped month"
                f"{'' if int(record.get('intermittent_non_zero_months', 0)) == 1 else 's'}, while the item only sold in "
                f"{company_recent_12_usage_periods} company month{'s' if company_recent_12_usage_periods != 1 else ''} over the last 12 months "
                f"and is currently stocked in {stocked_location_count} location{'s' if stocked_location_count != 1 else ''}"
            )
        keep_deviation_local = (
            not record["dc_location_reserve_rule_applied"]
            and not regional_zero_max_branch_pool
            and (
                (not hub_managed)
                or (
                    single_stocked_branch_hold
                    and str(record.get("location", "")).strip() == single_stocked_branch_location
                )
                or _mac_amount(record.get("mac")) < cheap_local_deviation_threshold
            )
            and (preliminary_deviation_pool > 0 or intermittent_spike_pooled_to_dc > 0)
        )
        localized_deviation_kept_amount = 0.0
        if regional_zero_max_branch_pool:
            record["recommended_new_max"] = 0.0
            record["recommended_min_amount"] = 0.0
            record["regional_zero_max_branch_pool_applied"] = True
        elif keep_deviation_local:
            localized_deviation_kept_amount = preliminary_deviation_pool + intermittent_spike_pooled_to_dc
            record["recommended_new_max"] = math.ceil(branch_demand_recommendation + localized_deviation_kept_amount)
            record["low_cost_local_deviation_applied"] = not hub_managed
            if _mac_amount(record.get("mac")) < cheap_local_deviation_threshold:
                record["low_cost_local_deviation_applied"] = True
            record["low_cost_local_deviation_kept_amount"] = localized_deviation_kept_amount
        else:
            record["recommended_new_max"] = branch_demand_recommendation
        if not record["dc_location_reserve_rule_applied"]:
            record["variability_pooled_to_dc"] = (
                0.0
                if (
                    keep_deviation_local
                    or not hub_managed
                    or suppress_sparse_regional_pool
                    or single_period_pool_guard
                    or single_stocked_branch_hold
                )
                else preliminary_deviation_pool
            )
            record["direct_transfer_pooled_to_dc"] = (
                0.0
                if (
                    keep_deviation_local
                    or not hub_managed
                    or suppress_sparse_regional_pool
                    or single_period_pool_guard
                    or single_stocked_branch_hold
                )
                else intermittent_spike_pooled_to_dc
            )
            _sync_branch_dc_pool(record)
        else:
            record["variability_pooled_to_dc"] = 0.0
            record["direct_transfer_pooled_to_dc"] = 0.0
            _sync_branch_dc_pool(record)
        record["recommendation_explanation"] = (
            "Branch targets use the effective demand signal as a base, then floor the result to demand-only coverage for lead time and supplier frequency."
        )
        if record["forecast_used"]:
            record["recommendation_explanation"] += (
                " AutoGluon forecast demand is being used as the monthly demand input before the stocking rules are applied."
            )
        elif record["product_group_trend_label"] != "Flat":
            record["recommendation_explanation"] += (
                f" Product-group trend signal is {record['product_group_trend_label'].lower()} from {record['product_group_trend_source'].lower()}, "
                f"so the item mean is adjusted by {float(record['product_group_trend_factor']):.2f} before rounding."
            )
        record["recommendation_explanation"] += (
            f" The year-over-year reference rule selected {int(record['reference_window_months'])} months because the item trend is "
            f"{float(record['yoy_change_pct']):.1f}%."
        )
        if bool(record.get("thin_history_seasonal_dc_mean_fallback_applied")):
            record["recommendation_explanation"] += (
                f" Thin-history seasonal DC fallback is active because {str(record.get('thin_history_seasonal_dc_reason') or '').strip()}."
            )
        if int(record.get("negative_usage_netted_months", 0)) > 0:
            unmatched_units = float(record.get("negative_usage_unmatched_units", 0.0))
            record["recommendation_explanation"] += (
                f" Negative monthly usage or return activity totaling {float(record.get('negative_usage_netted_units', 0.0)):.1f} units "
                f"across {int(record.get('negative_usage_netted_months', 0))} month(s) was netted backward against the closest earlier positive month(s) within "
                f"{RETURN_NETTING_MAX_LOOKBACK_MONTHS} months so returns do not create replenishment demand or DC pooling."
                + (
                    f" {unmatched_units:.1f} units had no earlier positive month to net against and were dropped from replenishment math."
                    if unmatched_units > 0
                    else ""
                )
            )
        record["recommendation_explanation"] += _highest_outlier_explanation_text(record)
        record["recommendation_explanation"] += _seasonal_ramp_explanation_text(record)
        if bool(record.get("two_point_spike_normalized")):
            record["recommendation_explanation"] += (
                f" Two-point intermittent spike normalization is active because "
                f"{str(record.get('two_point_spike_normalized_month_mean') or 'the top scoped month')} at "
                f"{float(record.get('two_point_spike_normalized_value_mean', 0.0)):.1f} units was "
                f"{float(record.get('two_point_spike_normalized_ratio_mean', 0.0)):.1f}x the second active month of "
                f"{float(record.get('two_point_spike_normalized_baseline_value_mean', 0.0)):.1f}. "
                f"It was reset to {float(record.get('two_point_spike_normalized_baseline_value_mean', 0.0)):.1f} for the scoped calculation inputs before branch variability was evaluated."
            )
        if bool(record.get("project_spike_suppressed")):
            record["recommendation_explanation"] += (
                f" Non-replenishment project spike suppression is active because {str(record.get('project_spike_reason') or '').strip()} "
                "That usage is excluded from both branch and DC replenishment recommendations."
            )
        elif bool(record.get("intermittent_branch_protection_applied")):
            intermittent_destination = (
                "the extra spike coverage stays at this branch because the item is below the MAC cutoff"
                if bool(record["low_cost_local_deviation_applied"])
                else "only the variability portion is pooled to the DC because no explicit spike rule fired"
                if bool(record.get("intermittent_direct_transfer_suppressed"))
                else "the excess spike coverage is pooled to the DC"
                if not regional_zero_max_branch_pool
                else "the branch stays non-stocked and the spike is pooled to the DC"
            )
            record["recommendation_explanation"] += (
                f" Intermittent branch protection is active because {record.get('intermittent_reason', 'the branch demand was sparse and spike-heavy')}. "
                f"The active-demand mean is reduced from {float(record.get('raw_trend_adjusted_mean', record['trend_adjusted_mean'])):.1f} to "
                f"{float(record['trend_adjusted_mean']):.1f}, and {intermittent_destination}."
            )
        if regional_zero_max_branch_pool:
            record["recommendation_explanation"] += (
                " This branch currently has a max of 0 and the status contains Regional, so the branch remains non-stocked. Its usage signal is intentionally pooled to the DC instead of creating a branch max."
            )
        elif suppress_sparse_regional_pool:
            record["regional_sparse_pool_suppressed"] = True
            record["recommendation_explanation"] += (
                f" This is a sparse regional branch signal, so its deviation is not pooled to the DC. The item only has {company_recent_12_usage_periods} active company month"
                f"{'' if company_recent_12_usage_periods == 1 else 's'} over the last 12 months, with just {int(record.get('intermittent_non_zero_months', 0))} non-zero scoped period"
                f"{'' if int(record.get('intermittent_non_zero_months', 0)) == 1 else 's'} at this branch."
            )
        elif bool(record.get("single_period_pool_guard_applied")):
            record["recommendation_explanation"] += (
                f" Single-period pooling guard is active because {str(record.get('single_period_pool_guard_reason') or '').strip()}. "
                "That thin branch signal can influence the local branch floor, but it is not allowed to create pooled DC stock until the item shows repeat proof."
            )
        elif single_stocked_branch_hold:
            if str(record.get("location", "")).strip() == single_stocked_branch_location:
                record["recommendation_explanation"] += (
                    f" This item is only currently stocked at location {single_stocked_branch_location} outside the DC, so that location keeps its own local need and does not create pooled DC stock."
                )
            else:
                record["recommendation_explanation"] += (
                    f" This item is only currently stocked at location {single_stocked_branch_location} outside the DC, so this location cannot create pooled DC stock for it."
                )
        elif not hub_managed:
            record["recommendation_explanation"] += (
                f" Supplier policy marks {str(record.get('supplier') or '').strip()} as non-hub-managed, so local variability stays at the stocking location instead of being pooled to a DC."
            )
        if bool(record["low_cost_local_deviation_applied"]):
            if hub_managed and _mac_amount(record.get("mac")) < cheap_local_deviation_threshold:
                record["recommendation_explanation"] += (
                    f" This row has MAC {float(record.get('mac', 0.0)):.2f}, which is below the local-deviation cutoff of "
                    f"{cheap_local_deviation_threshold:.2f}, so {float(record['low_cost_local_deviation_kept_amount']):.1f} units of deviation are kept at this branch instead of being sent to the DC."
                )
            elif not hub_managed:
                record["recommendation_explanation"] += (
                    f" Because this supplier is not hub-managed, {float(record['low_cost_local_deviation_kept_amount']):.1f} units of variability stay local instead of being sent to a DC."
                )
        if float(record["deviation_pooled_to_dc"]) > 0:
            record["recommendation_explanation"] += (
                " Local variability is not kept at the branch. The variability portion is pooled into the DC using a pooled-variance approach, and any direct spike-transfer units are added on top of that instead of being stacked branch by branch."
            )
        if record["override_flag"]:
            record["recommended_new_max"] = float(record["current_max"])
            record["variability_pooled_to_dc"] = 0.0
            record["direct_transfer_pooled_to_dc"] = 0.0
            _sync_branch_dc_pool(record)
            record["recommended_min_amount"] = min(float(record["recommended_min_amount"]), float(record["recommended_new_max"]))
            record["recommendation_explanation"] = (
                "Manual override is active, so the recommended max is locked to the current max. Use the override details to review who set it and when."
            )
        _apply_supplier_min_amount_floor(record)
        if bool(record.get("supplier_min_amount_floor_applied")):
            record["recommendation_explanation"] += (
                f" Supplier minimum amount is {float(record['supplier_min_amount_floor']):.0f}, so the final max is floored up to at least that value."
            )
        non_stockable_location_blocked = (
            not record["dc_location_reserve_rule_applied"]
            and float(record.get("current_max", 0.0)) <= 0
            and not _is_yes(record.get("stockable"))
            and float(record.get("recommended_new_max", 0.0)) > 0
        )
        if non_stockable_location_blocked:
            record["non_stockable_location_blocked"] = True
            record["recommended_new_max"] = 0.0
            record["recommended_min_amount"] = 0.0
            record["variability_pooled_to_dc"] = 0.0
            record["direct_transfer_pooled_to_dc"] = 0.0
            _sync_branch_dc_pool(record)
            record["recommendation_explanation"] += (
                " This location is marked as not stockable, so it cannot seed a new branch max or create DC pooling."
            )
        branch_stock_gate_blocked = (
            not record["dc_location_reserve_rule_applied"]
            and float(record.get("current_max", 0.0)) <= 0
            and float(record.get("recommended_new_max", 0.0)) > 0
            and not branch_stock_gate_passed
        )
        if branch_stock_gate_blocked:
            removed_branch_stock = float(record.get("recommended_new_max", 0.0))
            record["branch_stock_gate_blocked"] = True
            record["recommended_new_max"] = 0.0
            record["recommended_min_amount"] = 0.0
            if hub_managed:
                if (
                    bool(record.get("single_period_pool_guard_applied"))
                    or bool(record.get("non_stockable_location_blocked"))
                    or single_stocked_branch_hold
                ):
                    record["variability_pooled_to_dc"] = 0.0
                    record["direct_transfer_pooled_to_dc"] = 0.0
                    _sync_branch_dc_pool(record)
                else:
                    _add_branch_direct_transfer(record, removed_branch_stock)
            else:
                record["variability_pooled_to_dc"] = 0.0
                record["direct_transfer_pooled_to_dc"] = 0.0
                _sync_branch_dc_pool(record)
            record["recommendation_explanation"] += (
                f" New branch stock is blocked because the item only sold in {company_recent_12_usage_periods} months across the last 12 months and "
                f"{stocked_location_count} locations currently stock it. A new stocking location must show more than 2 selling months in the last 12 months "
                f"and at least {NEW_BRANCH_STOCK_MIN_EXISTING_STOCK_LOCATIONS} stocked locations before the model creates a new stocking branch."
            )
            if bool(record.get("single_period_pool_guard_applied")):
                record["recommendation_explanation"] += (
                    " Because the branch only has a single scoped selling month and the item still lacks repeat proof, that blocked branch stock is also prevented from rolling into the DC."
                )
            elif single_stocked_branch_hold:
                record["recommendation_explanation"] += (
                    f" Because this item is only currently stocked at location {single_stocked_branch_location}, blocked new-branch stock is prevented from rolling into the DC."
                )
        record["branch_zero_max_recommendation_alert"] = (
            not record["dc_location_reserve_rule_applied"]
            and float(record.get("current_max", 0.0)) <= 0
            and float(record.get("recommended_new_max", 0.0)) > 0
        )
        if bool(record["branch_zero_max_recommendation_alert"]):
            record["recommendation_explanation"] += (
                " This branch currently has a max of 0, but the model is recommending a positive branch max here, so the row should be reviewed."
            )

    if not hub_managed:
        for record in records:
            record["pooled_variance_absorbed_by_dc"] = 0.0
            record["pooled_direct_transfer_absorbed_by_dc"] = 0.0
            record["deviation_absorbed_by_dc"] = 0.0
            record["dc_pooling_zero_max_alert"] = False
            record["is_balancing_location"] = False
            record["recommendation_delta"] = float(record["recommended_new_max"]) - float(record["current_max"])
            record["recommended_min_delta"] = float(record["recommended_min_amount"]) - float(record["min_value"])
        return records

    dc_sparse_active_mean_fallback = _evaluate_dc_sparse_active_mean_fallback(primary, others)
    if bool(dc_sparse_active_mean_fallback["applied"]):
        _apply_dc_sparse_active_mean_fallback(primary, dc_sparse_active_mean_fallback)

    _recompute_primary_dc_absorption(records)
    pooled_branch_deviation = float(primary.get("deviation_absorbed_by_dc", 0.0))
    max_total_dev = max(float(record["total_dev"]) for record in records)
    balancing_recommendation = max(
        float(primary["rounded_mean"])
        + (
            sum(float(record["rounded_mean"]) for record in others)
            - sum(float(record["recommended_new_max"]) for record in others)
        )
        + math.ceil(max_total_dev)
        + math.ceil(pooled_branch_deviation),
        1,
    )
    primary["recommended_new_max"] = max(
        balancing_recommendation,
        float(primary["policy_order_up_to"]),
        float(primary["recommended_min_amount"]),
    )
    primary["is_balancing_location"] = True
    primary["recommendation_explanation"] = (
        "Balancing location takes the effective demand balancing result, then floors it to the policy order-up-to level driven by lead time, supplier frequency, and ABC service level."
    )
    if primary["forecast_used"]:
        primary["recommendation_explanation"] += (
            " AutoGluon forecast demand is being used as the monthly demand input before the stocking rules are applied."
        )
    elif primary["product_group_trend_label"] != "Flat":
        primary["recommendation_explanation"] += (
            f" Product-group trend signal is {primary['product_group_trend_label'].lower()} from {primary['product_group_trend_source'].lower()}, "
            f"so the item mean is adjusted by {float(primary['product_group_trend_factor']):.2f} before rounding."
        )
    primary["recommendation_explanation"] += (
        f" The year-over-year reference rule selected {int(primary['reference_window_months'])} months because the item trend is "
        f"{float(primary['yoy_change_pct']):.1f}%."
    )
    if bool(primary.get("thin_history_seasonal_dc_mean_fallback_applied")):
        primary["recommendation_explanation"] += (
            f" Thin-history seasonal DC fallback is active because {str(primary.get('thin_history_seasonal_dc_reason') or '').strip()}."
        )
    if bool(primary.get("dc_sparse_active_mean_fallback_applied")):
        primary["recommendation_explanation"] += (
            f" DC sparse active-mean fallback is active because {str(primary.get('dc_sparse_active_mean_fallback_reason') or '').strip()}."
        )
    if int(primary.get("negative_usage_netted_months", 0)) > 0:
        unmatched_units = float(primary.get("negative_usage_unmatched_units", 0.0))
        primary["recommendation_explanation"] += (
            f" Negative monthly usage or return activity totaling {float(primary.get('negative_usage_netted_units', 0.0)):.1f} units "
            f"across {int(primary.get('negative_usage_netted_months', 0))} month(s) was netted backward against the closest earlier positive month(s) within "
            f"{RETURN_NETTING_MAX_LOOKBACK_MONTHS} months so returns do not create replenishment demand or DC pooling."
            + (
                f" {unmatched_units:.1f} units had no earlier positive month to net against and were dropped from replenishment math."
                if unmatched_units > 0
                else ""
            )
        )
    primary["recommendation_explanation"] += _highest_outlier_explanation_text(primary)
    primary["recommendation_explanation"] += _seasonal_ramp_explanation_text(primary)
    if bool(primary.get("two_point_spike_normalized")):
        primary["recommendation_explanation"] += (
            f" Two-point intermittent spike normalization is active because "
            f"{str(primary.get('two_point_spike_normalized_month_mean') or 'the top scoped month')} at "
            f"{float(primary.get('two_point_spike_normalized_value_mean', 0.0)):.1f} units was "
            f"{float(primary.get('two_point_spike_normalized_ratio_mean', 0.0)):.1f}x the second active month of "
            f"{float(primary.get('two_point_spike_normalized_baseline_value_mean', 0.0)):.1f}."
        )
    if primary["dc_location_reserve_rule_applied"]:
        primary["recommendation_explanation"] += (
            f" Location {primary.get('location')} is treated as the DC for this supplier, so its min only covers that location's own demand across the protected cycle."
        )
    if single_stocked_branch_hold:
        primary["recommended_new_max"] = 0.0
        primary["recommended_min_amount"] = 0.0
        primary["pooled_variance_absorbed_by_dc"] = 0.0
        primary["pooled_direct_transfer_absorbed_by_dc"] = 0.0
        primary["deviation_absorbed_by_dc"] = 0.0
        primary["recommendation_explanation"] += (
            f" This item is only currently stocked at location {single_stocked_branch_location} outside the DC, and the status is not Regional, so the DC is held at zero and the stocked branch keeps its own need locally."
        )
    if float(primary["deviation_absorbed_by_dc"]) > 0:
        primary["recommendation_explanation"] += (
            f" Branch protection adds {float(primary.get('pooled_variance_absorbed_by_dc', 0.0)):.1f} units of pooled variance "
            f"(root-sum-square across branches) plus {float(primary.get('pooled_direct_transfer_absorbed_by_dc', 0.0)):.1f} units of direct spike or transfer stock, "
            f"for {float(primary['deviation_absorbed_by_dc']):.1f} total pooled units in this balancing/DC recommendation."
        )
    if primary["override_flag"]:
        primary["recommended_new_max"] = float(primary["current_max"])
        primary["recommended_min_amount"] = min(float(primary["recommended_min_amount"]), float(primary["recommended_new_max"]))
        primary["recommendation_explanation"] = (
            "Manual override is active, so the recommended max is locked to the current max. Use the override details to review who set it and when."
        )
    _apply_supplier_min_amount_floor(primary)
    if bool(primary.get("supplier_min_amount_floor_applied")):
        primary["recommendation_explanation"] += (
            f" Supplier minimum amount is {float(primary['supplier_min_amount_floor']):.0f}, so the final max is floored up to at least that value."
        )
    primary_stock_gate_blocked = (
        hub_managed
        and float(primary.get("current_max", 0.0)) <= 0
        and float(primary.get("recommended_new_max", 0.0)) > 0
        and float(primary.get("deviation_absorbed_by_dc", 0.0)) <= 0
        and not branch_stock_gate_passed
    )
    if primary_stock_gate_blocked:
        primary["primary_stock_gate_blocked"] = True
        primary["recommended_new_max"] = 0.0
        primary["recommended_min_amount"] = 0.0
        primary["recommendation_explanation"] += (
            f" Location {primary.get('location')} is not being stocked because of DC pooling here, so the new-stock gate also applies to it. "
            f"The item only sold in {company_recent_12_usage_periods} months across the last 12 months and is currently stocked in "
            f"{stocked_location_count} locations. Location {primary.get('location')} can only be suggested as a new stocking point after more than 2 selling months "
            f"in the last 12 months and at least {NEW_BRANCH_STOCK_MIN_EXISTING_STOCK_LOCATIONS} stocked locations."
        )
    primary["dc_pooling_zero_max_alert"] = (
        float(primary.get("current_max", 0.0)) <= 0
        and float(primary.get("deviation_absorbed_by_dc", 0.0)) > 0
        and float(primary.get("recommended_new_max", 0.0)) > 0
    )
    if bool(primary["dc_pooling_zero_max_alert"]):
        primary["recommendation_explanation"] += (
            " The DC currently has no max, but pooled branch protection is creating a positive recommendation here, so this row should be reviewed."
        )

    for record in records:
        record["recommendation_delta"] = float(record["recommended_new_max"]) - float(record["current_max"])
        record["recommended_min_delta"] = float(record["recommended_min_amount"]) - float(record["min_value"])

    return records


def _determine_reference_window(
    ordered: pd.DataFrame,
    monthly_columns: list[str],
) -> dict[str, object]:
    recent_labels = monthly_columns[:12]
    prior_labels = monthly_columns[12:24]

    if not recent_labels:
        return {"months": 12, "yoy_change_pct": 0.0, "rule": "No recent history was available, so the model used a 12-month reference."}

    recent_total = float(ordered[recent_labels].clip(lower=0).sum(numeric_only=True).sum())
    prior_total = float(ordered[prior_labels].clip(lower=0).sum(numeric_only=True).sum()) if prior_labels else 0.0

    if prior_total > 0:
        yoy_change_pct = ((recent_total - prior_total) / prior_total) * 100.0
        stable = -YOY_STABLE_THRESHOLD <= yoy_change_pct <= YOY_STABLE_THRESHOLD
    elif recent_total == 0:
        yoy_change_pct = 0.0
        stable = True
    else:
        yoy_change_pct = 100.0
        stable = False

    if stable and len(prior_labels) == 12:
        return {
            "months": 24,
            "yoy_change_pct": yoy_change_pct,
            "rule": "Year-over-year demand stayed within +/-33%, so both years are used.",
        }

    return {
        "months": 12,
        "yoy_change_pct": yoy_change_pct,
        "rule": "Year-over-year demand moved outside +/-33%, so the model uses the last 12 months.",
    }


def _resolve_replenishment_window_seasonal_ramp(
    reference_labels: list[str],
    reference_values: list[float],
    scoped_labels: list[str],
    scoped_values: list[float],
    base_mean: float,
    seasonality: SeasonalityConfig | None,
    protection_days: float,
    method: MethodConfig,
    forecast_used: bool,
    intermittent_branch_applied: bool,
) -> dict[str, object]:
    non_zero_points = sum(1 for value in scoped_values if float(value) > 0)
    distinct_months = len(
        {
            _month_number(label)
            for label, value in zip(scoped_labels, scoped_values, strict=False)
            if float(value) > 0 and _month_number(label) is not None
        }
    )
    result = {
        "applied": False,
        "factor": 1.0,
        "mode": "Whole season",
        "reason": "",
        "window_label": "",
        "start_date": "",
        "window_average": float(base_mean),
        "full_season_average": float(base_mean),
        "non_zero_points": int(non_zero_points),
        "distinct_months": int(distinct_months),
        "peak_month": "",
    }

    if not seasonality or not seasonality.enabled:
        result["reason"] = "Seasonality is off, so the model uses the whole method window."
        return result
    if forecast_used:
        result["reason"] = "AI forecast is already forward-looking, so the seasonal ramp is skipped."
        return result
    if intermittent_branch_applied:
        result["reason"] = "Sparse or intermittent demand keeps the item on the whole-season view."
        return result
    if not scoped_labels or protection_days <= 0 or base_mean <= 0:
        result["reason"] = "No seasonal baseline was available for a current-window ramp."
        return result
    if non_zero_points < SEASONAL_RAMP_MIN_NON_ZERO_POINTS or distinct_months < SEASONAL_RAMP_MIN_DISTINCT_MONTHS:
        result["reason"] = (
            f"Only {non_zero_points} non-zero in-season points across {distinct_months} distinct months were available, "
            "so the model keeps the whole-season view."
        )
        return result

    month_profile = _build_month_of_year_profile(reference_labels, reference_values)
    if not month_profile:
        result["reason"] = "No monthly seasonal profile could be built from the reference window."
        return result

    start_date = _next_replenishment_window_start(seasonality.planning_season, seasonality.as_of_date)
    segments = _build_forward_window_segments(start_date, protection_days)
    if not segments:
        result["reason"] = "The replenishment window could not be mapped to future months."
        return result

    total_days = sum(segment["days"] for segment in segments)
    if total_days <= 0:
        result["reason"] = "The replenishment window produced no future days to weight."
        return result

    window_average = sum(float(month_profile.get(segment["month"], 0.0)) * float(segment["days"]) for segment in segments) / total_days
    factor = window_average / float(base_mean) if float(base_mean) > 0 else 1.0

    allowed_months = SEASON_MONTHS.get(seasonality.planning_season, set())
    seasonal_month_profile = {month: value for month, value in month_profile.items() if month in allowed_months}
    peak_month = ""
    if seasonal_month_profile:
        peak_month_number = max(seasonal_month_profile, key=seasonal_month_profile.get)
        peak_month = datetime(2000, peak_month_number, 1).strftime("%b")

    result.update(
        {
            "applied": True,
            "factor": float(factor),
            "mode": "Current replenishment window",
            "reason": (
                f"{non_zero_points} non-zero in-season points across {distinct_months} distinct months gave the item enough history "
                "to use a forward seasonal ramp instead of the whole-season average."
            ),
            "window_label": ", ".join(f"{segment['label']} ({int(segment['days'])}d)" for segment in segments),
            "start_date": start_date.isoformat(),
            "window_average": float(window_average),
            "full_season_average": float(base_mean),
            "peak_month": peak_month,
        }
    )
    return result


def _build_month_of_year_profile(labels: list[str], values: list[float]) -> dict[int, float]:
    buckets: dict[int, list[float]] = {}
    for label, value in zip(labels, values, strict=False):
        month_number = _month_number(label)
        if month_number is None:
            continue
        buckets.setdefault(month_number, []).append(float(value))
    return {
        month_number: (sum(month_values) / len(month_values))
        for month_number, month_values in buckets.items()
        if month_values
    }


def _next_replenishment_window_start(planning_season: str, as_of_date: date) -> date:
    allowed_months = SEASON_MONTHS.get(planning_season, set())
    if as_of_date.month in allowed_months:
        return as_of_date
    if planning_season == "Summer":
        target_year = as_of_date.year if as_of_date.month < 4 else as_of_date.year + 1
        return date(target_year, 4, 1)
    if planning_season == "Winter":
        if as_of_date.month < 10:
            return date(as_of_date.year, 10, 1)
        return date(as_of_date.year + 1, 10, 1)
    return as_of_date


def _build_forward_window_segments(start_date: date, protection_days: float) -> list[dict[str, object]]:
    remaining_days = max(int(math.ceil(protection_days)), 1)
    current_date = start_date
    segments: list[dict[str, object]] = []
    while remaining_days > 0:
        month_end_day = calendar.monthrange(current_date.year, current_date.month)[1]
        month_end = date(current_date.year, current_date.month, month_end_day)
        days_in_segment = min((month_end - current_date).days + 1, remaining_days)
        segments.append(
            {
                "month": current_date.month,
                "days": days_in_segment,
                "label": current_date.strftime("%b-%y"),
            }
        )
        remaining_days -= days_in_segment
        current_date = month_end + timedelta(days=1)
    return segments


def _apply_outlier_value_to_reference_window(
    reference_labels: list[str],
    reference_values: list[float],
    outlier_result: dict[str, object],
) -> list[float]:
    adjusted_values = list(reference_values)
    if not bool(outlier_result.get("applied")):
        return adjusted_values
    removed_label = str(outlier_result.get("removed_label") or "")
    baseline_value = float(outlier_result.get("baseline_value", 0.0) or 0.0)
    try:
        reference_index = reference_labels.index(removed_label)
    except ValueError:
        return adjusted_values
    adjusted_values[reference_index] = baseline_value
    return adjusted_values


def _remove_highest_outlier_month(
    labels: list[str],
    values: list[float],
    enabled: bool,
    threshold_pct: float,
) -> dict[str, object]:
    normalized_values = [float(value) for value in values]
    result = {
        "applied": False,
        "values": normalized_values,
        "labels": list(labels),
        "removed_label": "",
        "removed_value": 0.0,
        "baseline_value": 0.0,
        "ratio_pct": 0.0,
        "non_zero_months": sum(1 for value in normalized_values if value > 0),
    }
    if not enabled or len(labels) <= 1:
        return result

    non_zero_entries = [
        (index, labels[index], value)
        for index, value in enumerate(normalized_values)
        if value > 0
    ]
    if len(non_zero_entries) < HIGHEST_OUTLIER_MIN_NON_ZERO_MONTHS:
        return result

    highest_value = max(value for _, _, value in non_zero_entries)
    highest_index = next(index for index, _, value in non_zero_entries if value == highest_value)
    highest_label = labels[highest_index]
    other_non_zero_values = [
        value
        for index, _, value in non_zero_entries
        if index != highest_index
    ]
    if not other_non_zero_values:
        return result

    baseline_value = float(median(other_non_zero_values))
    if baseline_value <= 0:
        return result

    normalized_threshold_pct = max(float(threshold_pct), 100.0)
    ratio_pct = (highest_value / baseline_value) * 100.0
    if highest_value <= (baseline_value * (normalized_threshold_pct / 100.0)):
        result["baseline_value"] = baseline_value
        result["ratio_pct"] = ratio_pct
        return result

    adjusted_values = list(normalized_values)
    adjusted_values[highest_index] = baseline_value
    result.update(
        {
            "applied": True,
            "values": adjusted_values,
            "labels": list(labels),
            "removed_label": highest_label,
            "removed_value": highest_value,
            "baseline_value": baseline_value,
            "ratio_pct": ratio_pct,
        }
    )
    return result


def _normalize_two_point_intermittent_spike(
    labels: list[str],
    values: list[float],
    method: MethodConfig,
    row: dict[str, object],
    forecast_used: bool,
    ratio_threshold: float = TWO_POINT_INTERMITTENT_SPIKE_RATIO_THRESHOLD,
) -> dict[str, object]:
    normalized_values = [float(value) for value in values]
    result = {
        "applied": False,
        "values": normalized_values,
        "labels": list(labels),
        "normalized_label": "",
        "normalized_value": 0.0,
        "baseline_value": 0.0,
        "ratio": 0.0,
        "non_zero_months": sum(1 for value in normalized_values if value > 0),
    }
    if (
        method.key != INTERMITTENT_BRANCH_METHOD_KEY
        or forecast_used
        or _is_dc_location(row.get("location"), row.get("supplier"))
        or len(labels) <= 1
    ):
        return result

    non_zero_entries = [
        (index, labels[index], value)
        for index, value in enumerate(normalized_values)
        if value > 0
    ]
    if len(non_zero_entries) != 2:
        return result

    sorted_entries = sorted(non_zero_entries, key=lambda entry: entry[2], reverse=True)
    top_index, top_label, top_value = sorted_entries[0]
    _, _, second_value = sorted_entries[1]
    if second_value <= 0:
        return result

    ratio = top_value / second_value
    if ratio < max(float(ratio_threshold), 1.0):
        result["baseline_value"] = second_value
        result["ratio"] = ratio
        return result

    adjusted_values = list(normalized_values)
    adjusted_values[top_index] = second_value
    result.update(
        {
            "applied": True,
            "values": adjusted_values,
            "labels": list(labels),
            "normalized_label": top_label,
            "normalized_value": top_value,
            "baseline_value": second_value,
            "ratio": ratio,
        }
    )
    return result


def _evaluate_intermittent_branch_protection(
    values: list[float],
    method: MethodConfig,
    row: dict[str, object],
    forecast_used: bool,
) -> dict[str, object]:
    scope_months = len(values)
    non_zero_values = [float(value) for value in values if float(value) > 0]
    non_zero_months = len(non_zero_values)
    total_demand = float(sum(values))
    inclusive_mean = _average(values, include_zeros=True)
    adi = (scope_months / non_zero_months) if non_zero_months else 0.0
    top_two_total = sum(sorted(non_zero_values, reverse=True)[:2])
    top_two_share = (top_two_total / total_demand) if total_demand > 0 else 0.0

    eligible = (
        method.key == INTERMITTENT_BRANCH_METHOD_KEY
        and not _is_dc_location(row.get("location"), row.get("supplier"))
        and not forecast_used
        and scope_months > 0
        and total_demand > 0
    )

    triggers: list[str] = []
    if eligible and non_zero_months <= INTERMITTENT_BRANCH_MIN_NON_ZERO_MONTHS:
        triggers.append(f"it only sold in {non_zero_months} of {scope_months} scoped months")
    if eligible and non_zero_months > 0 and adi >= INTERMITTENT_BRANCH_ADI_THRESHOLD:
        triggers.append(f"ADI is {adi:.1f}")
    if eligible and top_two_share >= INTERMITTENT_BRANCH_TOP_TWO_SHARE_THRESHOLD:
        triggers.append(f"the top two months account for {top_two_share * 100:.0f}% of scoped demand")

    applied = bool(triggers)
    reason = ", ".join(dict.fromkeys(triggers))
    return {
        "applied": applied,
        "scope_months": scope_months,
        "non_zero_months": non_zero_months,
        "adi": adi,
        "top_two_share_pct": top_two_share * 100.0,
        "inclusive_mean": inclusive_mean,
        "effective_mean": inclusive_mean if applied else _average(values, include_zeros=method.mean_include_zeros),
        "reason": reason,
    }


def _resolve_product_group_trend(
    row: dict[str, object],
    scoped_mean_labels: list[str],
    supplier_prod_group_profiles: dict[tuple[str, str], dict[str, object]],
    global_prod_group_profiles: dict[str, dict[str, object]],
) -> dict[str, object]:
    prod_group = str(row.get("prod_group") or "").strip()
    supplier = str(row.get("supplier") or "").strip()

    if not prod_group or len(scoped_mean_labels) < 2:
        return _empty_product_group_trend()

    supplier_profile = supplier_prod_group_profiles.get((supplier, prod_group))
    global_profile = global_prod_group_profiles.get(prod_group)

    source = "No product-group trend"
    profile = None
    if supplier_profile and int(supplier_profile.get("item_count", 0)) >= 2:
        profile = supplier_profile
        source = "Supplier product group"
    elif global_profile and int(global_profile.get("item_count", 0)) >= 2:
        profile = global_profile
        source = "Global product group"

    if profile is None:
        return _empty_product_group_trend()

    window_size = min(6, max(1, len(scoped_mean_labels) // 2))
    recent_labels = scoped_mean_labels[:window_size]
    prior_labels = scoped_mean_labels[window_size : window_size * 2]
    if not prior_labels:
        return _empty_product_group_trend()

    monthly_totals = profile["monthly_totals"]
    recent_avg = sum(float(monthly_totals.get(label, 0.0)) for label in recent_labels) / len(recent_labels)
    prior_avg = sum(float(monthly_totals.get(label, 0.0)) for label in prior_labels) / len(prior_labels)

    if prior_avg > 0:
        trend_ratio = recent_avg / prior_avg
    elif recent_avg > 0:
        trend_ratio = 1.25
    else:
        trend_ratio = 1.0

    trend_factor = _clamp(
        1.0 + ((trend_ratio - 1.0) * PRODUCT_GROUP_TREND_WEIGHT),
        PRODUCT_GROUP_TREND_MIN_FACTOR,
        PRODUCT_GROUP_TREND_MAX_FACTOR,
    )
    trend_label = "Flat"
    if trend_ratio >= 1.0 + PRODUCT_GROUP_TREND_THRESHOLD:
        trend_label = "Up"
    elif trend_ratio <= 1.0 - PRODUCT_GROUP_TREND_THRESHOLD:
        trend_label = "Down"

    return {
        "source": source,
        "label": trend_label,
        "factor": trend_factor,
        "recent_avg": recent_avg,
        "prior_avg": prior_avg,
        "scope": f"{', '.join(recent_labels)} vs {', '.join(prior_labels)}",
    }


def _empty_product_group_trend() -> dict[str, object]:
    return {
        "source": "No product-group trend",
        "label": "Flat",
        "factor": 1.0,
        "recent_avg": 0.0,
        "prior_avg": 0.0,
        "scope": "",
    }


def _apply_seasonality_window(
    month_labels: list[str],
    item_season: str,
    seasonality: SeasonalityConfig | None,
) -> list[str]:
    if not seasonality or not seasonality.enabled:
        return month_labels

    filtered = _seasonality_window_cached(tuple(month_labels), seasonality.planning_season)
    return list(filtered)


@lru_cache(maxsize=256)
def _seasonality_window_cached(month_labels: tuple[str, ...], planning_season: str) -> tuple[str, ...]:
    allowed_months = SEASON_MONTHS.get(planning_season, set())
    filtered = tuple(label for label in month_labels if _month_number(label) in allowed_months)
    return filtered or month_labels


@lru_cache(maxsize=64)
def _month_number(label: str) -> int | None:
    try:
        return datetime.strptime(label, "%b-%y").month
    except ValueError:
        return None


def _month_start(label: str) -> datetime | None:
    try:
        return datetime.strptime(label, "%b-%y")
    except ValueError:
        return None


def _season_matches_planning(item_season: object, planning_season: object) -> bool:
    item_text = str(item_season or "").strip()
    planning_text = str(planning_season or "").strip()
    return item_text in {"", "Both"} or item_text.casefold() == planning_text.casefold()


def _seasonality_note(item_season: str, seasonality: SeasonalityConfig | None, scoped_labels: list[str]) -> str:
    if not seasonality or not seasonality.enabled:
        return "Using the full method window with no seasonal narrowing."

    if not scoped_labels:
        return "Seasonality was requested, but no seasonal month labels were available, so the method fell back to the base window."

    alignment = "matches" if _season_matches_planning(item_season, seasonality.planning_season) else "does not match"
    return (
        f"Seasonality is using {seasonality.planning_season} months only. "
        f"Item season '{item_season or 'Unspecified'}' {alignment} the planning season."
    )


def _apply_status_rules(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data.copy()

    status_keys = data["status"].fillna("").map(_status_key)
    location_keys = data["location"].fillna("").astype(str).str.strip()
    current_max = pd.to_numeric(data["current_max"], errors="coerce").fillna(0.0)
    ignore_mask = status_keys.isin(IGNORED_STATUSES)
    ignore_mask = ignore_mask | (status_keys.isin(IGNORE_IF_ZERO_MAX_STATUSES) & (current_max <= 0))
    ignore_mask = ignore_mask | location_keys.isin(IGNORED_LOCATIONS)
    keep_mask = ~ignore_mask
    return data.loc[keep_mask].copy()


def _dashboard_category(status: object) -> str:
    return "Recommendations"


def _status_key(value: object) -> str:
    return str(value or "").strip().casefold()


def _status_contains_regional(value: object) -> bool:
    return bool(REGIONAL_STATUS_PATTERN.search(str(value or "").strip()))


def _override_flag(value: object) -> bool:
    return str(value or "").strip().upper() == "Y"


def _normalize_supplier_name(value: object) -> str:
    return str(value or "").strip().upper()


def _supplier_inventory_policy(supplier: object) -> dict[str, object]:
    normalized_supplier = _normalize_supplier_name(supplier)

    for pattern in NON_HUB_MANAGED_SUPPLIER_PATTERNS:
        if pattern in normalized_supplier:
            return {
                "hub_managed": False,
                "dc_location": "",
                "policy_source": pattern,
            }

    for pattern, dc_location in SUPPLIER_DC_LOCATION_OVERRIDES.items():
        if pattern in normalized_supplier:
            return {
                "hub_managed": True,
                "dc_location": str(dc_location),
                "policy_source": pattern,
            }

    return {
        "hub_managed": True,
        "dc_location": "1",
        "policy_source": "default",
    }


def _supports_precomputed_policies(data: pd.DataFrame) -> bool:
    if data.empty or "supplier" not in data.columns:
        return True

    suppliers = data["supplier"].dropna().astype(str).unique().tolist()
    for supplier in suppliers:
        policy = _supplier_inventory_policy(supplier)
        if not bool(policy["hub_managed"]) or str(policy["dc_location"] or "") != "1":
            return False
    return True


def _is_dc_location(value: object, supplier: object = None) -> bool:
    policy = _supplier_inventory_policy(supplier)
    if not bool(policy["hub_managed"]):
        return False
    return str(value or "").strip() == str(policy["dc_location"] or "").strip()


def _mac_amount(value: object) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(amount):
        return 0.0
    return amount


def _calculation_month_value(value: object) -> float:
    return max(_mac_amount(value), 0.0)


def _apply_negative_return_netting(
    data: pd.DataFrame,
    monthly_columns: list[str],
    max_lookback_months: int = RETURN_NETTING_MAX_LOOKBACK_MONTHS,
) -> pd.DataFrame:
    if data.empty or not monthly_columns:
        adjusted = data.copy()
        adjusted["negative_usage_netted_months"] = 0
        adjusted["negative_usage_netted_units"] = 0.0
        adjusted["negative_usage_unmatched_units"] = 0.0
        return adjusted

    adjusted = data.copy()
    month_frame = adjusted.loc[:, monthly_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    values = month_frame.to_numpy(dtype=float, copy=True)
    np.nan_to_num(values, copy=False, nan=0.0)

    chronological_indices = list(range(len(monthly_columns) - 1, -1, -1))
    netted_month_counts = np.zeros(len(adjusted), dtype=np.int32)
    netted_units = np.zeros(len(adjusted), dtype=np.float64)
    unmatched_units = np.zeros(len(adjusted), dtype=np.float64)

    for row_index in range(values.shape[0]):
        row_values = values[row_index]
        for chronological_position, current_index in enumerate(chronological_indices):
            current_value = row_values[current_index]
            if current_value >= 0:
                continue

            remaining_return = abs(float(current_value))
            row_values[current_index] = 0.0
            netted_month_counts[row_index] += 1
            netted_units[row_index] += remaining_return

            lookback_start = max(0, chronological_position - max_lookback_months)
            for prior_position in range(chronological_position - 1, lookback_start - 1, -1):
                prior_index = chronological_indices[prior_position]
                available_usage = max(float(row_values[prior_index]), 0.0)
                if available_usage <= 0:
                    continue
                reduction = min(available_usage, remaining_return)
                row_values[prior_index] = available_usage - reduction
                remaining_return -= reduction
                if remaining_return <= 1e-9:
                    break

            if remaining_return > 1e-9:
                unmatched_units[row_index] += remaining_return

    adjusted.loc[:, monthly_columns] = values
    adjusted["negative_usage_netted_months"] = netted_month_counts.astype(int)
    adjusted["negative_usage_netted_units"] = netted_units.astype(float)
    adjusted["negative_usage_unmatched_units"] = unmatched_units.astype(float)
    return adjusted


def _sync_branch_dc_pool(record: dict[str, object]) -> None:
    variability_amount = max(float(record.get("variability_pooled_to_dc", 0.0)), 0.0)
    direct_transfer_amount = max(float(record.get("direct_transfer_pooled_to_dc", 0.0)), 0.0)
    record["variability_pooled_to_dc"] = variability_amount
    record["direct_transfer_pooled_to_dc"] = direct_transfer_amount
    record["deviation_pooled_to_dc"] = variability_amount + direct_transfer_amount


def _reduce_branch_dc_pool(record: dict[str, object], reduction: float) -> float:
    remaining_reduction = max(float(reduction), 0.0)
    if remaining_reduction <= 0:
        return 0.0

    direct_transfer_amount = max(float(record.get("direct_transfer_pooled_to_dc", 0.0)), 0.0)
    direct_transfer_reduction = min(direct_transfer_amount, remaining_reduction)
    direct_transfer_amount -= direct_transfer_reduction
    remaining_reduction -= direct_transfer_reduction

    variability_amount = max(float(record.get("variability_pooled_to_dc", 0.0)), 0.0)
    variability_reduction = min(variability_amount, remaining_reduction)
    variability_amount -= variability_reduction
    remaining_reduction -= variability_reduction

    record["direct_transfer_pooled_to_dc"] = direct_transfer_amount
    record["variability_pooled_to_dc"] = variability_amount
    _sync_branch_dc_pool(record)
    return max(float(reduction) - remaining_reduction, 0.0)


def _add_branch_direct_transfer(record: dict[str, object], amount: float) -> None:
    if amount <= 0:
        return
    record["direct_transfer_pooled_to_dc"] = max(float(record.get("direct_transfer_pooled_to_dc", 0.0)), 0.0) + float(amount)
    _sync_branch_dc_pool(record)


def _set_primary_dc_absorption(
    primary: dict[str, object],
    pooled_variance_absorbed: float,
    pooled_direct_transfer_absorbed: float,
) -> None:
    pooled_variance_absorbed = max(float(pooled_variance_absorbed), 0.0)
    pooled_direct_transfer_absorbed = max(float(pooled_direct_transfer_absorbed), 0.0)
    primary["pooled_variance_absorbed_by_dc"] = pooled_variance_absorbed
    primary["pooled_direct_transfer_absorbed_by_dc"] = pooled_direct_transfer_absorbed
    primary["deviation_absorbed_by_dc"] = pooled_variance_absorbed + pooled_direct_transfer_absorbed


def _recompute_primary_dc_absorption(records: list[dict[str, object]]) -> None:
    if not records:
        return
    primary = records[0]
    pooled_variance_absorbed = math.sqrt(
        sum(max(float(record.get("variability_pooled_to_dc", 0.0)), 0.0) ** 2 for record in records[1:])
    )
    pooled_direct_transfer_absorbed = sum(
        max(float(record.get("direct_transfer_pooled_to_dc", 0.0)), 0.0) for record in records[1:]
    )
    _set_primary_dc_absorption(primary, pooled_variance_absorbed, pooled_direct_transfer_absorbed)


def _reduce_primary_dc_absorption(primary: dict[str, object], reduction: float) -> float:
    remaining_reduction = max(float(reduction), 0.0)
    if remaining_reduction <= 0:
        return 0.0

    pooled_direct_transfer_absorbed = max(float(primary.get("pooled_direct_transfer_absorbed_by_dc", 0.0)), 0.0)
    direct_transfer_reduction = min(pooled_direct_transfer_absorbed, remaining_reduction)
    pooled_direct_transfer_absorbed -= direct_transfer_reduction
    remaining_reduction -= direct_transfer_reduction

    pooled_variance_absorbed = max(float(primary.get("pooled_variance_absorbed_by_dc", 0.0)), 0.0)
    variance_reduction = min(pooled_variance_absorbed, remaining_reduction)
    pooled_variance_absorbed -= variance_reduction
    remaining_reduction -= variance_reduction

    _set_primary_dc_absorption(primary, pooled_variance_absorbed, pooled_direct_transfer_absorbed)
    return max(float(reduction) - remaining_reduction, 0.0)


def _supplier_min_amount_floor(value: object) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(amount) or amount <= 0:
        return 0.0
    return amount


def _apply_supplier_min_amount_floor(record: dict[str, object]) -> None:
    supplier_min_amount = _supplier_min_amount_floor(record.get("supplier_min_amount"))
    recommended_new_max = float(record.get("recommended_new_max", 0.0))
    floor_uplift = 0.0
    floor_applied = supplier_min_amount > 0 and recommended_new_max > 0 and recommended_new_max < supplier_min_amount
    if floor_applied:
        floor_uplift = supplier_min_amount - recommended_new_max
        record["recommended_new_max"] = supplier_min_amount
        if not _is_dc_location(record.get("location"), record.get("supplier")):
            _reduce_branch_dc_pool(record, floor_uplift)
    record["supplier_min_amount_floor"] = supplier_min_amount
    record["supplier_min_amount_floor_applied"] = floor_applied
    record["supplier_min_amount_floor_uplift"] = floor_uplift


def normalize_service_levels(service_levels: dict[str, float] | None = None) -> dict[str, float]:
    resolved = DEFAULT_SERVICE_LEVELS.copy()
    if not service_levels:
        return resolved

    for key, value in service_levels.items():
        normalized_key = str(key or "").strip().upper()
        if normalized_key not in resolved:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            numeric_value = resolved[normalized_key]
        if math.isnan(numeric_value):
            numeric_value = resolved[normalized_key]
        if numeric_value > 1.0:
            numeric_value = numeric_value / 100.0
        resolved[normalized_key] = max(0.01, min(numeric_value, 0.999))
    return resolved


def _service_level(abc_value: object, service_levels: dict[str, float] | None = None) -> float:
    key = str(abc_value or "").strip().upper()
    resolved_service_levels = service_levels or DEFAULT_SERVICE_LEVELS
    return resolved_service_levels.get(key, resolved_service_levels["X"])


def _lead_time_days(value: object) -> float:
    try:
        lead_time = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(lead_time):
        return 0.0
    return max(lead_time, 0.0)


def _frequency_days(value: object) -> float:
    text = str(value or "").strip()
    return _frequency_days_from_text(text)


@lru_cache(maxsize=128)
def _frequency_days_from_text(text: str) -> float:
    if not text:
        return 14.0

    lowered = text.casefold()
    if lowered == "local" or lowered.startswith("local "):
        return 28.0
    if lowered in {"weekly", "every week"}:
        return 7.0
    if lowered in {"biweekly", "bi-weekly", "2 weeks", "every 2 weeks"}:
        return 14.0
    if lowered in {"monthly", "every month"}:
        return 30.4375
    if lowered in {"quarterly", "every quarter"}:
        return 91.3125

    match = FREQUENCY_PATTERN.search(text)
    if not match:
        return 14.0

    count = float(match.group("count") or 1.0)
    unit = match.group("unit").casefold()
    if unit.startswith("day"):
        return count
    if unit.startswith("week"):
        return count * 7.0
    if unit.startswith("month"):
        return count * DAYS_PER_MONTH
    if unit.startswith("quarter"):
        return count * (DAYS_PER_MONTH * 3.0)
    return 14.0


def _average(values: list[float], include_zeros: bool) -> float:
    selected = values if include_zeros else [value for value in values if value != 0]
    if not selected:
        return 0.0
    return sum(selected) / len(selected)


def _sample_std(values: list[float], include_zeros: bool) -> float:
    selected = values if include_zeros else [value for value in values if value != 0]
    if len(selected) <= 1:
        return 0.0
    return float(stdev(selected))


def _value_count(values: list[float], include_zeros: bool) -> int:
    if include_zeros:
        return len(values)
    return sum(1 for value in values if value != 0)


def _round_value(value: float, mode: str) -> int:
    if mode == "roundup":
        return math.ceil(value)
    rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _location_rule(current_max: float, rounded_mean: float) -> float:
    if float(current_max) > 0:
        return 1.0 if float(rounded_mean) == 0 else float(rounded_mean)
    return 0.0
