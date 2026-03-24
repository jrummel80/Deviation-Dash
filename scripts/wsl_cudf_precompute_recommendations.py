from __future__ import annotations

import argparse
import json
import math
import re
from statistics import NormalDist

import cudf
import cupy as cp
import pandas as pd


LOCATION_ORDER = ["1", "30", "40", "115", "116", "117", "118", "119"]
IGNORED_LOCATIONS = {"9999"}
IGNORED_STATUSES = {
    "service",
    "ok to sell below cost",
    "special",
    "inactive",
    "substitute",
    "exception",
}
IGNORE_IF_ZERO_MAX_STATUSES = {"stock", "stock with no max"}
SEASON_MONTHS = {
    "Summer": {4, 5, 6, 7, 8, 9},
    "Winter": {10, 11, 12, 1, 2, 3},
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
DAYS_PER_MONTH = 30.4375
FREQUENCY_PATTERN = re.compile(
    r"(?P<count>\d+(?:\.\d+)?)?\s*(?P<unit>day|days|week|weeks|month|months|quarter|quarters)",
    re.IGNORECASE,
)

TREND_SOURCE_LABELS = {
    0: "No product-group trend",
    1: "Supplier product group",
    2: "Global product group",
}
TREND_LABELS = {
    -1: "Down",
    0: "Flat",
    1: "Up",
}
REFERENCE_RULES = {
    24: "Year-over-year demand stayed within +/-33%, so both years are used.",
    12: "Year-over-year demand moved outside +/-33%, so the model uses the last 12 months.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Precompute recommendation math with cuDF in WSL.")
    parser.add_argument("--input", required=True, help="Input parquet path.")
    parser.add_argument("--output", required=True, help="Output parquet path.")
    parser.add_argument("--params", required=True, help="JSON parameter file path.")
    parser.add_argument("--forecast", help="Optional forecast parquet path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with open(args.params, "r", encoding="utf-8") as handle:
        params = json.load(handle)
    monthly_columns = list(params["monthly_columns"])
    method = params["method"]
    seasonality = params["seasonality"]
    service_levels = {str(key).upper(): float(value) for key, value in params["service_levels"].items()}
    service_z_scores = {key: float(NormalDist().inv_cdf(value)) for key, value in service_levels.items()}

    frame = cudf.read_parquet(args.input)
    frame = apply_status_rules(frame)
    if len(frame) == 0:
        pd.DataFrame().to_parquet(args.output, index=False)
        return 0
    frame[monthly_columns] = frame[monthly_columns].clip(lower=0)

    frame["location_sort"] = build_location_sort(frame["location"])
    frame = frame.sort_values(["supplier", "item", "location_sort", "location"], kind="stable")

    reference_frame = build_reference_window_frame(frame, monthly_columns)
    frame = frame.merge(reference_frame, on=["supplier", "item"], how="left")

    forecast_frame = None
    if args.forecast:
        forecast_frame = cudf.read_parquet(args.forecast)
        frame = frame.merge(forecast_frame, on=["supplier", "item", "location"], how="left")
    else:
        frame["forecast_mean"] = None

    scoped_config = build_scoped_month_configs(monthly_columns, method, seasonality)
    filtered_with_prod_group = frame[frame["prod_group"].fillna("").astype("str").str.strip() != ""].copy()

    output_frames: list[cudf.DataFrame] = []
    for reference_months, config in scoped_config.items():
        subset = frame[frame["reference_window_months"] == reference_months].copy()
        if len(subset) == 0:
            continue

        supplier_profile, global_profile = build_product_group_profiles_gpu(filtered_with_prod_group, config["mean_labels"])
        subset = subset.merge(supplier_profile, on=["supplier", "prod_group"], how="left")
        subset = subset.merge(global_profile, on=["prod_group"], how="left")
        subset = compute_subset_metrics(
            subset,
            config,
            method,
            service_levels,
            service_z_scores,
        )
        output_frames.append(subset)

    if not output_frames:
        pd.DataFrame().to_parquet(args.output, index=False)
        return 0

    combined = cudf.concat(output_frames, ignore_index=True)
    combined = combined.sort_values(["supplier", "item", "location_sort", "location"], kind="stable")
    combined["is_primary_candidate"] = build_primary_candidate(combined)

    output = combined.to_pandas()
    output["reference_window_rule"] = output["reference_window_months"].map(REFERENCE_RULES)
    output["product_group_trend_source"] = output["product_group_trend_source_code"].map(TREND_SOURCE_LABELS)
    output["product_group_trend_label"] = output["product_group_trend_label_code"].map(TREND_LABELS)
    output["forecast_mode"] = output["forecast_mode_code"].map({1: "AI Forecast + Rules", 0: "Rules Only"})
    output["mean_source"] = output["mean_source_code"].map({1: "AutoGluon forecast", 0: "Historical demand"})
    output["intermittent_reason"] = output.apply(
        lambda row: build_intermittent_reason(
            bool(row.get("intermittent_branch_protection_applied", False)),
            int(row.get("intermittent_non_zero_months", 0) or 0),
            int(row.get("intermittent_scope_months", 0) or 0),
            float(row.get("intermittent_adi", 0.0) or 0.0),
            float(row.get("intermittent_top_two_share_pct", 0.0) or 0.0),
        ),
        axis=1,
    )
    output["seasonality_note"] = output.apply(
        lambda row: build_seasonality_note(
            str(row.get("season", "")),
            bool(row.get("seasonality_enabled", False)),
            str(row.get("planning_season", "All Months")),
            str(row.get("mean_month_scope", "")),
        ),
        axis=1,
    )
    output["dashboard_category"] = "Recommendations"
    output["recommendation_explanation"] = ""
    output["recommended_new_max"] = 0.0
    output["is_balancing_location"] = False
    output.to_parquet(args.output, index=False)
    return 0


def apply_status_rules(frame: cudf.DataFrame) -> cudf.DataFrame:
    status_keys = frame["status"].fillna("").astype("str").str.strip().str.lower()
    location_keys = frame["location"].fillna("").astype("str").str.strip()
    current_max = cudf.to_numeric(frame["current_max"], errors="coerce").fillna(0.0)
    ignore_mask = status_keys.isin(list(IGNORED_STATUSES))
    ignore_mask = ignore_mask | (status_keys.isin(list(IGNORE_IF_ZERO_MAX_STATUSES)) & (current_max <= 0))
    ignore_mask = ignore_mask | location_keys.isin(list(IGNORED_LOCATIONS))
    return frame.loc[~ignore_mask].copy()


def build_location_sort(location_series: cudf.Series) -> cudf.Series:
    mapping_frame = cudf.DataFrame(
        {
            "location": LOCATION_ORDER,
            "location_sort": list(range(len(LOCATION_ORDER))),
        }
    )
    location_frame = cudf.DataFrame({"location": location_series.astype("str")})
    location_frame = location_frame.merge(mapping_frame, on="location", how="left")
    return location_frame["location_sort"].fillna(len(LOCATION_ORDER))


def build_reference_window_frame(frame: cudf.DataFrame, monthly_columns: list[str]) -> cudf.DataFrame:
    group_totals = frame.groupby(["supplier", "item"], dropna=False)[monthly_columns].sum().reset_index()
    recent_labels = monthly_columns[:12]
    prior_labels = monthly_columns[12:24]

    recent_total = cp.sum(group_totals[recent_labels].to_cupy(), axis=1) if recent_labels else cp.zeros(len(group_totals))
    prior_total = cp.sum(group_totals[prior_labels].to_cupy(), axis=1) if prior_labels else cp.zeros(len(group_totals))

    stable = cp.zeros(len(group_totals), dtype=cp.bool_)
    yoy_change_pct = cp.zeros(len(group_totals), dtype=cp.float64)

    prior_positive = prior_total > 0
    yoy_change_pct = cp.where(
        prior_positive,
        ((recent_total - prior_total) / prior_total) * 100.0,
        yoy_change_pct,
    )
    stable = cp.where(
        prior_positive,
        (yoy_change_pct >= -YOY_STABLE_THRESHOLD) & (yoy_change_pct <= YOY_STABLE_THRESHOLD),
        stable,
    )

    recent_zero = recent_total == 0
    stable = cp.where((~prior_positive) & recent_zero, True, stable)
    yoy_change_pct = cp.where((~prior_positive) & recent_zero, 0.0, yoy_change_pct)
    yoy_change_pct = cp.where((~prior_positive) & (~recent_zero), 100.0, yoy_change_pct)

    reference_months = cp.where(stable & (len(prior_labels) == 12), 24, 12)

    result = group_totals[["supplier", "item"]].copy()
    result["recent_total"] = recent_total
    result["prior_total"] = prior_total
    result["reference_window_months"] = reference_months
    result["yoy_change_pct"] = yoy_change_pct
    return result


def build_scoped_month_configs(
    monthly_columns: list[str],
    method: dict[str, object],
    seasonality: dict[str, object],
) -> dict[int, dict[str, object]]:
    configs: dict[int, dict[str, object]] = {}
    for reference_months in (12, 24):
        mean_labels = monthly_columns[: min(int(method["mean_months"]), reference_months)]
        std_labels = monthly_columns[: min(int(method["std_months"]), reference_months)]
        summary_labels = list(mean_labels)
        scoped_mean_labels = apply_seasonality_window(mean_labels, seasonality)
        scoped_std_labels = apply_seasonality_window(std_labels, seasonality)
        scoped_summary_labels = apply_seasonality_window(summary_labels, seasonality)
        configs[reference_months] = {
            "mean_labels": scoped_mean_labels,
            "std_labels": scoped_std_labels,
            "summary_labels": scoped_summary_labels,
            "mean_scope": ", ".join(scoped_mean_labels),
            "std_scope": ", ".join(scoped_std_labels),
            "summary_scope": ", ".join(scoped_summary_labels),
            "seasonality_enabled": bool(seasonality["enabled"]),
            "planning_season": seasonality["planning_season"] if seasonality["enabled"] else "All Months",
        }
    return configs


def apply_seasonality_window(month_labels: list[str], seasonality: dict[str, object]) -> list[str]:
    if not seasonality["enabled"]:
        return month_labels
    allowed_months = SEASON_MONTHS.get(str(seasonality["planning_season"]), set())
    filtered = [label for label in month_labels if month_number(label) in allowed_months]
    return filtered or month_labels


def month_number(label: str) -> int | None:
    try:
        return pd.to_datetime(label, format="%b-%y").month
    except Exception:
        return None


def build_product_group_profiles_gpu(frame: cudf.DataFrame, scoped_mean_labels: list[str]) -> tuple[cudf.DataFrame, cudf.DataFrame]:
    if len(frame) == 0 or len(scoped_mean_labels) < 2:
        return empty_supplier_profile(), empty_global_profile()

    window_size = min(6, max(1, len(scoped_mean_labels) // 2))
    recent_labels = scoped_mean_labels[:window_size]
    prior_labels = scoped_mean_labels[window_size : window_size * 2]
    if not prior_labels:
        return empty_supplier_profile(), empty_global_profile()

    supplier_monthly = frame.groupby(["supplier", "prod_group"], dropna=False)[recent_labels + prior_labels].sum().reset_index()
    supplier_counts = frame.groupby(["supplier", "prod_group"], dropna=False)["item"].nunique().reset_index(name="supplier_item_count")
    supplier_profile = supplier_monthly.merge(supplier_counts, on=["supplier", "prod_group"], how="left")
    supplier_profile = attach_profile_metrics(supplier_profile, recent_labels, prior_labels, "supplier")

    global_monthly = frame.groupby(["prod_group"], dropna=False)[recent_labels + prior_labels].sum().reset_index()
    global_counts = frame.groupby(["prod_group"], dropna=False)["item"].nunique().reset_index(name="global_item_count")
    global_profile = global_monthly.merge(global_counts, on=["prod_group"], how="left")
    global_profile = attach_profile_metrics(global_profile, recent_labels, prior_labels, "global")

    return supplier_profile, global_profile


def attach_profile_metrics(
    frame: cudf.DataFrame,
    recent_labels: list[str],
    prior_labels: list[str],
    prefix: str,
) -> cudf.DataFrame:
    recent_avg = cp.sum(frame[recent_labels].to_cupy(), axis=1) / len(recent_labels)
    prior_avg = cp.sum(frame[prior_labels].to_cupy(), axis=1) / len(prior_labels)
    trend_ratio = cp.where(prior_avg > 0, recent_avg / prior_avg, cp.where(recent_avg > 0, 1.25, 1.0))
    trend_factor = cp.clip(
        1.0 + ((trend_ratio - 1.0) * PRODUCT_GROUP_TREND_WEIGHT),
        PRODUCT_GROUP_TREND_MIN_FACTOR,
        PRODUCT_GROUP_TREND_MAX_FACTOR,
    )
    trend_label_code = cp.where(
        trend_ratio >= 1.0 + PRODUCT_GROUP_TREND_THRESHOLD,
        1,
        cp.where(trend_ratio <= 1.0 - PRODUCT_GROUP_TREND_THRESHOLD, -1, 0),
    )
    frame[f"{prefix}_recent_avg"] = recent_avg
    frame[f"{prefix}_prior_avg"] = prior_avg
    frame[f"{prefix}_trend_factor"] = trend_factor
    frame[f"{prefix}_trend_label_code"] = trend_label_code
    return frame


def empty_supplier_profile() -> cudf.DataFrame:
    return cudf.DataFrame(
        {
            "supplier": [],
            "prod_group": [],
            "supplier_item_count": [],
            "supplier_recent_avg": [],
            "supplier_prior_avg": [],
            "supplier_trend_factor": [],
            "supplier_trend_label_code": [],
        }
    )


def empty_global_profile() -> cudf.DataFrame:
    return cudf.DataFrame(
        {
            "prod_group": [],
            "global_item_count": [],
            "global_recent_avg": [],
            "global_prior_avg": [],
            "global_trend_factor": [],
            "global_trend_label_code": [],
        }
    )


def compute_subset_metrics(
    subset: cudf.DataFrame,
    config: dict[str, object],
    method: dict[str, object],
    service_levels: dict[str, float],
    service_z_scores: dict[str, float],
) -> cudf.DataFrame:
    subset = subset.copy()
    mean_labels = list(config["mean_labels"])
    std_labels = list(config["std_labels"])
    subset = attach_product_group_choice(subset, config)
    subset = attach_frequency_days(subset)
    subset = attach_service_levels(subset, service_levels, service_z_scores)

    filtered_mean, active_months_mean = compute_mean_stats(
        subset,
        mean_labels,
        bool(method["mean_include_zeros"]),
    )
    filtered_std_dev, active_months_std = compute_std_stats(
        subset,
        std_labels,
        bool(method["std_include_zeros"]),
    )
    intermittent_metrics = compute_intermittent_branch_metrics(
        subset,
        mean_labels,
        str(method["key"]),
        forecast_mean_column="forecast_mean",
    )

    forecast_mean = cudf.to_numeric(subset["forecast_mean"], errors="coerce")
    forecast_valid = forecast_mean.notna().fillna(False).to_cupy()
    forecast_values = forecast_mean.fillna(0.0).to_cupy()
    product_group_factor = subset["product_group_trend_factor"].fillna(1.0).to_cupy()
    filtered_mean_cp = filtered_mean.astype(cp.float64)
    effective_mean = cp.where(
        intermittent_metrics["applied"],
        intermittent_metrics["inclusive_mean"],
        filtered_mean_cp,
    )
    trend_adjusted_mean = cp.where(
        forecast_valid,
        cp.maximum(forecast_values, 0.0),
        effective_mean * product_group_factor,
    )
    raw_trend_adjusted_mean = cp.where(
        forecast_valid,
        cp.maximum(forecast_values, 0.0),
        filtered_mean_cp * product_group_factor,
    )
    applied_product_group_factor = cp.where(forecast_valid, 1.0, product_group_factor)

    if str(method["rounding_mode"]) == "roundup":
        rounded_mean = cp.ceil(trend_adjusted_mean)
        raw_rounded_mean = cp.ceil(raw_trend_adjusted_mean)
    else:
        rounded_mean = cp.floor(trend_adjusted_mean + 0.5)
        raw_rounded_mean = cp.floor(raw_trend_adjusted_mean + 0.5)

    delta = trend_adjusted_mean - rounded_mean
    total_dev = delta + filtered_std_dev
    intermittent_spike_pooled_to_dc = cp.maximum(raw_trend_adjusted_mean - trend_adjusted_mean, 0.0)
    lead_time_days = cudf.to_numeric(subset["lead_time"], errors="coerce").fillna(0.0).to_cupy()
    lead_time_days = cp.maximum(lead_time_days, 0.0)
    frequency_days = cudf.to_numeric(subset["frequency_days"], errors="coerce").fillna(14.0).to_cupy()
    raw_protection_days = lead_time_days + frequency_days
    protection_days = cp.maximum(raw_protection_days, 28.0)
    daily_mean = trend_adjusted_mean / DAYS_PER_MONTH
    lead_time_demand = daily_mean * lead_time_days
    cycle_demand = daily_mean * cp.maximum(protection_days - lead_time_days, 0.0)
    protected_cycle_demand = lead_time_demand + cycle_demand
    lead_time_std = cp.where(
        lead_time_days > 0,
        filtered_std_dev * cp.sqrt(lead_time_days / DAYS_PER_MONTH),
        0.0,
    )
    protection_std = cp.where(
        protection_days > 0,
        filtered_std_dev * cp.sqrt(protection_days / DAYS_PER_MONTH),
        0.0,
    )

    demand_only_min_amount = cp.ceil(cp.maximum(lead_time_demand, 0.0))
    service_level_min_amount = cp.ceil(
        cp.maximum(lead_time_demand + (subset["service_z_score"].to_cupy() * lead_time_std), 0.0)
    )
    dc_transfer_reserve_amount = cp.ceil(cp.maximum(protected_cycle_demand, 0.0))
    demand_only_order_up_to = cp.ceil(cp.maximum(protected_cycle_demand, demand_only_min_amount))
    service_level_order_up_to = cp.ceil(
        cp.maximum(
            protected_cycle_demand + (subset["service_z_score"].to_cupy() * protection_std),
            service_level_min_amount,
        )
    )

    dc_location_reserve_rule_applied = subset["location"].astype("str").str.strip() == "1"
    dc_rule_cp = dc_location_reserve_rule_applied.fillna(False).to_cupy()
    recommended_min_amount = cp.where(dc_rule_cp, dc_transfer_reserve_amount, demand_only_min_amount)
    policy_order_up_to = cp.where(dc_rule_cp, service_level_order_up_to, demand_only_order_up_to)

    current_max = cudf.to_numeric(subset["current_max"], errors="coerce").fillna(0.0).to_cupy()
    rounded_mean_cp = rounded_mean.astype(cp.float64)
    base_branch_recommendation = cp.where(
        current_max > 0,
        cp.where(rounded_mean_cp == 0, 1.0, rounded_mean_cp),
        0.0,
    )
    branch_demand_recommendation = cp.maximum(
        base_branch_recommendation,
        cp.maximum(policy_order_up_to, recommended_min_amount),
    )
    service_level_recommendation = cp.maximum(
        base_branch_recommendation,
        cp.maximum(service_level_order_up_to, service_level_min_amount),
    )
    preliminary_deviation_pool = cp.where(
        dc_rule_cp,
        0.0,
        cp.maximum(service_level_recommendation - branch_demand_recommendation, 0.0),
    )

    override_flag = subset["override"].fillna("").astype("str").str.strip().str.upper() == "Y"
    forecast_mode_code = cp.where(forecast_valid, 1, 0)
    mean_source_code = cp.where(forecast_valid, 1, 0)

    subset["filtered_mean"] = effective_mean
    subset["raw_filtered_mean"] = filtered_mean
    subset["filtered_std_dev"] = filtered_std_dev
    subset["trend_adjusted_mean"] = trend_adjusted_mean
    subset["raw_trend_adjusted_mean"] = raw_trend_adjusted_mean
    subset["autogluon_forecast_mean"] = forecast_mean.fillna(cp.nan)
    subset["forecast_used"] = cudf.Series(forecast_valid)
    subset["forecast_mode_code"] = forecast_mode_code
    subset["mean_source_code"] = mean_source_code
    subset["rounded_mean"] = rounded_mean
    subset["raw_rounded_mean"] = raw_rounded_mean
    subset["delta"] = delta
    subset["total_dev"] = total_dev
    subset["daily_demand"] = daily_mean
    subset["lead_time_days"] = lead_time_days
    subset["frequency_days"] = frequency_days
    subset["review_cycle_days"] = frequency_days
    subset["raw_protection_days"] = raw_protection_days
    subset["protection_days"] = protection_days
    subset["minimum_28_day_rule_applied"] = raw_protection_days < 28.0
    subset["lead_time_demand"] = lead_time_demand
    subset["cycle_demand"] = cycle_demand
    subset["protected_cycle_demand"] = protected_cycle_demand
    subset["lead_time_std"] = lead_time_std
    subset["protection_std"] = protection_std
    subset["demand_only_min_amount"] = demand_only_min_amount
    subset["service_level_min_amount"] = service_level_min_amount
    subset["dc_transfer_reserve_amount"] = dc_transfer_reserve_amount
    subset["demand_only_order_up_to"] = demand_only_order_up_to
    subset["service_level_order_up_to"] = service_level_order_up_to
    subset["recommended_min_amount"] = recommended_min_amount
    subset["policy_order_up_to"] = policy_order_up_to
    subset["dc_location_reserve_rule_applied"] = dc_location_reserve_rule_applied
    subset["override_flag"] = override_flag
    subset["active_months_mean"] = active_months_mean
    subset["active_months_std"] = active_months_std
    subset["mean_months_window"] = len(mean_labels)
    subset["std_months_window"] = len(std_labels)
    subset["mean_month_scope"] = str(config["mean_scope"])
    subset["std_month_scope"] = str(config["std_scope"])
    subset["summary_month_scope"] = str(config["summary_scope"])
    subset["seasonality_enabled"] = bool(config["seasonality_enabled"])
    subset["planning_season"] = str(config["planning_season"])
    subset["product_group_trend_factor"] = applied_product_group_factor
    subset["intermittent_branch_protection_applied"] = cudf.Series(intermittent_metrics["applied"])
    subset["intermittent_scope_months"] = int(intermittent_metrics["scope_months"])
    subset["intermittent_non_zero_months"] = intermittent_metrics["non_zero_months"]
    subset["intermittent_adi"] = intermittent_metrics["adi"]
    subset["intermittent_top_two_share_pct"] = intermittent_metrics["top_two_share_pct"]
    subset["intermittent_inclusive_mean"] = intermittent_metrics["inclusive_mean"]
    subset["intermittent_spike_pooled_to_dc"] = intermittent_spike_pooled_to_dc
    subset["base_branch_recommendation"] = base_branch_recommendation
    subset["branch_demand_recommendation"] = branch_demand_recommendation
    subset["service_level_recommendation"] = service_level_recommendation
    subset["preliminary_deviation_pool"] = preliminary_deviation_pool
    return subset


def attach_product_group_choice(subset: cudf.DataFrame, config: dict[str, object]) -> cudf.DataFrame:
    subset = subset.copy()
    supplier_count = cudf.to_numeric(subset.get("supplier_item_count"), errors="coerce").fillna(0).to_cupy()
    global_count = cudf.to_numeric(subset.get("global_item_count"), errors="coerce").fillna(0).to_cupy()
    use_supplier = supplier_count >= 2
    use_global = (~use_supplier) & (global_count >= 2)

    supplier_factor = cudf.to_numeric(subset.get("supplier_trend_factor"), errors="coerce").fillna(1.0).to_cupy()
    global_factor = cudf.to_numeric(subset.get("global_trend_factor"), errors="coerce").fillna(1.0).to_cupy()
    supplier_recent = cudf.to_numeric(subset.get("supplier_recent_avg"), errors="coerce").fillna(0.0).to_cupy()
    supplier_prior = cudf.to_numeric(subset.get("supplier_prior_avg"), errors="coerce").fillna(0.0).to_cupy()
    global_recent = cudf.to_numeric(subset.get("global_recent_avg"), errors="coerce").fillna(0.0).to_cupy()
    global_prior = cudf.to_numeric(subset.get("global_prior_avg"), errors="coerce").fillna(0.0).to_cupy()
    supplier_label = cudf.to_numeric(subset.get("supplier_trend_label_code"), errors="coerce").fillna(0).to_cupy()
    global_label = cudf.to_numeric(subset.get("global_trend_label_code"), errors="coerce").fillna(0).to_cupy()

    subset["product_group_trend_factor"] = cp.where(use_supplier, supplier_factor, cp.where(use_global, global_factor, 1.0))
    subset["product_group_recent_avg"] = cp.where(use_supplier, supplier_recent, cp.where(use_global, global_recent, 0.0))
    subset["product_group_prior_avg"] = cp.where(use_supplier, supplier_prior, cp.where(use_global, global_prior, 0.0))
    subset["product_group_trend_source_code"] = cp.where(use_supplier, 1, cp.where(use_global, 2, 0))
    subset["product_group_trend_label_code"] = cp.where(use_supplier, supplier_label, cp.where(use_global, global_label, 0))
    subset["product_group_trend_scope"] = str(config["mean_scope"])
    return subset


def attach_frequency_days(subset: cudf.DataFrame) -> cudf.DataFrame:
    subset = subset.copy()
    frequency_values = subset["frequency"].fillna("").astype("str").to_pandas().unique().tolist()
    mapping = pd.DataFrame(
        {
            "frequency": frequency_values,
            "frequency_days": [frequency_days(value) for value in frequency_values],
        }
    )
    subset = subset.merge(cudf.from_pandas(mapping), on="frequency", how="left")
    subset["frequency_days"] = cudf.to_numeric(subset["frequency_days"], errors="coerce").fillna(14.0)
    return subset


def attach_service_levels(
    subset: cudf.DataFrame,
    service_levels: dict[str, float],
    service_z_scores: dict[str, float],
) -> cudf.DataFrame:
    subset = subset.copy()
    abc_values = subset["abc"].fillna("").astype("str").str.upper().to_pandas().unique().tolist()
    mapping = pd.DataFrame(
        {
            "abc": abc_values,
            "service_level": [service_levels.get(str(value).upper(), service_levels["X"]) for value in abc_values],
            "service_z_score": [service_z_scores.get(str(value).upper(), service_z_scores["X"]) for value in abc_values],
        }
    )
    subset = subset.merge(cudf.from_pandas(mapping), on="abc", how="left")
    subset["service_level"] = cudf.to_numeric(subset["service_level"], errors="coerce").fillna(service_levels["X"])
    subset["service_level_pct"] = subset["service_level"] * 100.0
    subset["service_z_score"] = cudf.to_numeric(subset["service_z_score"], errors="coerce").fillna(service_z_scores["X"])
    return subset


def compute_intermittent_branch_metrics(
    subset: cudf.DataFrame,
    labels: list[str],
    method_key: str,
    forecast_mean_column: str,
) -> dict[str, object]:
    row_count = len(subset)
    if not labels or row_count == 0:
        zero = cp.zeros(row_count, dtype=cp.float64)
        return {
            "applied": cp.zeros(row_count, dtype=cp.bool_),
            "scope_months": len(labels),
            "non_zero_months": zero.astype(cp.int32),
            "adi": zero,
            "top_two_share_pct": zero,
            "inclusive_mean": zero,
        }

    values = subset[labels].astype("float64").to_cupy()
    positive_values = cp.where(values > 0, values, 0.0)
    non_zero_mask = values > 0
    non_zero_months = non_zero_mask.sum(axis=1).astype(cp.int32)
    scope_months = values.shape[1]
    total_demand = positive_values.sum(axis=1)
    inclusive_mean = cp.mean(values, axis=1)
    sorted_values = cp.sort(positive_values, axis=1)
    top_two_total = sorted_values[:, -2:].sum(axis=1) if scope_months >= 2 else sorted_values[:, -1]
    top_two_share_pct = cp.where(total_demand > 0, (top_two_total / total_demand) * 100.0, 0.0)
    adi = cp.where(non_zero_months > 0, scope_months / non_zero_months.astype(cp.float64), 0.0)
    forecast_mean = cudf.to_numeric(subset[forecast_mean_column], errors="coerce")
    forecast_used = forecast_mean.notna().fillna(False).to_cupy()
    is_dc_location = cp.asarray(subset["location"].astype("str").str.strip().to_pandas().to_numpy() == "1")

    if method_key != INTERMITTENT_BRANCH_METHOD_KEY:
        applied = cp.zeros(row_count, dtype=cp.bool_)
    else:
        eligible = (~forecast_used) & (~is_dc_location) & (total_demand > 0) & (scope_months > 0)
        applied = eligible & (
            (non_zero_months <= INTERMITTENT_BRANCH_MIN_NON_ZERO_MONTHS)
            | (adi >= INTERMITTENT_BRANCH_ADI_THRESHOLD)
            | (top_two_share_pct >= (INTERMITTENT_BRANCH_TOP_TWO_SHARE_THRESHOLD * 100.0))
        )
    return {
        "applied": applied,
        "scope_months": scope_months,
        "non_zero_months": non_zero_months,
        "adi": adi,
        "top_two_share_pct": top_two_share_pct,
        "inclusive_mean": inclusive_mean,
    }


def compute_mean_stats(
    subset: cudf.DataFrame,
    labels: list[str],
    include_zeros: bool,
) -> tuple[cp.ndarray, cp.ndarray]:
    if not labels:
        zero = cp.zeros(len(subset), dtype=cp.float64)
        return zero, zero.astype(cp.int32)
    values = subset[labels].astype("float64").to_cupy()
    if include_zeros:
        mean = cp.mean(values, axis=1)
        count = cp.full(values.shape[0], values.shape[1], dtype=cp.int32)
        return mean, count
    mask = values != 0
    count = mask.sum(axis=1).astype(cp.int32)
    selected_sum = cp.where(mask, values, 0.0).sum(axis=1)
    mean = cp.where(count > 0, selected_sum / count, 0.0)
    return mean, count


def compute_std_stats(
    subset: cudf.DataFrame,
    labels: list[str],
    include_zeros: bool,
) -> tuple[cp.ndarray, cp.ndarray]:
    if not labels:
        zero = cp.zeros(len(subset), dtype=cp.float64)
        return zero, zero.astype(cp.int32)
    values = subset[labels].astype("float64").to_cupy()
    if include_zeros:
        if values.shape[1] <= 1:
            zero = cp.zeros(values.shape[0], dtype=cp.float64)
            count = cp.full(values.shape[0], values.shape[1], dtype=cp.int32)
            return zero, count
        std = cp.std(values, axis=1, ddof=1)
        count = cp.full(values.shape[0], values.shape[1], dtype=cp.int32)
        return std, count
    mask = values != 0
    count = mask.sum(axis=1).astype(cp.int32)
    selected = cp.where(mask, values, 0.0)
    selected_sum = selected.sum(axis=1)
    selected_sum_sq = cp.square(selected).sum(axis=1)
    variance = cp.where(
        count > 1,
        (selected_sum_sq - (cp.square(selected_sum) / count)) / (count - 1),
        0.0,
    )
    variance = cp.maximum(variance, 0.0)
    return cp.sqrt(variance), count


def build_primary_candidate(frame: cudf.DataFrame) -> cudf.Series:
    group_min = frame.groupby(["supplier", "item"], dropna=False)["location_sort"].min().reset_index()
    group_min = group_min.rename(columns={"location_sort": "primary_location_sort"})
    merged = frame[["supplier", "item", "location_sort"]].merge(group_min, on=["supplier", "item"], how="left")
    return merged["location_sort"] == merged["primary_location_sort"]


def build_seasonality_note(item_season: str, enabled: bool, planning_season: str, mean_scope: str) -> str:
    if not enabled:
        return "Using the full method window with no seasonal narrowing."
    if not mean_scope:
        return "Seasonality was requested, but no seasonal month labels were available, so the method fell back to the base window."
    alignment = "matches" if item_season in ("Both", "", planning_season) else "does not match"
    return f"Seasonality is using {planning_season} months only. Item season '{item_season or 'Unspecified'}' {alignment} the planning season."


def build_intermittent_reason(
    applied: bool,
    non_zero_months: int,
    scope_months: int,
    adi: float,
    top_two_share_pct: float,
) -> str:
    if not applied:
        return ""
    triggers: list[str] = []
    if non_zero_months <= INTERMITTENT_BRANCH_MIN_NON_ZERO_MONTHS:
        triggers.append(f"it only sold in {non_zero_months} of {scope_months} scoped months")
    if adi >= INTERMITTENT_BRANCH_ADI_THRESHOLD:
        triggers.append(f"ADI is {adi:.1f}")
    if top_two_share_pct >= (INTERMITTENT_BRANCH_TOP_TWO_SHARE_THRESHOLD * 100.0):
        triggers.append(f"the top two months account for {top_two_share_pct:.0f}% of scoped demand")
    return ", ".join(dict.fromkeys(triggers))


def frequency_days(value: object) -> float:
    text = str(value or "").strip()
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
        return DAYS_PER_MONTH
    if lowered in {"quarterly", "every quarter"}:
        return DAYS_PER_MONTH * 3.0
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


if __name__ == "__main__":
    raise SystemExit(main())
