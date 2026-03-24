# Deviation Dash

Chrome-friendly replenishment dashboard for reviewing raw item/location demand and recommendation outputs.

## What this version does

- Imports the `Data` tab from the raw Excel workbook.
- Runs the current replenishment rule engine, with `Active Demand with Active Variability` as the primary production method.
- Shows supplier-aware item summaries and location-level recommendations.
- Adds supplier-level ranking so you can see which suppliers have the biggest overall changes first.
- Lets you drill into one item at a time to inspect monthly demand, intermediate calculations, and the balancing-location logic.
- Ignores `Service`, `Special`, `Inactive`, `Ok to Sell Below Cost`, `Substitute`, and `Exception` items, plus `Stock` rows with no max.
- Treats `Local` frequency as a 4-week supplier cycle.
- Blends bounded product-group trend signals into the item mean before rounding.
- Detects an NVIDIA GPU and will use `cuDF` automatically for large aggregation steps when it is installed.
- Can optionally switch from `Rules Only` to `AI Forecast + Rules` when a saved AutoGluon forecast artifact exists.

## Assumptions in this first build

- The raw workbook matches the current `Data` tab shape from `Deviation.xlsx`.
- Locations are evaluated in this order: `1, 30, 40, 115, 116, 117, 118, 119`.
- The first location in that ordered set acts as the balancing location, matching the Excel model tab pattern.
- Recommendations are grouped by `Supplier + Item`, so multiple suppliers can be loaded in the same file.
- Product-group trends prefer `Supplier + Prod Group` history and fall back to all-supplier `Prod Group` history when needed.

## Programmer Guides

The main technical docs are:

- [docs/model_overview_for_programmers.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/docs/model_overview_for_programmers.md)
- [docs/representative_model_variations_for_ai_team.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/docs/representative_model_variations_for_ai_team.md)
- [docs/how_to_train_other_models_from_deviation_dash.md](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/docs/how_to_train_other_models_from_deviation_dash.md)

Suggested reading order:

1. model overview
2. representative cases
3. training guide

## Run locally on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run app.py
```

Then open the local URL Streamlit prints in Chrome.

## Optional GPU acceleration

If `cuDF` is installed in the virtual environment, the app will detect your NVIDIA GPU automatically and use it for the heaviest aggregation steps. Without `cuDF`, the app stays on pandas/CPU and still runs normally.

## Optional cuDF on Windows

RAPIDS/cuDF is supported on this machine through WSL2 rather than native Windows Python.

Current status on this workstation:
- WSL and Ubuntu were installed successfully.
- Windows reported that a reboot is required before WSL2 becomes usable.
- BIOS virtualization is already enabled on this machine.

After reboot:
1. Open Ubuntu once from the Start menu and finish the first-time Linux username/password setup.
2. Run:

```powershell
.\setup_cudf_wsl.bat
```

That will install Miniforge inside Ubuntu, create a `rapids` conda environment, install `cudf`, and verify the import.

## Optional AutoGluon forecasting

Use AutoGluon as a demand forecast layer, then let the dashboard keep applying the replenishment rules.

1. Install the optional forecasting dependency:

```powershell
.\install_autogluon.bat
```

If you want AutoGluon to train on your NVIDIA GPU instead of CPU, run:

```powershell
.\install_autogluon_gpu.bat
```

2. Train the model from a workbook:

```powershell
.\train_autogluon.bat "D:\path\to\Data.xlsx"
```

3. Restart the dashboard:

```powershell
.\run_dashboard.bat
```

When a saved forecast exists in `models\autogluon`, the sidebar will offer `Use AI Forecast + Rules`. The current integration uses AutoGluon to forecast monthly demand for each `supplier + item + location`, then feeds that demand into the existing stocking rules.

### AutoGluon GPU notes

- Your Windows machine can use the GPU for AutoGluon training if PyTorch is installed with CUDA support.
- This project's GPU installer switches the dashboard virtual environment to the official PyTorch `cu126` wheels, which matches current NVIDIA drivers like yours.
- The installer keeps `numpy` pinned below `2.2` so the AutoGluon time-series stack stays compatible.
- You can verify the install with:

```powershell
.\.venv\Scripts\python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No GPU')"
```

## One-click launcher

Double-click [run_dashboard.bat](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/run_dashboard.bat) to:

- create the virtual environment if it does not exist
- install/update requirements
- start the Streamlit server on `http://localhost:8501`
- open the dashboard in Chrome when Chrome is installed in a standard location

## AutoGluon files

- [install_autogluon.bat](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/install_autogluon.bat) installs the optional AutoGluon dependency into the dashboard virtual environment.
- [train_autogluon.bat](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/train_autogluon.bat) trains a model and saves forecast artifacts locally.
- [train_autogluon.py](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/train_autogluon.py) is the underlying training entrypoint.
- [requirements-autogluon.txt](D:/OneDrive%20-%20R&E%20Supply/Apps/Deviation%20Dash/requirements-autogluon.txt) contains the optional forecasting dependency list.
