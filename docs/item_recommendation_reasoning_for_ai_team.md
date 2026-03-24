# Item Recommendation Reasoning Guide for the AI Team

## Scope

- Source workbook: `DataV3.xlsx`.
- Requested item list: the screenshot prefixes were matched to the exact item codes below.
- Recommendation method: `Active Demand with Active Variability`.
- Forecast mode: `Rules Only` (no AutoGluon forecast blended in for this report).
- Seasonality: enabled, planning season `Summer`, so only April through September demand is considered relevant for the active seasonal window.
- Service levels used by the calculation: `A=99%`, `B=92%`, `C=88%`, `D=84%`, `E=80%`, `X=80%`.
- Location `1` is treated as the DC plus a stocking location. Locations `115`, `116`, `117`, `118`, `119`, `30`, and `40` are branches. Location `9999` is ignored.

## Screenshot Match List

| Screenshot text | Matched item code |
| --- | --- |
| `R-134A-30` | `R-134A-30LB-REFG` |
| `R-22-30LB` | `R-22-30LB-REFG` |
| `R-427A-25` | `R-427A-25LB-REFG` |
| `R-404A-10...` | `R-404A-100LB-REFG` |
| `R-417C-25` | `R-417C-25LB-REFG` |
| `R-407C-25` | `R-407C-25LB-REFG` |
| `R-410A-25` | `R-410A-25LB-REFG` |
| `R-422B-25` | `R-422B-25LB-REFG` |
| `R-422D-25` | `R-422D-25LB-REFG` |
| `R-448A-25` | `R-448A-25LB-REFG` |
| `R-449A-25` | `R-449A-25LB-REFG` |
| `R-290-10.6` | `R-290-10.6OZ-REFG` |
| `R-600-10.6` | `R-600-10.6OZ-REFG` |
| `R-407A-25` | `R-407A-25LB-REFG` |
| `R-32-20LB` | `R-32-20LB-REFG` |
| `R-404A-24...` | `R-404A-24LB-REFG` |
| `R-421A-25` | `R-421A-25LB-REFG` |
| `R-438A-25` | `R-438A-25LB-REFG` |
| `R-507-25L...` | `R-507-25LB-REFG` |

## Plain-English Rule Order

1. Ignore rows that should never drive replenishment: ignored statuses, `Stock with no Max`, and location `9999`.
2. Pick the history window. If year-over-year demand is between `-33%` and `+33%`, use both years. Otherwise use the last 12 months.
3. Apply seasonality. Because this report is for `Summer`, the usable months are only April through September inside the chosen history window.
4. Build the demand signal. In `Active Demand with Active Variability`, the mean and the standard deviation both ignore zero-demand months.
5. Blend in the product-group trend. The item mean is nudged up or down based on how the item's product group has been moving recently, but the adjustment is capped so it cannot overwhelm the item's own history.
6. Detect intermittent branch demand. For branch locations, if demand is too sparse or too concentrated in only one or two months, the model stops treating those few sales as steady branch demand. Instead it falls back to the inclusive seasonal mean and pushes the extra spike stock back to the DC.
7. Convert monthly demand into protection days. Protection days are `lead time + supplier order frequency`, with a floor of `28` days. If frequency is `Local`, the model treats it as `28` days.
8. Set the branch minimum. Branch mins are demand-only coverage. They do not hold large variability buffers.
9. Set the branch maximum. Branch maxes use the effective branch demand signal, but branch variability is not kept locally. That deviation is pooled into the DC.
10. Set the DC minimum. Location `1` only keeps enough min stock for its own demand between replenishment cycles.
11. Set the DC maximum. The DC/balancing location absorbs pooled branch deviation and intermittent spike stock, then is floored to the policy order-up-to level driven by lead time, frequency, and ABC service level.
12. Respect overrides. If `Override = Y`, the current max wins and the row is flagged as an override.

## What the programmers should mirror

- Treat this as a hybrid of deterministic rules plus demand estimation, not as a pure black-box forecast.
- The most important branch-vs-DC behavior is: branches hold demand-only working stock, while the DC carries the pooled uncertainty.
- The most important outlier protection is the intermittent branch rule. That is what stops a branch from looking like it steadily needs `16` just because it sold `16` in one or two isolated months.
- If the AI team wants to learn from this engine, the best training targets are the final `recommended_min_amount` and `recommended_new_max`, while the best explanatory features are the intermediate fields shown in the item sections below.

## Item-by-Item Reasoning

### A-GAS REFRIGERANTS | R-134A-30LB-REFG | HFC134A

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `7` days | planning season `Summer`
- Reference window: `24` months | YOY `-4.0%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.00x` from `Global product group`
- Company total min: `27` -> `21` | company total max: `44` -> `115`
- Pooled to DC: `53.50` | absorbed by DC: `53.50` | changed locations: `7` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `3` | `9` | `12` | `77` | `9.55` | `9.55` | `13.09` | `0.00` | `53.50` |
| `115` | `2` | `1` | `3` | `4` | `4.27` | `4.27` | `3.12` | `7.00` | `0.00` |
| `116` | `7` | `2` | `9` | `9` | `8.67` | `8.67` | `6.13` | `14.00` | `0.00` |
| `117` | `4` | `2` | `5` | `8` | `8.33` | `8.33` | `4.99` | `11.00` | `0.00` |
| `118` | `4` | `2` | `5` | `6` | `5.67` | `5.67` | `2.46` | `6.00` | `0.00` |
| `119` | `3` | `1` | `4` | `1` | `0.50` | `2.00` | `0.50` | `3.50` | `0.00` |
| `30` | `1` | `2` | `2` | `5` | `4.91` | `4.91` | `3.34` | `8.00` | `0.00` |
| `40` | `3` | `2` | `4` | `5` | `4.40` | `4.40` | `2.25` | `4.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `3` / `12` change to `9` / `77`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `53.50` units of pooled branch uncertainty and is floored to policy order-up-to `39`. The protection window was floored up to `28` days from a raw `21` days.
- `115`: Branch location. Current min/max `2` / `3` change to `1` / `4`. The branch uses an effective demand basis of `4.27` and a variability amount of `3.12` to size the branch target, but the branch only keeps demand-only coverage. `7.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `116`: Branch location. Current min/max `7` / `9` change to `2` / `9`. The branch uses an effective demand basis of `8.67` and a variability amount of `6.13` to size the branch target, but the branch only keeps demand-only coverage. `14.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `117`: Branch location. Current min/max `4` / `5` change to `2` / `8`. The branch uses an effective demand basis of `8.33` and a variability amount of `4.99` to size the branch target, but the branch only keeps demand-only coverage. `11.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `118`: Branch location. Current min/max `4` / `5` change to `2` / `6`. The branch uses an effective demand basis of `5.67` and a variability amount of `2.46` to size the branch target, but the branch only keeps demand-only coverage. `6.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `119`: Branch location. Current min/max `3` / `4` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.00` was reduced to `0.50` because ADI is 4.0, the top two months account for 83% of scoped demand. `1.50` units of spike stock and `3.50` total branch deviation were pushed back to the DC. The protection window was floored up to `28` days from a raw `21` days.
- `30`: Branch location. Current min/max `1` / `2` change to `2` / `5`. The branch uses an effective demand basis of `4.91` and a variability amount of `3.34` to size the branch target, but the branch only keeps demand-only coverage. `8.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `40`: Branch location. Current min/max `3` / `4` change to `2` / `5`. The branch uses an effective demand basis of `4.40` and a variability amount of `2.25` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.

### A-GAS REFRIGERANTS | R-22-30LB-REFG | REFRIGERANT HCFC

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `7` days | planning season `Summer`
- Reference window: `24` months | YOY `-11.4%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.00x` from `No product-group trend`
- Company total min: `16` -> `18` | company total max: `41` -> `90`
- Pooled to DC: `44.00` | absorbed by DC: `44.00` | changed locations: `5` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `6` | `7` | `24` | `58` | `7.50` | `7.50` | `6.11` | `0.00` | `44.00` |
| `115` | `1` | `1` | `2` | `2` | `2.00` | `2.00` | `0.89` | `2.00` | `0.00` |
| `116` | `2` | `3` | `3` | `9` | `8.70` | `8.70` | `4.44` | `10.00` | `0.00` |
| `117` | `1` | `2` | `2` | `6` | `5.50` | `5.50` | `3.23` | `8.00` | `0.00` |
| `118` | `2` | `1` | `3` | `3` | `2.73` | `2.73` | `1.68` | `4.00` | `0.00` |
| `119` | `1` | `1` | `2` | `2` | `1.57` | `1.57` | `0.71` | `2.00` | `0.00` |
| `30` | `1` | `1` | `2` | `4` | `3.40` | `3.40` | `2.86` | `5.00` | `0.00` |
| `40` | `2` | `2` | `3` | `6` | `6.18` | `6.18` | `5.71` | `13.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `6` / `24` change to `7` / `58`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `44.00` units of pooled branch uncertainty and is floored to policy order-up-to `22`. The protection window was floored up to `28` days from a raw `21` days.
- `115`: Branch location. Current min/max `1` / `2` change to `1` / `2`. The branch uses an effective demand basis of `2.00` and a variability amount of `0.89` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `116`: Branch location. Current min/max `2` / `3` change to `3` / `9`. The branch uses an effective demand basis of `8.70` and a variability amount of `4.44` to size the branch target, but the branch only keeps demand-only coverage. `10.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `117`: Branch location. Current min/max `1` / `2` change to `2` / `6`. The branch uses an effective demand basis of `5.50` and a variability amount of `3.23` to size the branch target, but the branch only keeps demand-only coverage. `8.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `118`: Branch location. Current min/max `2` / `3` change to `1` / `3`. The branch uses an effective demand basis of `2.73` and a variability amount of `1.68` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `119`: Branch location. Current min/max `1` / `2` change to `1` / `2`. The branch uses an effective demand basis of `1.57` and a variability amount of `0.71` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `30`: Branch location. Current min/max `1` / `2` change to `1` / `4`. The branch uses an effective demand basis of `3.40` and a variability amount of `2.86` to size the branch target, but the branch only keeps demand-only coverage. `5.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `40`: Branch location. Current min/max `2` / `3` change to `2` / `6`. The branch uses an effective demand basis of `6.18` and a variability amount of `5.71` to size the branch target, but the branch only keeps demand-only coverage. `13.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.

### ARKEMA, INC. | R-427A-25LB-REFG | R-22-REPLACEMENT

- Profile: ABC `C` at `88%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `12` months | YOY `-46.3%` | rule: Year-over-year demand moved outside +/-33%, so the model uses the last 12 months.
- Product-group trend: `Flat` at `0.99x` from `Global product group`
- Company total min: `7` -> `4` | company total max: `33` -> `16`
- Pooled to DC: `10.13` | absorbed by DC: `10.13` | changed locations: `3` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `2` | `1` | `22` | `11` | `1.00` | `1.00` | `-0.01` | `0.00` | `10.13` |
| `115` | `0` | `1` | `1` | `1` | `0.17` | `1.00` | `0.17` | `0.83` | `0.00` |
| `116` | `1` | `0` | `2` | `1` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `117` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `118` | `4` | `1` | `6` | `1` | `0.83` | `2.50` | `1.95` | `4.65` | `0.00` |
| `119` | `0` | `0` | `1` | `1` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `30` | `0` | `1` | `1` | `1` | `0.83` | `2.50` | `1.95` | `4.65` | `0.00` |
| `40` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `2` / `22` change to `1` / `11`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `10.13` units of pooled branch uncertainty and is floored to policy order-up-to `1`.
- `115`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.17` because it only sold in 1 of 6 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `0.83` units of spike stock and `0.83` total branch deviation were pushed back to the DC.
- `116`: Branch location. Current min/max `1` / `2` change to `0` / `1`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `4` / `6` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.50` was reduced to `0.83` because it only sold in 2 of 6 scoped months, the top two months account for 100% of scoped demand. `1.65` units of spike stock and `4.65` total branch deviation were pushed back to the DC.
- `119`: Branch location. Current min/max `0` / `1` change to `0` / `1`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.50` was reduced to `0.83` because it only sold in 2 of 6 scoped months, the top two months account for 100% of scoped demand. `1.65` units of spike stock and `4.65` total branch deviation were pushed back to the DC.
- `40`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### CHEMOURS | R-404A-100LB-REFG | HP-62

- Profile: ABC `D` at `84%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `12` months | YOY `100.0%` | rule: Year-over-year demand moved outside +/-33%, so the model uses the last 12 months.
- Product-group trend: `Flat` at `1.00x` from `Supplier product group`
- Company total min: `0` -> `1` | company total max: `1` -> `4`
- Pooled to DC: `2.50` | absorbed by DC: `2.50` | changed locations: `2` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `0` | `0` | `1` | `3` | `0.00` | `0.00` | `0.00` | `0.00` | `2.50` |
| `115` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `116` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `117` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `118` | `0` | `1` | `0` | `1` | `0.50` | `3.00` | `-0.50` | `2.50` | `0.00` |
| `119` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `30` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `40` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `0` / `1` change to `0` / `3`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `2.50` units of pooled branch uncertainty and is floored to policy order-up-to `0`.
- `115`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `0` / `0` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `3.00` was reduced to `0.50` because it only sold in 1 of 6 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `2.50` units of spike stock and `2.50` total branch deviation were pushed back to the DC.
- `119`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### CHEMOURS | R-417C-25LB-REFG | HOT SHOT TWO R-12 MP-39 R134A R500

- Profile: ABC `C` at `88%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `-21.4%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Down` at `0.85x` from `Supplier product group`
- Company total min: `5` -> `7` | company total max: `28` -> `10`
- Pooled to DC: `6.75` | absorbed by DC: `6.75` | changed locations: `4` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `2` | `2` | `20` | `3` | `1.00` | `1.00` | `-0.15` | `0.00` | `6.75` |
| `115` | `0` | `1` | `1` | `1` | `0.25` | `1.50` | `0.92` | `2.06` | `0.00` |
| `116` | `1` | `1` | `2` | `1` | `0.25` | `3.00` | `0.21` | `2.34` | `0.00` |
| `117` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `118` | `1` | `1` | `2` | `2` | `1.25` | `1.25` | `0.56` | `1.00` | `0.00` |
| `119` | `0` | `0` | `1` | `1` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `30` | `1` | `1` | `2` | `1` | `0.25` | `1.00` | `0.21` | `0.64` | `0.00` |
| `40` | `0` | `1` | `0` | `1` | `0.17` | `1.00` | `0.14` | `0.71` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `2` / `20` change to `2` / `3`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `6.75` units of pooled branch uncertainty and is floored to policy order-up-to `2`.
- `115`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.50` was reduced to `0.25` because it only sold in 2 of 12 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `1.06` units of spike stock and `2.06` total branch deviation were pushed back to the DC.
- `116`: Branch location. Current min/max `1` / `2` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `3.00` was reduced to `0.25` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `2.34` units of spike stock and `2.34` total branch deviation were pushed back to the DC.
- `117`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `1` / `2` change to `1` / `2`. The branch uses an effective demand basis of `1.25` and a variability amount of `0.56` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `0` / `1` change to `0` / `1`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `1` / `2` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.25` because ADI is 4.0. `0.64` units of spike stock and `0.64` total branch deviation were pushed back to the DC.
- `40`: Branch location. Current min/max `0` / `0` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.17` because it only sold in 2 of 12 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `0.71` units of spike stock and `0.71` total branch deviation were pushed back to the DC.

### HUDSON TECHNOLOGIES COMPANY | R-407C-25LB-REFG | 407C SUVA REPLACE R-22

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `-16.7%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Down` at `0.96x` from `Supplier product group`
- Company total min: `34` -> `132` | company total max: `74` -> `282`
- Pooled to DC: `139.00` | absorbed by DC: `139.00` | changed locations: `8` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `9` | `44` | `38` | `151` | `33.00` | `33.00` | `18.00` | `0.00` | `139.00` |
| `115` | `4` | `9` | `5` | `14` | `9.92` | `9.92` | `5.27` | `15.00` | `0.00` |
| `116` | `4` | `11` | `6` | `16` | `11.50` | `11.50` | `4.97` | `13.00` | `0.00` |
| `117` | `5` | `20` | `7` | `29` | `21.75` | `21.75` | `8.47` | `24.00` | `0.00` |
| `118` | `4` | `12` | `6` | `18` | `13.25` | `13.25` | `6.47` | `18.00` | `0.00` |
| `119` | `1` | `7` | `2` | `10` | `7.42` | `7.42` | `6.47` | `18.00` | `0.00` |
| `30` | `4` | `14` | `6` | `21` | `15.33` | `15.33` | `9.35` | `26.00` | `0.00` |
| `40` | `3` | `15` | `4` | `23` | `16.83` | `16.83` | `9.54` | `25.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `9` / `38` change to `44` / `151`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `139.00` units of pooled branch uncertainty and is floored to policy order-up-to `94`.
- `115`: Branch location. Current min/max `4` / `5` change to `9` / `14`. The branch uses an effective demand basis of `9.92` and a variability amount of `5.27` to size the branch target, but the branch only keeps demand-only coverage. `15.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `4` / `6` change to `11` / `16`. The branch uses an effective demand basis of `11.50` and a variability amount of `4.97` to size the branch target, but the branch only keeps demand-only coverage. `13.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `5` / `7` change to `20` / `29`. The branch uses an effective demand basis of `21.75` and a variability amount of `8.47` to size the branch target, but the branch only keeps demand-only coverage. `24.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `4` / `6` change to `12` / `18`. The branch uses an effective demand basis of `13.25` and a variability amount of `6.47` to size the branch target, but the branch only keeps demand-only coverage. `18.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `1` / `2` change to `7` / `10`. The branch uses an effective demand basis of `7.42` and a variability amount of `6.47` to size the branch target, but the branch only keeps demand-only coverage. `18.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `4` / `6` change to `14` / `21`. The branch uses an effective demand basis of `15.33` and a variability amount of `9.35` to size the branch target, but the branch only keeps demand-only coverage. `26.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `3` / `4` change to `15` / `23`. The branch uses an effective demand basis of `16.83` and a variability amount of `9.54` to size the branch target, but the branch only keeps demand-only coverage. `25.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### HUDSON TECHNOLOGIES COMPANY | R-410A-25LB-REFG | REFRIGERANT HFC

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `-25.0%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.00x` from `No product-group trend`
- Company total min: `192` -> `596` | company total max: `356` -> `1,407`
- Pooled to DC: `726.00` | absorbed by DC: `726.00` | changed locations: `8` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `36` | `126` | `159` | `702` | `90.83` | `90.83` | `38.18` | `0.00` | `726.00` |
| `115` | `19` | `70` | `24` | `104` | `75.25` | `75.25` | `45.34` | `124.00` | `0.00` |
| `116` | `43` | `98` | `54` | `147` | `105.83` | `105.83` | `80.29` | `219.00` | `0.00` |
| `117` | `25` | `65` | `32` | `98` | `70.58` | `70.58` | `14.38` | `40.00` | `0.00` |
| `118` | `10` | `33` | `13` | `50` | `35.58` | `35.58` | `32.66` | `90.00` | `0.00` |
| `119` | `16` | `29` | `20` | `43` | `31.08` | `31.08` | `23.98` | `66.00` | `0.00` |
| `30` | `20` | `91` | `25` | `137` | `98.75` | `98.75` | `34.13` | `94.00` | `0.00` |
| `40` | `23` | `84` | `29` | `126` | `90.83` | `90.83` | `34.08` | `93.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `36` / `159` change to `126` / `702`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `726.00` units of pooled branch uncertainty and is floored to policy order-up-to `231`.
- `115`: Branch location. Current min/max `19` / `24` change to `70` / `104`. The branch uses an effective demand basis of `75.25` and a variability amount of `45.34` to size the branch target, but the branch only keeps demand-only coverage. `124.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `43` / `54` change to `98` / `147`. The branch uses an effective demand basis of `105.83` and a variability amount of `80.29` to size the branch target, but the branch only keeps demand-only coverage. `219.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `25` / `32` change to `65` / `98`. The branch uses an effective demand basis of `70.58` and a variability amount of `14.38` to size the branch target, but the branch only keeps demand-only coverage. `40.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `10` / `13` change to `33` / `50`. The branch uses an effective demand basis of `35.58` and a variability amount of `32.66` to size the branch target, but the branch only keeps demand-only coverage. `90.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `16` / `20` change to `29` / `43`. The branch uses an effective demand basis of `31.08` and a variability amount of `23.98` to size the branch target, but the branch only keeps demand-only coverage. `66.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `20` / `25` change to `91` / `137`. The branch uses an effective demand basis of `98.75` and a variability amount of `34.13` to size the branch target, but the branch only keeps demand-only coverage. `94.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `23` / `29` change to `84` / `126`. The branch uses an effective demand basis of `90.83` and a variability amount of `34.08` to size the branch target, but the branch only keeps demand-only coverage. `93.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### HUDSON TECHNOLOGIES COMPANY | R-422B-25LB-REFG | NU-22B REFRIGERANT R-22 REPLMNT

- Profile: ABC `B` at `92%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `-5.6%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Down` at `0.96x` from `Supplier product group`
- Company total min: `7` -> `21` | company total max: `20` -> `30`
- Pooled to DC: `11.96` | absorbed by DC: `11.96` | changed locations: `6` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `2` | `5` | `8` | `10` | `3.64` | `3.64` | `2.95` | `0.00` | `11.96` |
| `115` | `1` | `2` | `2` | `2` | `1.20` | `1.20` | `0.60` | `1.00` | `0.00` |
| `116` | `0` | `2` | `1` | `3` | `1.80` | `1.80` | `0.57` | `1.00` | `0.00` |
| `117` | `0` | `1` | `1` | `1` | `0.33` | `1.33` | `0.90` | `1.96` | `0.00` |
| `118` | `0` | `2` | `1` | `2` | `1.33` | `1.33` | `0.80` | `1.00` | `0.00` |
| `119` | `2` | `3` | `3` | `4` | `2.33` | `2.33` | `1.75` | `2.00` | `0.00` |
| `30` | `1` | `2` | `2` | `3` | `2.00` | `2.00` | `0.59` | `1.00` | `0.00` |
| `40` | `1` | `4` | `2` | `5` | `3.67` | `3.67` | `1.94` | `4.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `2` / `8` change to `5` / `10`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `11.96` units of pooled branch uncertainty and is floored to policy order-up-to `9`.
- `115`: Branch location. Current min/max `1` / `2` change to `2` / `2`. The branch uses an effective demand basis of `1.20` and a variability amount of `0.60` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `0` / `1` change to `2` / `3`. The branch uses an effective demand basis of `1.80` and a variability amount of `0.57` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.33` was reduced to `0.33` because ADI is 4.0, the top two months account for 75% of scoped demand. `0.96` units of spike stock and `1.96` total branch deviation were pushed back to the DC.
- `118`: Branch location. Current min/max `0` / `1` change to `2` / `2`. The branch uses an effective demand basis of `1.33` and a variability amount of `0.80` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `2` / `3` change to `3` / `4`. The branch uses an effective demand basis of `2.33` and a variability amount of `1.75` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `1` / `2` change to `2` / `3`. The branch uses an effective demand basis of `2.00` and a variability amount of `0.59` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `1` / `2` change to `4` / `5`. The branch uses an effective demand basis of `3.67` and a variability amount of `1.94` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### HUDSON TECHNOLOGIES COMPANY | R-422D-25LB-REFG | MO29 REFRIGERANT R-22 REPLMNT

- Profile: ABC `B` at `92%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `12.1%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Down` at `0.96x` from `Supplier product group`
- Company total min: `6` -> `18` | company total max: `21` -> `35`
- Pooled to DC: `13.96` | absorbed by DC: `13.96` | changed locations: `4` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `1` | `8` | `11` | `23` | `6.00` | `6.00` | `8.42` | `0.00` | `13.96` |
| `115` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `116` | `0` | `1` | `1` | `1` | `0.25` | `1.00` | `0.24` | `0.72` | `0.00` |
| `117` | `3` | `2` | `4` | `2` | `1.17` | `3.50` | `3.23` | `7.24` | `0.00` |
| `118` | `1` | `2` | `2` | `2` | `1.20` | `1.20` | `0.60` | `1.00` | `0.00` |
| `119` | `0` | `1` | `1` | `2` | `1.00` | `1.00` | `-0.04` | `0.00` | `0.00` |
| `30` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `40` | `1` | `4` | `2` | `5` | `3.60` | `3.60` | `3.05` | `5.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `1` / `11` change to `8` / `23`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `13.96` units of pooled branch uncertainty and is floored to policy order-up-to `23`.
- `115`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.25` because ADI is 4.0. `0.72` units of spike stock and `0.72` total branch deviation were pushed back to the DC.
- `117`: Branch location. Current min/max `3` / `4` change to `2` / `2`. Intermittent branch protection fired, so the raw active-demand mean `3.50` was reduced to `1.17` because the top two months account for 79% of scoped demand. `2.24` units of spike stock and `7.24` total branch deviation were pushed back to the DC.
- `118`: Branch location. Current min/max `1` / `2` change to `2` / `2`. The branch uses an effective demand basis of `1.20` and a variability amount of `0.60` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `0` / `1` change to `1` / `2`. The branch uses an effective demand basis of `1.00` and a variability amount of `-0.04` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `1` / `2` change to `4` / `5`. The branch uses an effective demand basis of `3.60` and a variability amount of `3.05` to size the branch target, but the branch only keeps demand-only coverage. `5.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### HUDSON TECHNOLOGIES COMPANY | R-448A-25LB-REFG | REFRIGERANT HFO 25LB CYLINDER

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `-9.8%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Down` at `0.96x` from `Supplier product group`
- Company total min: `23` -> `29` | company total max: `44` -> `63`
- Pooled to DC: `33.88` | absorbed by DC: `33.88` | changed locations: `6` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `4` | `6` | `15` | `32` | `4.40` | `4.40` | `3.29` | `0.00` | `33.88` |
| `115` | `1` | `2` | `2` | `2` | `1.29` | `1.29` | `0.72` | `2.00` | `0.00` |
| `116` | `1` | `2` | `2` | `3` | `2.11` | `2.11` | `1.56` | `4.00` | `0.00` |
| `117` | `5` | `5` | `7` | `7` | `4.75` | `4.75` | `3.21` | `10.00` | `0.00` |
| `118` | `9` | `8` | `12` | `11` | `8.25` | `8.25` | `3.06` | `9.00` | `0.00` |
| `119` | `1` | `1` | `2` | `1` | `0.08` | `1.00` | `0.08` | `0.88` | `0.00` |
| `30` | `1` | `2` | `2` | `3` | `2.00` | `2.00` | `1.15` | `3.00` | `0.00` |
| `40` | `1` | `3` | `2` | `4` | `2.75` | `2.75` | `1.41` | `5.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `4` / `15` change to `6` / `32`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `33.88` units of pooled branch uncertainty and is floored to policy order-up-to `15`.
- `115`: Branch location. Current min/max `1` / `2` change to `2` / `2`. The branch uses an effective demand basis of `1.29` and a variability amount of `0.72` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `1` / `2` change to `2` / `3`. The branch uses an effective demand basis of `2.11` and a variability amount of `1.56` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `5` / `7` change to `5` / `7`. The branch uses an effective demand basis of `4.75` and a variability amount of `3.21` to size the branch target, but the branch only keeps demand-only coverage. `10.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `9` / `12` change to `8` / `11`. The branch uses an effective demand basis of `8.25` and a variability amount of `3.06` to size the branch target, but the branch only keeps demand-only coverage. `9.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `1` / `2` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.08` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `0.88` units of spike stock and `0.88` total branch deviation were pushed back to the DC.
- `30`: Branch location. Current min/max `1` / `2` change to `2` / `3`. The branch uses an effective demand basis of `2.00` and a variability amount of `1.15` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `1` / `2` change to `3` / `4`. The branch uses an effective demand basis of `2.75` and a variability amount of `1.41` to size the branch target, but the branch only keeps demand-only coverage. `5.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### HUDSON TECHNOLOGIES COMPANY | R-449A-25LB-REFG | OPTEON XP40

- Profile: ABC `B` at `92%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `28` days | planning season `Summer`
- Reference window: `24` months | YOY `-30.0%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Down` at `0.96x` from `Supplier product group`
- Company total min: `11` -> `15` | company total max: `40` -> `24`
- Pooled to DC: `11.28` | absorbed by DC: `11.28` | changed locations: `6` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `3` | `5` | `25` | `11` | `3.50` | `3.50` | `2.26` | `0.00` | `11.28` |
| `115` | `2` | `1` | `3` | `1` | `0.25` | `1.00` | `0.24` | `0.72` | `0.00` |
| `116` | `1` | `2` | `2` | `3` | `1.83` | `1.83` | `0.74` | `2.00` | `0.00` |
| `117` | `1` | `1` | `2` | `1` | `0.17` | `1.00` | `0.16` | `0.80` | `0.00` |
| `118` | `2` | `1` | `3` | `2` | `1.00` | `1.00` | `1.37` | `2.00` | `0.00` |
| `119` | `0` | `1` | `1` | `1` | `0.17` | `2.00` | `0.16` | `1.76` | `0.00` |
| `30` | `1` | `2` | `2` | `3` | `2.20` | `2.20` | `1.15` | `2.00` | `0.00` |
| `40` | `1` | `2` | `2` | `2` | `1.50` | `1.50` | `1.20` | `2.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `3` / `25` change to `5` / `11`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `11.28` units of pooled branch uncertainty and is floored to policy order-up-to `8`.
- `115`: Branch location. Current min/max `2` / `3` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.25` because ADI is 4.0. `0.72` units of spike stock and `0.72` total branch deviation were pushed back to the DC.
- `116`: Branch location. Current min/max `1` / `2` change to `2` / `3`. The branch uses an effective demand basis of `1.83` and a variability amount of `0.74` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `1` / `2` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.17` because it only sold in 2 of 12 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `0.80` units of spike stock and `0.80` total branch deviation were pushed back to the DC.
- `118`: Branch location. Current min/max `2` / `3` change to `1` / `2`. The branch uses an effective demand basis of `1.00` and a variability amount of `1.37` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.00` was reduced to `0.17` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `1.76` units of spike stock and `1.76` total branch deviation were pushed back to the DC.
- `30`: Branch location. Current min/max `1` / `2` change to `2` / `3`. The branch uses an effective demand basis of `2.20` and a variability amount of `1.15` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `1` / `2` change to `2` / `2`. The branch uses an effective demand basis of `1.50` and a variability amount of `1.20` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### NU-CALGON | R-290-10.6OZ-REFG | R-290-10.6OZ CAN

- Profile: ABC `B` at `92%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `24` months | YOY `14.9%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Up` at `1.11x` from `Supplier product group`
- Company total min: `43` -> `21` | company total max: `56` -> `56`
- Pooled to DC: `20.01` | absorbed by DC: `20.01` | changed locations: `6` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `11` | `5` | `14` | `28` | `4.73` | `4.73` | `3.30` | `0.00` | `20.01` |
| `115` | `7` | `3` | `8` | `5` | `4.73` | `4.73` | `3.16` | `4.00` | `0.00` |
| `116` | `8` | `3` | `10` | `5` | `4.58` | `4.58` | `2.22` | `3.00` | `0.00` |
| `117` | `2` | `2` | `3` | `4` | `3.11` | `3.11` | `2.81` | `3.00` | `0.00` |
| `118` | `7` | `3` | `9` | `6` | `5.36` | `5.36` | `2.22` | `3.00` | `0.00` |
| `119` | `0` | `1` | `1` | `1` | `0.08` | `1.00` | `0.09` | `1.01` | `0.00` |
| `30` | `5` | `2` | `7` | `3` | `2.64` | `2.64` | `1.35` | `2.00` | `0.00` |
| `40` | `3` | `2` | `4` | `4` | `3.73` | `3.73` | `2.95` | `4.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `11` / `14` change to `5` / `28`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `20.01` units of pooled branch uncertainty and is floored to policy order-up-to `9`.
- `115`: Branch location. Current min/max `7` / `8` change to `3` / `5`. The branch uses an effective demand basis of `4.73` and a variability amount of `3.16` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `8` / `10` change to `3` / `5`. The branch uses an effective demand basis of `4.58` and a variability amount of `2.22` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `2` / `3` change to `2` / `4`. The branch uses an effective demand basis of `3.11` and a variability amount of `2.81` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `7` / `9` change to `3` / `6`. The branch uses an effective demand basis of `5.36` and a variability amount of `2.22` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.08` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `1.01` units of spike stock and `1.01` total branch deviation were pushed back to the DC.
- `30`: Branch location. Current min/max `5` / `7` change to `2` / `3`. The branch uses an effective demand basis of `2.64` and a variability amount of `1.35` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `3` / `4` change to `2` / `4`. The branch uses an effective demand basis of `3.73` and a variability amount of `2.95` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### NU-CALGON | R-600-10.6OZ-REFG | R-600 10.6OZ CAN

- Profile: ABC `C` at `88%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `24` months | YOY `26.9%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Up` at `1.11x` from `Supplier product group`
- Company total min: `13` -> `10` | company total max: `20` -> `26`
- Pooled to DC: `10.22` | absorbed by DC: `10.22` | changed locations: `2` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `3` | `3` | `4` | `14` | `2.89` | `2.89` | `1.89` | `0.00` | `10.22` |
| `115` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `116` | `5` | `2` | `7` | `3` | `2.71` | `2.71` | `1.11` | `2.00` | `0.00` |
| `117` | `3` | `2` | `4` | `4` | `3.62` | `3.62` | `2.45` | `3.00` | `0.00` |
| `118` | `1` | `1` | `2` | `2` | `1.08` | `3.25` | `2.26` | `4.40` | `0.00` |
| `119` | `0` | `1` | `1` | `1` | `0.25` | `1.00` | `0.28` | `0.83` | `0.00` |
| `30` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `40` | `1` | `1` | `2` | `2` | `1.25` | `1.25` | `0.88` | `0.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `3` / `4` change to `3` / `14`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `10.22` units of pooled branch uncertainty and is floored to policy order-up-to `5`.
- `115`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `5` / `7` change to `2` / `3`. The branch uses an effective demand basis of `2.71` and a variability amount of `1.11` to size the branch target, but the branch only keeps demand-only coverage. `2.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `3` / `4` change to `2` / `4`. The branch uses an effective demand basis of `3.62` and a variability amount of `2.45` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `1` / `2` change to `1` / `2`. Intermittent branch protection fired, so the raw active-demand mean `3.25` was reduced to `1.08` because the top two months account for 77% of scoped demand. `2.40` units of spike stock and `4.40` total branch deviation were pushed back to the DC.
- `119`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.25` because ADI is 4.0. `0.83` units of spike stock and `0.83` total branch deviation were pushed back to the DC.
- `30`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `1` / `2` change to `1` / `2`. The branch uses an effective demand basis of `1.25` and a variability amount of `0.88` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### RGAS LLC | R-407A-25LB-REFG | REFG R404A/R507 REPLACEMENT

- Profile: ABC `C` at `88%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `7` days | planning season `Summer`
- Reference window: `24` months | YOY `6.0%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.00x` from `Global product group`
- Company total min: `6` -> `8` | company total max: `21` -> `21`
- Pooled to DC: `11.27` | absorbed by DC: `11.27` | changed locations: `2` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `2` | `1` | `10` | `11` | `1.00` | `1.00` | `0.00` | `0.00` | `11.27` |
| `115` | `1` | `1` | `2` | `2` | `1.33` | `1.33` | `0.85` | `0.00` | `0.00` |
| `116` | `0` | `1` | `1` | `1` | `0.08` | `1.00` | `0.08` | `0.92` | `0.00` |
| `117` | `1` | `1` | `2` | `1` | `0.08` | `1.00` | `0.08` | `0.92` | `0.00` |
| `118` | `2` | `1` | `3` | `3` | `3.10` | `3.10` | `2.62` | `3.00` | `0.00` |
| `119` | `0` | `1` | `1` | `1` | `0.25` | `1.50` | `0.96` | `2.25` | `0.00` |
| `30` | `0` | `1` | `1` | `1` | `0.17` | `2.00` | `0.17` | `1.84` | `0.00` |
| `40` | `0` | `1` | `1` | `1` | `0.67` | `2.00` | `0.82` | `2.34` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `2` / `10` change to `1` / `11`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `11.27` units of pooled branch uncertainty and is floored to policy order-up-to `1`. The protection window was floored up to `28` days from a raw `21` days.
- `115`: Branch location. Current min/max `1` / `2` change to `1` / `2`. The branch uses an effective demand basis of `1.33` and a variability amount of `0.85` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `116`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.08` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `0.92` units of spike stock and `0.92` total branch deviation were pushed back to the DC. The protection window was floored up to `28` days from a raw `21` days.
- `117`: Branch location. Current min/max `1` / `2` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.08` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `0.92` units of spike stock and `0.92` total branch deviation were pushed back to the DC. The protection window was floored up to `28` days from a raw `21` days.
- `118`: Branch location. Current min/max `2` / `3` change to `1` / `3`. The branch uses an effective demand basis of `3.10` and a variability amount of `2.62` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead. The protection window was floored up to `28` days from a raw `21` days.
- `119`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.50` was reduced to `0.25` because it only sold in 2 of 12 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `1.25` units of spike stock and `2.25` total branch deviation were pushed back to the DC. The protection window was floored up to `28` days from a raw `21` days.
- `30`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.00` was reduced to `0.17` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `1.84` units of spike stock and `1.84` total branch deviation were pushed back to the DC. The protection window was floored up to `28` days from a raw `21` days.
- `40`: Branch location. Current min/max `0` / `1` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.00` was reduced to `0.67` because the top two months account for 75% of scoped demand. `1.34` units of spike stock and `2.34` total branch deviation were pushed back to the DC. The protection window was floored up to `28` days from a raw `21` days.

### iGAS USA, inc | R-32-20LB-REFG | REFRIGERANT R32

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `12` months | YOY `311.1%` | rule: Year-over-year demand moved outside +/-33%, so the model uses the last 12 months.
- Product-group trend: `Flat` at `1.01x` from `Supplier product group`
- Company total min: `17` -> `14` | company total max: `61` -> `59`
- Pooled to DC: `33.77` | absorbed by DC: `33.77` | changed locations: `3` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `3` | `3` | `40` | `39` | `3.20` | `3.20` | `2.50` | `0.00` | `33.77` |
| `115` | `1` | `1` | `2` | `2` | `1.17` | `1.75` | `1.13` | `2.59` | `0.00` |
| `116` | `3` | `2` | `4` | `4` | `3.67` | `3.67` | `1.76` | `5.00` | `0.00` |
| `117` | `1` | `1` | `2` | `2` | `1.80` | `1.80` | `1.12` | `3.00` | `0.00` |
| `118` | `2` | `1` | `3` | `1` | `1.00` | `2.00` | `1.74` | `5.01` | `0.00` |
| `119` | `1` | `1` | `2` | `2` | `1.17` | `2.33` | `1.33` | `3.17` | `0.00` |
| `30` | `3` | `3` | `4` | `5` | `4.80` | `4.80` | `3.60` | `8.00` | `0.00` |
| `40` | `3` | `2` | `4` | `4` | `4.17` | `4.17` | `3.32` | `7.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `3` / `40` change to `3` / `39`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `33.77` units of pooled branch uncertainty and is floored to policy order-up-to `9`.
- `115`: Branch location. Current min/max `1` / `2` change to `1` / `2`. Intermittent branch protection fired, so the raw active-demand mean `1.75` was reduced to `1.17` because the top two months account for 71% of scoped demand. `0.59` units of spike stock and `2.59` total branch deviation were pushed back to the DC.
- `116`: Branch location. Current min/max `3` / `4` change to `2` / `4`. The branch uses an effective demand basis of `3.67` and a variability amount of `1.76` to size the branch target, but the branch only keeps demand-only coverage. `5.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `1` / `2` change to `1` / `2`. The branch uses an effective demand basis of `1.80` and a variability amount of `1.12` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `2` / `3` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.00` was reduced to `1.00` because the top two months account for 83% of scoped demand. `1.01` units of spike stock and `5.01` total branch deviation were pushed back to the DC.
- `119`: Branch location. Current min/max `1` / `2` change to `1` / `2`. Intermittent branch protection fired, so the raw active-demand mean `2.33` was reduced to `1.17` because the top two months account for 86% of scoped demand. `1.17` units of spike stock and `3.17` total branch deviation were pushed back to the DC.
- `30`: Branch location. Current min/max `3` / `4` change to `3` / `5`. The branch uses an effective demand basis of `4.80` and a variability amount of `3.60` to size the branch target, but the branch only keeps demand-only coverage. `8.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `3` / `4` change to `2` / `4`. The branch uses an effective demand basis of `4.17` and a variability amount of `3.32` to size the branch target, but the branch only keeps demand-only coverage. `7.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### iGAS USA, inc | R-404A-24LB-REFG | HP-62

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `24` months | YOY `-17.7%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.01x` from `Supplier product group`
- Company total min: `110` -> `86` | company total max: `166` -> `265`
- Pooled to DC: `95.00` | absorbed by DC: `95.00` | changed locations: `8` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `27` | `30` | `59` | `151` | `32.00` | `32.00` | `24.02` | `0.00` | `95.00` |
| `115` | `8` | `6` | `11` | `12` | `12.00` | `12.00` | `2.86` | `6.00` | `0.00` |
| `116` | `20` | `10` | `25` | `21` | `20.50` | `20.50` | `6.19` | `13.00` | `0.00` |
| `117` | `11` | `9` | `14` | `19` | `19.08` | `19.08` | `11.69` | `25.00` | `0.00` |
| `118` | `22` | `15` | `28` | `32` | `31.25` | `31.25` | `12.08` | `25.00` | `0.00` |
| `119` | `3` | `2` | `4` | `3` | `2.20` | `2.20` | `1.98` | `3.00` | `0.00` |
| `30` | `10` | `7` | `13` | `14` | `14.25` | `14.25` | `5.04` | `10.00` | `0.00` |
| `40` | `9` | `7` | `12` | `13` | `13.00` | `13.00` | `6.20` | `13.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `27` / `59` change to `30` / `151`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `95.00` units of pooled branch uncertainty and is floored to policy order-up-to `83`.
- `115`: Branch location. Current min/max `8` / `11` change to `6` / `12`. The branch uses an effective demand basis of `12.00` and a variability amount of `2.86` to size the branch target, but the branch only keeps demand-only coverage. `6.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `20` / `25` change to `10` / `21`. The branch uses an effective demand basis of `20.50` and a variability amount of `6.19` to size the branch target, but the branch only keeps demand-only coverage. `13.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `11` / `14` change to `9` / `19`. The branch uses an effective demand basis of `19.08` and a variability amount of `11.69` to size the branch target, but the branch only keeps demand-only coverage. `25.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `22` / `28` change to `15` / `32`. The branch uses an effective demand basis of `31.25` and a variability amount of `12.08` to size the branch target, but the branch only keeps demand-only coverage. `25.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `3` / `4` change to `2` / `3`. The branch uses an effective demand basis of `2.20` and a variability amount of `1.98` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `10` / `13` change to `7` / `14`. The branch uses an effective demand basis of `14.25` and a variability amount of `5.04` to size the branch target, but the branch only keeps demand-only coverage. `10.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `9` / `12` change to `7` / `13`. The branch uses an effective demand basis of `13.00` and a variability amount of `6.20` to size the branch target, but the branch only keeps demand-only coverage. `13.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### iGAS USA, inc | R-421A-25LB-REFG | STD CYLINDER DYNATEMP CHOICE

- Profile: ABC `B` at `92%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `24` months | YOY `-28.1%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.01x` from `Supplier product group`
- Company total min: `8` -> `17` | company total max: `21` -> `41`
- Pooled to DC: `15.19` | absorbed by DC: `15.19` | changed locations: `7` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `2` | `4` | `10` | `21` | `3.60` | `3.60` | `1.91` | `0.00` | `15.19` |
| `115` | `2` | `3` | `3` | `5` | `4.92` | `4.92` | `2.21` | `3.00` | `0.00` |
| `116` | `0` | `2` | `1` | `3` | `2.29` | `2.29` | `1.69` | `1.00` | `0.00` |
| `117` | `1` | `3` | `2` | `5` | `4.60` | `4.60` | `2.85` | `4.00` | `0.00` |
| `118` | `0` | `1` | `0` | `1` | `0.08` | `1.00` | `0.08` | `0.93` | `0.00` |
| `119` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `30` | `1` | `3` | `2` | `5` | `5.33` | `5.33` | `3.10` | `4.00` | `0.00` |
| `40` | `2` | `1` | `3` | `1` | `0.25` | `1.50` | `0.96` | `2.26` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `2` / `10` change to `4` / `21`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `15.19` units of pooled branch uncertainty and is floored to policy order-up-to `7`.
- `115`: Branch location. Current min/max `2` / `3` change to `3` / `5`. The branch uses an effective demand basis of `4.92` and a variability amount of `2.21` to size the branch target, but the branch only keeps demand-only coverage. `3.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `0` / `1` change to `2` / `3`. The branch uses an effective demand basis of `2.29` and a variability amount of `1.69` to size the branch target, but the branch only keeps demand-only coverage. `1.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `1` / `2` change to `3` / `5`. The branch uses an effective demand basis of `4.60` and a variability amount of `2.85` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `0` / `0` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.00` was reduced to `0.08` because it only sold in 1 of 12 scoped months, ADI is 12.0, the top two months account for 100% of scoped demand. `0.93` units of spike stock and `0.93` total branch deviation were pushed back to the DC.
- `119`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `1` / `2` change to `3` / `5`. The branch uses an effective demand basis of `5.33` and a variability amount of `3.10` to size the branch target, but the branch only keeps demand-only coverage. `4.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `2` / `3` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `1.50` was reduced to `0.25` because it only sold in 2 of 12 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `1.26` units of spike stock and `2.26` total branch deviation were pushed back to the DC.

### iGAS USA, inc | R-438A-25LB-REFG | MO99 R-22 REPLACEMENT A.C

- Profile: ABC `A` at `99%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `24` months | YOY `-3.4%` | rule: Year-over-year demand stayed within +/-33%, so both years are used.
- Product-group trend: `Flat` at `1.01x` from `Supplier product group`
- Company total min: `39` -> `82` | company total max: `88` -> `303`
- Pooled to DC: `132.00` | absorbed by DC: `132.00` | changed locations: `8` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `7` | `18` | `44` | `168` | `18.75` | `18.75` | `17.08` | `0.00` | `132.00` |
| `115` | `3` | `8` | `4` | `17` | `16.33` | `16.33` | `8.59` | `19.00` | `0.00` |
| `116` | `6` | `14` | `8` | `30` | `29.75` | `29.75` | `9.96` | `20.00` | `0.00` |
| `117` | `13` | `14` | `17` | `29` | `29.00` | `29.00` | `11.93` | `24.00` | `0.00` |
| `118` | `2` | `4` | `3` | `7` | `6.58` | `6.58` | `2.89` | `7.00` | `0.00` |
| `119` | `0` | `2` | `1` | `4` | `3.30` | `3.30` | `3.17` | `6.00` | `0.00` |
| `30` | `4` | `10` | `6` | `22` | `21.42` | `21.42` | `8.77` | `19.00` | `0.00` |
| `40` | `4` | `12` | `5` | `26` | `25.75` | `25.75` | `17.13` | `37.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `7` / `44` change to `18` / `168`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `132.00` units of pooled branch uncertainty and is floored to policy order-up-to `56`.
- `115`: Branch location. Current min/max `3` / `4` change to `8` / `17`. The branch uses an effective demand basis of `16.33` and a variability amount of `8.59` to size the branch target, but the branch only keeps demand-only coverage. `19.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `6` / `8` change to `14` / `30`. The branch uses an effective demand basis of `29.75` and a variability amount of `9.96` to size the branch target, but the branch only keeps demand-only coverage. `20.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `13` / `17` change to `14` / `29`. The branch uses an effective demand basis of `29.00` and a variability amount of `11.93` to size the branch target, but the branch only keeps demand-only coverage. `24.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `118`: Branch location. Current min/max `2` / `3` change to `4` / `7`. The branch uses an effective demand basis of `6.58` and a variability amount of `2.89` to size the branch target, but the branch only keeps demand-only coverage. `7.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `0` / `1` change to `2` / `4`. The branch uses an effective demand basis of `3.30` and a variability amount of `3.17` to size the branch target, but the branch only keeps demand-only coverage. `6.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `30`: Branch location. Current min/max `4` / `6` change to `10` / `22`. The branch uses an effective demand basis of `21.42` and a variability amount of `8.77` to size the branch target, but the branch only keeps demand-only coverage. `19.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `4` / `5` change to `12` / `26`. The branch uses an effective demand basis of `25.75` and a variability amount of `17.13` to size the branch target, but the branch only keeps demand-only coverage. `37.00` units of deviation are intentionally not held here and are pooled to the DC instead.

### iGAS USA, inc | R-507-25LB-REFG | AZ-50 R-507A

- Profile: ABC `B` at `92%` service level | season `Summer` | frequency `2 Weeks` (`14` days) | lead time `14` days | planning season `Summer`
- Reference window: `12` months | YOY `-74.4%` | rule: Year-over-year demand moved outside +/-33%, so the model uses the last 12 months.
- Product-group trend: `Flat` at `1.01x` from `Supplier product group`
- Company total min: `8` -> `7` | company total max: `29` -> `24`
- Pooled to DC: `15.10` | absorbed by DC: `15.10` | changed locations: `4` of `8`

| Location | Current Min | New Min | Current Max | New Max | Mean Used | Raw Mean | Total Dev | Pooled to DC | Absorbed by DC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1` | `4` | `4` | `21` | `18` | `4.00` | `4.00` | `0.03` | `0.00` | `15.10` |
| `115` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `116` | `0` | `0` | `1` | `1` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `117` | `1` | `1` | `2` | `1` | `0.33` | `2.00` | `0.34` | `1.68` | `0.00` |
| `118` | `2` | `0` | `3` | `1` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `119` | `1` | `2` | `2` | `3` | `2.67` | `16.00` | `-0.32` | `13.42` | `0.00` |
| `30` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |
| `40` | `0` | `0` | `0` | `0` | `0.00` | `0.00` | `0.00` | `0.00` | `0.00` |

Location reasoning:
- `1`: DC / balancing location. Current min/max `4` / `21` change to `4` / `18`. The DC min only covers location 1's own protected-cycle demand. The DC max absorbs `15.10` units of pooled branch uncertainty and is floored to policy order-up-to `4`.
- `115`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `116`: Branch location. Current min/max `0` / `1` change to `0` / `1`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `117`: Branch location. Current min/max `1` / `2` change to `1` / `1`. Intermittent branch protection fired, so the raw active-demand mean `2.00` was reduced to `0.33` because it only sold in 1 of 6 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `1.68` units of spike stock and `1.68` total branch deviation were pushed back to the DC.
- `118`: Branch location. Current min/max `2` / `3` change to `0` / `1`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `119`: Branch location. Current min/max `1` / `2` change to `2` / `3`. Intermittent branch protection fired, so the raw active-demand mean `16.00` was reduced to `2.67` because it only sold in 1 of 6 scoped months, ADI is 6.0, the top two months account for 100% of scoped demand. `13.42` units of spike stock and `13.42` total branch deviation were pushed back to the DC.
- `30`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
- `40`: Branch location. Current min/max `0` / `0` change to `0` / `0`. The branch uses an effective demand basis of `0.00` and a variability amount of `0.00` to size the branch target, but the branch only keeps demand-only coverage. `0.00` units of deviation are intentionally not held here and are pooled to the DC instead.
