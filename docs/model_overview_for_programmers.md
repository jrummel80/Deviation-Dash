# Deviation Dash Model Overview for Programmers

## Purpose

This model is a deterministic replenishment engine. It does not "guess" min and max settings directly from a black-box model. Instead, it:

1. Reads raw item-location demand history from the workbook `Data` tab.
2. Builds a demand signal for each `supplier + item + location`.
3. Applies business rules for seasonality, lead time, supplier order frequency, ABC service level, branch/DC behavior, overrides, and spike suppression.
4. Produces recommended min and max values by location.

The dashboard can optionally use an AutoGluon forecast as the demand input, but the stocking logic is still rule-based.

## Calculation Grain

- Primary grouping: `supplier + item`
- Recommendation grain: `supplier + item + location`
- Summary grain: one row per `supplier + item`

## Core Inputs

Important workbook columns used by the model:

- `Supplier`, `Item`, `Description`, `Location`
- `Status`, `Season`, `ABC`, `Prod Group`
- `Frequency`, `Lead Time`
- `Min`, `Max`, `Net QOH`
- `Override`, `Per`, `Oride Date`
- `S. Min Amt`
- `MAC`
- `Stockable`
- 24 monthly demand columns like `Mar-26`, `Feb-26`, etc.

## High-Level Flow

```text
load workbook
-> normalize raw data
-> ignore excluded rows
-> net negative months backward
-> choose reference window (12 vs 24 months)
-> apply season window if enabled
-> normalize spikes / intermittent demand
-> optionally blend product-group trend
-> optionally apply current replenishment-window seasonal ramp
-> convert monthly demand into policy min/max floors
-> apply branch/DC pooling rules
-> apply overrides, supplier mins, stockability, and stocking-footprint gates
-> finalize recommended min/max per location
```

## Step 1: Global Row Filtering

These rows are removed before recommendations are built:

- Location `9999`
- Status in `Service`, `Ok to Sell Below Cost`, `Special`, `Inactive`, `Substitute`, `Exception`
- `Stock` rows with no max

## Step 2: Negative Usage Handling

Negative monthly usage is treated as returns, not demand.

- A negative month is netted backward against the closest earlier positive month for the same `supplier + item + location`
- Lookback limit is 12 months
- If no earlier positive month exists, the negative amount is dropped from replenishment math

This keeps returns from inflating variability or creating DC stock.

## Step 3: Supplier Inventory Policy

Default DC is location `1`, except:

- `HAILIANG AMERICA` -> DC is `118`
- `REFLECTIX` -> DC is `119`

These suppliers are treated as non-hub-managed, so no DC pooling is allowed:

- `M&M MANUFACTURING`
- `ATCO RUBBER`
- `MCDANIEL METALS`
- `CONKLIN METAL INDUSTRIES`
- `RYERSON & SON, JOSEPH T.`

## Step 4: Reference Window Selection

The model compares company demand over:

- recent 12 months
- prior 12 months

Rule:

- if YOY change is between `-33%` and `+33%`, use 24 months
- otherwise use 12 months

This reference window controls what history is considered "current."

## Step 5: Seasonality

Season definitions:

- `Summer` = April through September
- `Winter` = October through March

When seasonality is enabled:

- demand is scoped to the planning season
- if the item has enough seasonal history, the model uses the next protected replenishment window instead of the full season average
- if history is too thin or intermittent, it stays on the full seasonal view

Current-window seasonal ramp turns the model into "what do I need for the next replenishment cycle?" instead of "what is the season average?"

## Step 6: Product-Group Trend

The model can nudge item demand using `Prod Group` trend.

- It first tries supplier-specific product-group trend
- If that is too small, it falls back to global product-group trend
- The trend factor is damped and clipped to the range `0.85x` to `1.15x`

This is a light bias, not a hard override.

## Step 7: Demand Methods

The dashboard still supports three historical methods:

- `Active Demand with Active Variability`
- `Recent Mean with Active Variability`
- `Recent Mean with Full Variability`

Most of the spike and branch/DC protections were tuned around `Active Demand with Active Variability`, which is the method that excludes zero months for both mean and standard deviation before later protection rules adjust it.

## Step 8: Spike and Sparse-Demand Protections

These are the main anti-spike protections, in practical order:

1. Highest-month normalization
- Always on
- If there are at least 3 non-zero scoped months, the highest month is compared to the median of the other non-zero months
- If it is above the configured threshold, it is reset to that baseline

2. Two-point intermittent spike normalization
- Used on `Active Demand with Active Variability`
- If there are exactly 2 non-zero scoped months and the top month is at least `5x` the second month, the top month is reset to the second month

3. Intermittent branch protection
- Used on non-DC branches for `Active Demand with Active Variability`
- Fires when demand is sparse, for example:
- 2 or fewer non-zero months
- ADI >= 4
- top 2 months >= 70% of scoped demand
- Result: branch mean falls back to inclusive mean

4. Project spike suppression
- Removes obvious one-time/project usage from both branch and DC replenishment logic

5. Single-period pooling guard
- If a branch has only 1 scoped selling month and the item still lacks enough repeat proof, that branch signal can affect the local branch floor but cannot create DC stock

6. Sparse regional pool suppression
- Thin regional branch spikes do not automatically create pooled DC stock unless the explicit regional-zero-max rule applies

7. DC sparse active-mean fallback
- If the DC itself has only 1-2 non-zero scoped months and no branch pooling is creating the recommendation, the DC falls back from zero-excluded active mean to inclusive mean

## Step 9: Service Level and Protection Days

Default service levels:

- `A = 99%`
- `B = 92%`
- `C = 88%`
- `D = 84%`
- `E = 80%`
- `X = 80%`

Users can change these in the dashboard.

Protection days:

- `raw protection days = lead time + frequency`
- if that is below 28, use 28
- `Local` frequency is treated as 4 weeks

## Step 10: Min / Max Floors

Base calculations are:

- `daily demand = monthly demand / 30.4375`
- `lead time demand = daily demand * lead time days`
- `protected cycle demand = daily demand * protection days`

Branch min:

- branch min uses demand-only lead-time coverage

DC min:

- DC min uses only the DC's own protected-cycle demand
- DC min does not include branch deviation stock

Order-up-to floors:

- demand-only order-up-to
- service-level order-up-to using ABC z-score and variability

## Step 11: Branch Recommendation Logic

Branch rows use these ideas:

- start with a branch base recommendation from current max and rounded demand
- apply policy order-up-to and min floors
- if branch variability is not kept local, only the pooled-variance portion normally moves to the DC
- direct intermittent transfer to the DC is only allowed when an explicit spike rule fired

## Step 12: DC / Balancing Logic

For hub-managed suppliers, the designated DC is the balancing location.

The DC max is built from:

- its own rounded demand
- minus branch max already being held at branches
- plus the largest location deviation
- plus pooled branch protection

Pooled branch protection uses:

- pooled variance via root-sum-square
- direct transfer only for explicit spike cases or allowed blocked-stock transfers

## Step 13: Stocking-Footprint Rules

These rules control where stock is allowed to exist:

- New branch stock requires:
- more than 2 selling months in the last 12 months
- at least 3 currently stocked locations

- If `Status` contains `Regional` and branch `current max = 0`:
- the branch stays non-stocked
- the signal is intentionally handled through the DC

- If an item is currently stocked at exactly one non-DC location, the DC has max 0, and status is not Regional:
- that stocked branch keeps its own need
- no other branch can create DC stock
- the DC is held at 0

- If `Stockable != Y` and `current max = 0`:
- the location cannot seed a new branch max
- the location cannot create DC pooling

## Step 14: Cost / Supplier / Override Rules

- If `MAC` is below the user-selected threshold, deviation stays local instead of being pooled to the DC
- If `Override = Y`, recommended max is locked to current max
- If `S. Min Amt > 0`, recommended max is floored up to at least that supplier minimum

## Step 15: Seasonal Ceiling Rule

For sparse seasonal items with long protection windows, the model applies a company-level seasonal ceiling so a thin one-season pattern does not explode into a large network recommendation.

## Outputs

For each location, the model outputs:

- recommended min
- recommended max
- change from current min/max
- explanation fields showing which rules fired

For each item, the model outputs:

- current total min/max
- recommended total min/max
- total DC pool input
- counts of rule hits such as outlier normalization, project suppression, branch-stock gate, and DC fallback

## Key Principle for Reimplementation

This model is best understood as:

- a demand estimator
- plus a large deterministic rules layer
- plus a stocking-footprint policy layer

If another team wants to replicate it, they should not train a single model to "guess min/max" directly first. The best way to reproduce behavior is:

1. reproduce the row-level demand signal
2. reproduce the spike protections
3. reproduce branch/DC pooling and stocking-footprint rules
4. only then compare final min/max results

## Practical Summary

The model is conservative about holding true replenishment stock, but increasingly aggressive about rejecting bad signals:

- returns do not count as demand
- sparse spikes are normalized or suppressed
- ordinary intermittent demand usually pools only variance, not direct stock
- non-stockable locations cannot create stock
- single stocked branch items stay local unless explicitly Regional
- supplier-specific hub policy overrides are respected

That is the current behavior the dashboard is implementing today.
