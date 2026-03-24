# Representative Recommendation Scenarios for the AI Team

## Purpose

This document is a short teaching set. Instead of reviewing a long random item list, it uses a small number of real items that each show a different rule path in the replenishment engine.

The goal is to help programmers understand **why** the model makes a recommendation, not just **what** number it outputs.

## Scope Used For This Document

- Source data: current `DataV3.xlsx` import snapshot cached by the dashboard on March 23, 2026.
- Method: `Active Demand with Active Variability`.
- Forecast mode: `Rules Only`.
- Seasonality: `On`, planning season `Summer`.
- Service levels: `A=99%`, `B=92%`, `C=88%`, `D=84%`, `E=80%`, `X=80%`.
- Low-cost local deviation threshold: `$1.00 MAC`.
- Highest-month normalization: `Off`.
- Location `1` is the DC plus a stocking location.
- Branch locations are `30`, `40`, `115`, `116`, `117`, `118`, and `119`.
- Location `9999` is ignored.

## How To Read These Examples

- `Recommended Min` is the working stock the model wants to protect for that location.
- `Recommended Max` is the replenishment target for that location right now.
- Branches are usually sized for local working demand, while large deviation is pooled to the DC.
- Some outputs are not demand-forecast decisions at all. They are policy decisions such as overrides, supplier minimums, regional rules, or alert flags.

## Scenario Summary

| Scenario | Example item | What it teaches |
| --- | --- | --- |
| Simple baseline / no special exception | `ESP COMPANY \| WATERHOSE-25-PREM` | What the engine does when there is no override, no regional rule, no low-cost exception, and no seasonal ramp. |
| Seasonal ramp to current replenishment window | `COPELAND LP - WHITE RODGERS DIVISION \| BFK163S-COPF` | Strong seasonal items should ramp toward the current window, not hold the full-season peak all season long. |
| Intermittent branch spike pooled to DC | `iGAS USA, inc \| R-507-25LB-REFG` | A branch should not look like a steady 16-per-month item just because it sold 16 in one isolated month. |
| Regional zero-max branches stay pooled to DC | `TWENTYTHREEC LLC (OXBOX) \| BAYHTRJ508BRKAA-OXBX` | If status contains `Regional` and branch current max is `0`, the branch stays non-stocked. |
| Branch current max is zero but model wants stock | `ICEO-MATIC (ICEO) \| 9101379-01-ICEO` | The model can flag a branch that has no current max but now looks like it needs stocking. |
| Low-cost item keeps deviation local | `SELECTA PRODUCTS INC \| PC2400-DURA` | Cheap items under the MAC threshold keep their deviation at the branch instead of pushing it to the DC. |
| Manual override wins | `EWC CONTROLS, INC. \| SAS-EWCC` | If `Override = Y`, the override location keeps its current max. |
| Supplier minimum amount floors the max | `SELECTA PRODUCTS INC \| LN91-BATT` | If `S. Min Amt > 0`, any positive recommended max must be at least that value. |
| DC gets a new max from pooled demand while current DC max is zero | `NORTEK PARTS \| 01-0085-NORP` | The model should flag when DC stock is being created only because branches pooled demand back to location `1`. |

## 1. Simple Baseline / No Special Exception

**Item**

- Supplier: `ESP COMPANY`
- Item: `WATERHOSE-25-PREM`
- Description: `HOSE WATER 5/8X25FT PREMIUM`
- Status: `New`
- Company totals: current min/max `8 / 16` -> recommended min/max `4 / 12`

**What happened**

- This item is the cleanest simple example in the current file.
- No override fired.
- No regional rule fired.
- No low-cost local rule fired.
- No supplier minimum floor fired.
- No seasonal ramp fired.
- No intermittent branch protection fired.

**Important locations**

- Location `1`: current min/max `1 / 2` -> recommended `4 / 5`
- Locations `30`, `40`, `115`, `116`, `117`, `118`, `119`: current max `2` -> recommended max `1`
- Branch recommended mins fell to `0`

**Plain-English reasoning**

- The item has very light branch demand in the scoped window.
- The branches do not justify local working stock beyond a token max.
- The DC remains the main stocking point because that is where the actual active demand signal exists.

**Programmer takeaway**

- This is a good reference case for the engine's default behavior when no exception rules are needed.
- It is useful as a control example when validating later changes.

## 2. Seasonal Ramp To The Current Replenishment Window

**Item**

- Supplier: `COPELAND LP - WHITE RODGERS DIVISION`
- Item: `BFK163S-COPF`
- Description: `3/8 SXS BIFLOW FILTER DRIER`
- Status: `Normal`
- Company totals: current min/max `11 / 15` -> recommended min/max `5 / 13`

**What happened**

- One location had enough real summer history to use the new current-window seasonal ramp.
- The item's peak month is `July`, but the planning window at the time of this run was the upcoming `April` replenishment window.
- Because of that, the branch should not hold full July-level stock yet.

**Important locations**

- Location `40`: current max `13` -> recommended max `4`
- Location `40`: raw filtered mean `9.36` -> ramped filtered mean `3.50`
- Location `40`: ramp factor `0.373786`
- Location `40`: ramp window `Apr-26 (28d)`
- Location `1`: current max `2` -> recommended max `9`, absorbing `3.0` pooled deviation

**Plain-English reasoning**

- The model recognized that this is a real seasonal item with enough history to trust the monthly shape.
- Instead of using the whole summer average, it used the demand expected during the next protection window.
- That lowered the branch max now, but still allowed the DC to hold pooled uncertainty.

**Programmer takeaway**

- This is the clearest example of the new "current replenishment window" logic.
- The model should ramp into the season rather than acting like the peak month is already here.

## 3. Intermittent Branch Spike Pooled To DC

**Item**

- Supplier: `iGAS USA, inc`
- Item: `R-507-25LB-REFG`
- Description: `AZ-50 R-507A`
- Status: `Normal`
- Company totals: current min/max `8 / 29` -> recommended min/max `7 / 24`

**What happened**

- This is the best real example of the intermittent-branch protection rule.
- A branch sold a large quantity in one isolated month, which would have badly overstated steady branch demand if the model simply excluded zeros.

**Important locations**

- Location `119`: current max `2` -> recommended max `3`
- Location `119`: raw filtered mean `16.0`
- Location `119`: protected filtered mean `2.67`
- Location `119`: intermittent rule reason: it only sold in `1` of `6` scoped months, `ADI = 6.0`, top two months = `100%` of scoped demand
- Location `119`: `13.42` units were pooled back to the DC
- Location `1`: current max `21` -> recommended max `18`
- Location `1`: absorbed pooled deviation `15.10`

**Plain-English reasoning**

- Without protection, the branch would look like a steady `16` per month item because the active-demand method ignores zero months.
- The intermittent rule recognizes that this was not steady branch demand.
- It converts the branch to a much smaller inclusive mean and sends the spike stock back to the DC.

**Programmer takeaway**

- This is one of the most important branch-vs-DC protections in the whole engine.
- It prevents isolated spike months from turning into permanent branch stocking.

## 4. Regional Zero-Max Branches Stay Pooled To DC

**Item**

- Supplier: `TWENTYTHREEC LLC (OXBOX)`
- Item: `BAYHTRJ508BRKAA-OXBX`
- Description: `HEAT STRIP 8KW JMM4 AIR HAND`
- Status: `Regional`
- Company totals: current max `4` -> recommended max `3`

**What happened**

- This is the cleanest current example of the `Regional` branch rule.
- Several branches had current max `0`.
- Because the status contains the word `Regional`, those zero-max branches stayed non-stocked.

**Important locations**

- Location `40`: current max `0` -> recommended max `0`
- Location `115`: current max `0` -> recommended max `0`
- Location `116`: current max `0` -> recommended max `0`
- Location `117`: current max `0` -> recommended max `0`
- Location `119`: current max `0` -> recommended max `0`
- Those five branches were marked with `regional_zero_max_branch_pool_applied = True`
- Location `30`: current max `2` -> recommended max `1`, pooling `0.83` to the DC
- Location `1`: current max `0` -> recommended max `1`, absorbing `0.83`

**Plain-English reasoning**

- The business meaning is: this is a regional item, not a normal branch-stock item.
- If a branch currently has no max, the model should not create new branch stock there just because demand exists somewhere in the network.
- Instead, the demand is serviced through the DC.

**Programmer takeaway**

- This is a policy rule, not a statistical rule.
- It should override normal branch stocking logic for statuses that contain the word `Regional`.

## 5. Branch Current Max Is Zero But The Model Wants Stock

**Item**

- Supplier: `ICEO-MATIC (ICEO)`
- Item: `9101379-01-ICEO`
- Description: `REED SWITCH`
- Status: `Normal`
- Company totals: current max `1` -> recommended max `3`

**What happened**

- This is the best simple alert example for a branch with current max `0` that the model now wants to stock.
- The location should be highlighted for review because it changes the stocking pattern.

**Important locations**

- Location `118`: current min/max `0 / 0` -> recommended `1 / 2`
- Location `118`: `branch_zero_max_recommendation_alert = True`
- Location `1`: stayed at max `1`
- All other branches stayed at `0`

**Plain-English reasoning**

- The item is not regional, so the zero-max regional protection does not apply.
- The normal demand and policy math says location `118` now needs working stock.
- Because the branch had no current max before, the model raises an alert for review.

**Programmer takeaway**

- This should be treated as a workflow flag, not just a number.
- The output is telling the buyer, "the engine wants to create a new stocked branch location."

## 6. Low-Cost Item Keeps Deviation Local

**Item**

- Supplier: `SELECTA PRODUCTS INC`
- Item: `PC2400-DURA`
- Description: `BATTERY ALK AAA PROCELL`
- Status: `Bulk`
- Company totals: current max `648` -> recommended max `813`

**What happened**

- This item has `MAC` values around `0.51` to `0.55`.
- Because the dashboard threshold was `$1.00`, the low-cost local rule applied to all seven branches.
- That means the branches kept their deviation locally instead of sending it to the DC.

**Important locations**

- Location `30`: current max `168` -> recommended max `231`
- Location `117`: current max `24` -> recommended max `71`
- Location `119`: current max `24` -> recommended max `26`
- All seven branches had `low_cost_local_deviation_applied = True`
- Pooled deviation to DC was `0` at every branch
- Location `1`: current max `144` -> recommended max `158`

**Plain-English reasoning**

- For cheap items, it is usually acceptable to keep extra stock local because the cost of decentralizing that stock is low.
- The engine intentionally stops pooling deviation to the DC when the item cost is below the configured threshold.

**Programmer takeaway**

- This is another policy layer, not a demand-estimation change.
- The demand signal may be the same, but the placement of the uncertainty stock changes because of item cost.

## 7. Manual Override Wins

**Item**

- Supplier: `EWC CONTROLS, INC.`
- Item: `SAS-EWCC`
- Description: `SENSOR AIR SUPPLY`
- Status: `Normal`
- Company totals: current max `34` -> recommended max `33`

**What happened**

- One location had a manual override.
- That location kept its current max regardless of what the normal math might have recommended.

**Important locations**

- Location `119`: current max `30` -> recommended max `30`
- Location `119`: `override_flag = True`
- Location `119`: `Per = HOLLADAY`
- Location `1`: current max `2` -> recommended max `1`
- All other locations followed the normal rules

**Plain-English reasoning**

- Overrides are buyer-owned decisions.
- When the file says `Override = Y`, the model does not try to outvote that row.
- The location stays at the current max and is marked so the UI can explain why it did not move.

**Programmer takeaway**

- Overrides should be treated as hard constraints unless the business explicitly decides otherwise.
- The AI model can explain them, but it should not silently ignore them.

## 8. Supplier Minimum Amount Floors The Max

**Item**

- Supplier: `SELECTA PRODUCTS INC`
- Item: `LN91-BATT`
- Description: `BATTERY LITHIUM AA ENERGIZER INDUSTRIAL`
- Status: `New`
- Company totals: current max `192` -> recommended max `96`

**What happened**

- Every stocked location had `S. Min Amt = 12`.
- The demand math wanted a much smaller result, but the supplier minimum amount forced each positive recommended max to be at least `12`.

**Important locations**

- Every location: current max `24` -> recommended max `12`
- Every location: `supplier_min_amount_floor_applied = True`
- Every location: `supplier_min_amount = 12`

**Plain-English reasoning**

- This is not saying demand requires `12`.
- It is saying the item cannot be recommended below the supplier's minimum stocking or order requirement once a positive max is justified.
- The supplier floor is acting as the last guardrail after the demand logic runs.

**Programmer takeaway**

- This is a post-calculation policy floor.
- It is important that the AI team not confuse this with demand itself.

## 9. DC Gets A New Max From Pooled Demand While Current DC Max Is Zero

**Item**

- Supplier: `NORTEK PARTS`
- Item: `01-0085-NORP`
- Description: `CAP 45+5MFD 370V FT4BD036`
- Status: `Normal`
- Company totals: current max `1` -> recommended max `3`

**What happened**

- The only meaningful branch signal came from location `115`.
- That branch kept max `1`, but it also pooled `1.0` unit of deviation to the DC.
- Because location `1` had current max `0`, the DC had to be created by pooled demand alone.

**Important locations**

- Location `115`: current max `1` -> recommended max `1`, pooled `1.0` to DC
- Location `1`: current max `0` -> recommended max `2`
- Location `1`: `dc_pooling_zero_max_alert = True`

**Plain-English reasoning**

- The engine is saying the network needs DC coverage even though the DC is not currently stocked.
- That is a meaningful workflow event because it creates a new DC max solely from pooled uncertainty.

**Programmer takeaway**

- This should be highlighted, not just calculated.
- It means the system is introducing a new DC stocking decision rather than merely resizing an existing one.

## What These Examples Show The AI Team

- Some outputs are mainly driven by demand estimation.
- Some outputs are mainly driven by inventory policy.
- Some outputs are mainly driven by explicit user control.
- A good AI replacement model would need to learn all three layers, or keep the policy layers as hard rules around a learned demand model.

## Suggested Feature Groups For A Learned Model

- Demand history by item and location
- Seasonality by item, product group, and calendar month
- Branch vs DC role
- Lead time and supplier frequency
- ABC service level
- Status text, especially anything containing `Regional`
- Current min and current max
- MAC and supplier minimum amount
- Override flags and override metadata
- Intermittent-demand indicators such as active-month count, ADI, and top-two-month concentration

## Suggested Training Caution

- Do not train the AI model to treat every final max as a pure forecast target.
- Many recommendation outputs are policy-adjusted targets, not raw demand expectations.
- If the AI team wants the clearest design, forecast demand first, then apply the policy rules as explicit constraints.
