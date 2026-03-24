# Representative Model Cases for Programmers

## Purpose

This guide uses a small set of real items from the current `DataV5.xlsx` run to show how the model behaves under different conditions.

It is meant to answer two questions quickly:

- What business situation is this rule trying to solve?
- What did the engine actually do to the recommendation?

## Scope Used For These Examples

- Workbook: `DataV5.xlsx`
- Method: `Active Demand with Active Variability`
- Forecast mode: `Rules Only`
- Seasonality: `On`
- Planning season: `Summer`
- As-of date: `2026-03-24`
- Highest-month normalization: `On`
- Highest-month threshold: `200%`
- Low-cost local deviation threshold: `$1.00`

## How To Read The Examples

- `Current max total` is the current network stocking total.
- `Recommended max total` is the new network total after all demand and policy logic runs.
- `Pooled to DC` is how much branch uncertainty was sent toward the DC.
- `Absorbed by DC` is how much of that pooled amount the DC actually held.

The same item can trigger more than one rule. That is normal. The engine is layered.

## Scenario Summary

| Scenario | Example item | What it teaches |
| --- | --- | --- |
| Highest-month normalization | `R-134A-30LB-REFG` | A single very large month can be reset to a standard active month instead of becoming the new normal. |
| Two-point spike normalization | `T20ACR218-STK-TUBE` | If there are only two active months and one is much larger, the big month is flattened to the smaller one. |
| Project-spike suppression | `EMT34-COND` | One-time/project usage can be removed from replenishment entirely. |
| Regional zero-max branch policy | `CAMW-WDB-HONE` | A `Regional` item with zero-max branches stays non-stocked at those branches. |
| Negative-return netting plus sparse regional control | `CF12K6E-PFV-945-COPW` | Returns are netted backward and thin regional branch noise is prevented from exaggerating DC behavior. |
| DC sparse active-mean fallback | `ETC211000-000-ROBE` | A DC with only one thin active month should not be sized from a zero-excluded active mean. |
| Single-stocked-branch hold | `673-20X20-HART` | If only one non-DC location truly stocks the item, the DC stays at zero and other branches cannot seed stock. |
| Supplier minimum amount floor | `SR51J250-EASY` | Any positive recommendation must be at least the supplier minimum amount. |
| Pooled variance only, not direct intermittent transfer | `REPLCOIL05M-NORD` | Ordinary intermittent branches send variance to the DC, but do not linearly stack direct intermittent stock there. |

## 1. Highest-Month Normalization

**Item**

- Supplier: `A-GAS REFRIGERANTS`
- Item: `R-134A-30LB-REFG`
- Current max total: `115`
- Recommended max total: `60`
- Pooled to DC: `36.0`
- Absorbed by DC: `16.12`

**What happened**

- Several rows on this item triggered highest-month normalization.
- Example: location `1` had a highest active month of `48`, but the baseline active month was `4`.
- The model reset that outlier month before finishing the mean/variance build.

**Why the rule exists**

- A single selling month can be real, but it should not immediately redefine normal demand.
- This rule keeps the item active while stripping away the spike effect.

**Programmer note**

- This is not a full suppression rule.
- The item still remains replenishment-active.
- The main behavior is: replace the oversized top month with a standard active-month baseline.

## 2. Two-Point Intermittent Spike Normalization

**Item**

- Supplier: `MUELLER (TUBE)`
- Item: `T20ACR218-STK-TUBE`
- Current max total: `229`
- Recommended max total: `105`
- Location `118`: current max `149` -> recommended max `25`
- Location `1`: current max `20` -> recommended max `20`

**What happened**

- Location `118` had a two-point pattern:
  - raw active mean `20`
  - normalized mean `6.67`
- The row also triggered intermittent branch protection.
- The result is that the branch was not allowed to behave like a huge sustained stocking point.

**Why the rule exists**

- Some items only have two active months in scope.
- If one month is dramatically larger, the highest-month rule does not fit well because there are not enough non-zero months.
- This two-point rule handles that exact gap.

**Programmer note**

- The rule only exists because the active-demand method is aggressive by design.
- It is a corrective layer, not the primary demand method.

## 3. Project-Spike Suppression

**Item**

- Supplier: `ALL ELECTRIC SUPPLY`
- Item: `EMT34-COND`
- Current max total: `2`
- Recommended max total: `2`
- Location `40`: raw filtered mean `2000.0` -> final recommendation `0`

**What happened**

- Location `40` had a one-time massive project-style hit.
- The branch also looked intermittent, but project-spike suppression is the rule that matters most here.
- The usage was removed from replenishment logic instead of being converted into branch stock or DC stock.

**Why the rule exists**

- Some sales are jobs, projects, or one-time pulls.
- Those should not create future stocking unless there is repeat proof.

**Programmer note**

- This is a hard suppression case.
- It is stronger than highest-month normalization and stronger than intermittent fallback.

## 4. Regional Zero-Max Branch Policy

**Item**

- Supplier: `ADEMCO INC (HONEYWELL RESIDENTIAL)`
- Item: `CAMW-WDB-HONE`
- Status: `New Regional`
- Current max total: `3`
- Recommended max total: `2`
- Regional zero-max branch locations: `6`

**What happened**

- Several branches had `current max = 0`.
- Because the status contains `Regional`, those branches remained non-stocked.
- The model did not create new branch stock there just because there was some network signal.

**Why the rule exists**

- `Regional` is a stocking-footprint policy, not a statistical demand signal.
- The rule tells the engine how the network is allowed to carry the item.

**Programmer note**

- This is one of the clearest examples of policy overriding ordinary replenishment math.

## 5. Negative-Return Netting Plus Sparse Regional Control

**Item**

- Supplier: `COPELAND LP (COPW)`
- Item: `CF12K6E-PFV-945-COPW`
- Status: `Regional`
- Current max total: `2`
- Recommended max total: `3`

**What happened**

- Location `118` had negative usage that was netted backward:
  - `negative_usage_netted_months = 1`
  - `negative_usage_netted_units = 1.0`
- Location `118` also triggered sparse regional suppression.
- The result is a small, controlled recommendation instead of an inflated DC reaction.

**Why the rule exists**

- Returns should reduce prior demand, not create fake volatility.
- Thin regional signals should not overdrive pooled stock.

**Programmer note**

- This item shows how multiple protections can stack:
  - return handling
  - intermittent handling
  - sparse regional handling

## 6. DC Sparse Active-Mean Fallback

**Item**

- Supplier: `ROBERTSHAW CONTROLS COMPANY`
- Item: `ETC211000-000-ROBE`
- Current max total: `5`
- Recommended max total: `5`
- Location `1`: current max `1` -> recommended max `1`

**What happened**

- The DC row only had a thin active signal.
- Without fallback, the zero-excluded active mean would have made the DC look larger than it really is.
- The DC row fell back to an inclusive mean instead.

**Why the rule exists**

- The DC can have the same sparse-demand problem as a branch.
- If no branch pooling is driving the recommendation, a one-month DC hit should not be treated as steady DC demand.

**Programmer note**

- This is a DC-only protection.
- It exists because the balancing row otherwise tends to overreact to thin active history.

## 7. Single-Stocked-Branch Hold

**Item**

- Supplier: `HART & COOLEY INC`
- Item: `673-20X20-HART`
- Current max total: `2`
- Recommended max total: `2`
- Single-stocked-branch hold locations: `8`

**What happened**

- Location `40` is the only real non-DC stocking location.
- The DC currently has max `0`.
- The model held the DC at `0` and kept the item local to the one stocked branch.
- Location `117` was also blocked because it is not stockable.

**Why the rule exists**

- Some items are intentionally carried at one branch only.
- A blocked branch or thin signal should not be allowed to manufacture a DC need.

**Programmer note**

- This is a network-footprint control rule.
- It is not about demand volume. It is about where the business wants the item to live.

## 8. Supplier Minimum Amount Floor

**Item**

- Supplier: `EASYHEAT INC-APPLETON GROUP LLC`
- Item: `SR51J250-EASY`
- Current max total: `699`
- Recommended max total: `400`
- Supplier minimum floor rows: `8`

**What happened**

- Every positive recommended row was floored to `S. Min Amt = 50`.
- Example:
  - location `30`: recommendation would have been `1`, but final max is `50`
  - location `40`: recommendation would have been `1`, but final max is `50`

**Why the rule exists**

- Sometimes the final recommendation is constrained by supplier policy, not by demand.
- Once the item is still considered stock-worthy at that location, the final max cannot stay below the supplier minimum amount.

**Programmer note**

- This is a post-calculation floor.
- It should not be interpreted as demand.

## 9. Pooled Variance Only, Not Direct Intermittent Transfer

**Item**

- Supplier: `NORTEK PARTS`
- Item: `REPLCOIL05M-NORD`
- Current max total: `8`
- Recommended max total: `12`
- Pooled to DC: `7.0`
- Absorbed by DC: `3.61`

**What happened**

- Multiple branches triggered intermittent protection.
- Their branch means were reduced, but the DC did not receive direct intermittent transfer stock.
- Instead, the DC only absorbed pooled variance through the root-sum-square calculation.

Examples:

- location `30`: current max `1` -> recommended max `2`, pooled `2.0`, direct intermittent transfer suppressed
- location `40`: current max `1` -> recommended max `1`, pooled `2.0`, direct intermittent transfer suppressed
- location `1`: current max `1` -> recommended max `5`, absorbing `3.61`

**Why the rule exists**

- Summing every intermittent branch signal linearly overstates network risk.
- Pooled variance is more stable and better matches how uncertainty should aggregate.

**Programmer note**

- This is the current default for ordinary intermittent branches:
  - pool variance
  - do not linearly stack direct intermittent stock

## What These Examples Teach

The main implementation lesson is that the engine is layered:

- first decide whether the history is even trustworthy
- then estimate demand
- then decide whether the signal belongs at the branch, the DC, or nowhere
- then apply final business-policy constraints

If another team tries to learn only the final max without modeling these layers, the results will look inconsistent because the final numbers are a mixture of:

- demand logic
- inventory policy
- stocking-footprint policy
- explicit business overrides
