# Start Here for Programmers

## What this repo is

This repository contains the current Deviation Dash replenishment engine.

It is not just a dashboard. The important part is the deterministic inventory logic behind it:

- demand shaping
- seasonality
- spike suppression
- branch vs DC behavior
- stocking-footprint policy
- final min/max recommendation rules

## What to read first

Read these in order:

1. [README.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/README.md)
2. [model_overview_for_programmers.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/docs/model_overview_for_programmers.md)
3. [representative_model_variations_for_ai_team.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/docs/representative_model_variations_for_ai_team.md)
4. [how_to_train_other_models_from_deviation_dash.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/docs/how_to_train_other_models_from_deviation_dash.md)

## Main files

- [app.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/app.py)
  - Streamlit dashboard and UI behavior
- [recommendations.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/deviation_dash/recommendations.py)
  - core replenishment logic
- [data_loader.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/deviation_dash/data_loader.py)
  - workbook import and normalization
- [autogluon_integration.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/deviation_dash/autogluon_integration.py)
  - optional forecast integration

## How to think about the model

The best mental model is:

- demand estimator
- then spike/sparse-demand protection
- then branch/DC allocation rules
- then hard business-policy floors and blocks

That means the final recommendation is not a pure forecast.

## Implementation advice

- Do not try to rebuild this as one monolithic black-box predictor first.
- Reproduce the intermediate rule decisions before comparing final min/max.
- Treat policy rules as policy, not as demand.
- Use the current engine as a teacher if you plan to train a new model.

## Current source-of-truth setup

The current main explanation set is based on:

- workbook: `DataV5.xlsx`
- method: `Active Demand with Active Variability`
- seasonality: `Summer`
- as-of date: `2026-03-24`
- highest-month normalization: on

If you compare outputs, make sure you are comparing against the same configuration.
