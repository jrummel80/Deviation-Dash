# How To Use Deviation Dash To Train Other Models

## Purpose

This guide explains how to use the current Deviation Dash engine as a teacher for other forecasting or recommendation models.

The short version:

- learn demand where learning helps
- keep hard inventory-policy rules explicit
- use the current engine to generate labeled training data

If another team wants one sentence to remember, it should be:

> Use this engine as a versioned teacher, not as a bag of ad hoc spreadsheet outputs.

## The Recommended Architecture

The safest architecture is still a hybrid:

1. A learned model estimates demand.
2. The deterministic rules engine converts demand into min/max.
3. Optional explanation or ranking models sit on top.

This is better than training a black box to guess min and max directly because the current engine already contains a large amount of policy logic that is not really "forecasting."

## What The Current Engine Already Knows

The current engine already encodes:

- ignored statuses and ignored locations
- branch vs DC behavior
- supplier-specific hub policy
- DC-location overrides
- service level by `ABC`
- lead-time and frequency coverage
- seasonality and current replenishment-window ramp
- spike normalization
- intermittent branch protection
- project-spike suppression
- regional handling
- non-stockable location blocks
- single-stocked-branch hold
- low-cost local deviation handling
- supplier minimum amount floors
- manual overrides

That means the engine is already a strong teacher even before any machine learning is added.

## What Should Stay Hard-Coded

These should generally remain explicit policy rules, not learned behavior:

- ignored statuses
- ignored location `9999`
- supplier DC overrides
- non-hub-managed suppliers
- `Regional` stocking policy
- `Stockable != Y` restrictions
- manual overrides
- supplier minimum amount floors
- location ordering
- minimum `28` day protection rule
- branch/DC alert rules

Why:

- these are business decisions
- they may change because management wants them changed
- they need to remain auditable

## What Is Worth Learning

These are the best candidates for machine learning:

- near-term demand
- expected demand over the current protection window
- seasonal shape
- product-group trend influence
- probability a demand pattern is intermittent
- probability a buyer later overrides the recommendation
- probability that a row is actually a non-replenishment signal

## Best Ways To Use The Current Engine

There are three realistic use cases.

## 1. Forecast + Rules

This is the best first production path.

Flow:

- train a demand model
- feed forecast demand into the current rules engine
- keep the final policy layer explicit

Best for:

- production safety
- explainability
- controlled rollout

## 2. Rule-Mimic Model

This trains a student model to reproduce the current engine's outputs.

Typical targets:

- `recommended_min_amount`
- `recommended_new_max`
- alert flags
- selected intermediate rule outputs

Best for:

- speed
- portability to another stack
- comparing a learned surrogate to the deterministic teacher

Main caution:

- if the feature set does not include enough policy context, the student will look unstable

## 3. Explanation / Review Model

This should not replace replenishment math.

Use it to:

- explain why the recommendation was made
- summarize which rules fired
- flag rows that deserve buyer review

This is a good place for an LLM.

## Recommended Targets

Do not create only one label.

Build a layered teacher dataset.

### Final-output targets

- `recommended_min_amount`
- `recommended_new_max`
- `recommended_min_delta`
- `recommendation_delta`

### Intermediate targets

- `filtered_mean`
- `filtered_std_dev`
- `reference_window_months`
- `seasonal_ramp_applied`
- `highest_outlier_removed`
- `two_point_spike_normalized`
- `intermittent_branch_protection_applied`
- `project_spike_suppressed`
- `single_period_pool_guard_applied`
- `regional_sparse_pool_suppressed`
- `dc_sparse_active_mean_fallback_applied`
- `deviation_pooled_to_dc`
- `deviation_absorbed_by_dc`

### Policy / alert targets

- `branch_zero_max_recommendation_alert`
- `dc_pooling_zero_max_alert`
- `regional_zero_max_branch_pool_applied`
- `non_stockable_location_blocked`
- `supplier_min_amount_floor_applied`
- `override_flag`

Why this matters:

- final targets tell you what the teacher decided
- intermediate targets tell you why

## Recommended Feature Groups

## 1. Raw demand history

Use:

- all 24 monthly columns
- rolling 3, 6, 12, and 24 month totals
- recent vs prior year totals
- non-zero month count
- top month value
- second-highest month value
- demand concentration ratios

## 2. Time-series structure

Use:

- month of year
- last non-zero month
- months since last demand
- item season
- planning season
- distance to seasonal peak

## 3. Intermittent-demand features

Use:

- ADI
- top-two-month share
- zero ratio
- highest month vs median of other active months
- highest month vs second-highest month

## 4. Policy features

Use:

- `Status`
- whether status contains `Regional`
- `ABC`
- service level percentage
- `Frequency`
- `Lead Time`
- computed protection days
- `MAC`
- `S. Min Amt`
- `Stockable`
- `Override`
- current `Min`
- current `Max`

## 5. Network features

Use:

- branch vs DC flag
- designated DC location
- number of stocked locations
- company item total demand
- branch share of company demand
- current DC min/max
- pooled variance to DC

## What To Learn First

If the programmers are starting from scratch, I would build these in order:

1. teacher-data exporter
2. baseline demand model
3. hybrid forecast + rules pipeline
4. rule-mimic model
5. explanation model

That order keeps the high-risk policy layer explicit while still letting the team improve demand quality.

## How To Generate Teacher Data From This Repo

The current repo already exposes the needed entry points.

### Workbook loading

Use [data_loader.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/deviation_dash/data_loader.py):

- `load_data_workbook(...)`

That returns:

- normalized data
- detected monthly columns

### Recommendation generation

Use [recommendations.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/deviation_dash/recommendations.py):

- `METHODS`
- `SeasonalityConfig`
- `calculate_method(...)`

Important return order:

- `detail` first
- `summary` second

### Example teacher extraction

```python
from datetime import date
from pathlib import Path

from deviation_dash.acceleration import detect_acceleration
from deviation_dash.data_loader import load_data_workbook
from deviation_dash.recommendations import (
    METHODS,
    SeasonalityConfig,
    calculate_method,
)

workbook_path = Path("DataV5.xlsx")
loaded = load_data_workbook(
    workbook_path.read_bytes(),
    source_name=workbook_path.name,
)

detail, summary = calculate_method(
    loaded.data,
    loaded.monthly_columns,
    METHODS[0],  # Active Demand with Active Variability
    seasonality=SeasonalityConfig(
        enabled=True,
        planning_season="Summer",
        as_of_date=date(2026, 3, 24),
    ),
    acceleration=detect_acceleration(prefer_gpu=False),
    forecast_lookup=None,
    service_levels=None,
    cheap_local_deviation_threshold=1.0,
    remove_highest_outlier_enabled=True,
    highest_outlier_threshold_pct=200.0,
)
```

## Version The Teacher Configuration

This is critical.

When building training data, always stamp the configuration used to create it:

- method key
- seasonality on/off
- planning season
- as-of date
- highest-month threshold
- cheap-local-deviation threshold
- service levels
- forecast mode
- code version / commit

Without this, the team will mix teacher outputs created under different business-rule settings and the dataset will become inconsistent.

## Evaluation Strategy

Do not evaluate only one number.

Use multiple views:

### Regression metrics

- MAE on `recommended_min_amount`
- MAE on `recommended_new_max`
- MAE on pooled DC amounts

### Classification metrics

- precision/recall for intermittent-demand flags
- precision/recall for project-spike suppression
- precision/recall for regional branch handling
- exact match rate for zero-max alerts

### Business metrics

- stockouts
- fill rate
- turns
- excess inventory
- buyer overrides after recommendation

## Recommended Modeling Patterns

## Pattern A: demand model + rules

Good first model choices:

- AutoGluon TimeSeries
- XGBoost / LightGBM on engineered features
- TFT or another sequence model if the team wants more complexity

Target options:

- next month usage
- next 2-3 month usage
- expected demand over protection days

## Pattern B: multi-head mimic model

A single model can predict:

- min
- max
- intermittent flag
- project-spike flag
- DC alert flags

This is useful as a surrogate, but it should still be compared against the teacher's intermediate logic.

## Pattern C: staged model family

Stage 1:

- classify item behavior

Stage 2:

- use specialized models for:
  - steady items
  - intermittent items
  - strongly seasonal items
  - regional items
  - sparse / edge-case items

This often works better than forcing one model to learn every behavior equally.

## What Not To Do

- Do not train only on final max with no rule context.
- Do not treat overrides as if they are ordinary demand.
- Do not mix teacher outputs from multiple configurations without versioning them.
- Do not judge success only by average numeric error.
- Do not replace hard policy rules with a black box too early.

## Best End State

The strongest long-term setup is likely:

- a learned demand model
- the current explicit business-rule layer
- an explanation / review layer on top
- buyer feedback logged for retraining

That gives the team:

- better forecasting
- safer policy control
- better explainability
- a stable way to compare model changes over time

## Practical Summary

If the programmers only remember the implementation strategy, it should be:

1. freeze a teacher configuration
2. generate teacher datasets from historical snapshots
3. learn demand first
4. keep policy explicit
5. train on both intermediate logic and final outputs
6. compare every learned model against both the teacher and real buyer behavior
