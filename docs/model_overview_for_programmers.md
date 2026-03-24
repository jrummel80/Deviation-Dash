# Deviation Dash Model Overview for Programmers

## Purpose

Deviation Dash is a deterministic replenishment engine.

It does not directly ask a model to "guess min and max."
Instead, it:

1. Loads raw workbook history at `supplier + item + location`.
2. Converts that history into a demand signal.
3. Applies explicit business-policy rules.
4. Produces recommended min/max values plus explanation flags.

The dashboard can optionally use an AutoGluon forecast as the demand input, but the replenishment policy layer is still rule-based.

## What The Model Is Optimizing

At a high level, the engine is trying to answer two different questions:

- What does this location likely need for the next replenishment window?
- Where should uncertainty be held: at the branch, at the DC, or nowhere at all?

That is why the model has both:

- a demand-estimation layer
- a stocking-footprint / policy layer

## Current Reference Run

The current source-of-truth configuration used for explanation and validation is:

- Workbook: `DataV5.xlsx`
- Method: `Active Demand with Active Variability`
- Forecast mode: `Rules Only`
- Seasonality: `On`
- Planning season: `Summer`
- As-of date: `2026-03-24`
- Highest-month normalization: `On`
- Highest-month threshold: `200%`
- Low-cost local deviation threshold: `$1.00 MAC`
- Service levels:
  - `A = 99%`
  - `B = 92%`
  - `C = 88%`
  - `D = 84%`
  - `E = 80%`
  - `X = 80%`

That run currently produces:

- `8,159` item summaries
- `65,532` location-detail rows

Rule-hit counts from that same run:

- `5,174` rows with highest-month normalization
- `147` rows with two-point intermittent spike normalization
- `11,265` rows with intermittent branch protection
- `153` rows with project-spike suppression
- `264` rows with single-period pool guard
- `241` rows with sparse regional pool suppression
- `1,601` rows with DC sparse active-mean fallback
- `13,047` rows with supplier minimum amount floors
- `6,102` rows affected by single-stocked-branch hold
- `582` rows blocked because the location is not stockable

## Calculation Grain

- Grouping grain: `supplier + item`
- Output grain: `supplier + item + location`
- Summary grain: one row per `supplier + item`

Locations are ordered like this:

- `1`
- `30`
- `40`
- `115`
- `116`
- `117`
- `118`
- `119`

Location `9999` is ignored before recommendations are built.

## Key Input Columns

The engine mainly depends on these workbook columns:

- identity:
  - `Supplier`
  - `Item`
  - `Description`
  - `Location`
- policy:
  - `Status`
  - `Season`
  - `ABC`
  - `Prod Group`
  - `Stockable`
  - `Override`
  - `Per`
  - `Oride Date`
  - `S. Min Amt`
  - `MAC`
- replenishment timing:
  - `Frequency`
  - `Lead Time`
- current stocking state:
  - `Min`
  - `Max`
  - `Net QOH`
- demand history:
  - the 24 monthly columns like `Mar-26`, `Feb-26`, and so on

## End-To-End Flow

```text
load workbook
-> normalize columns and monthly history
-> remove ignored rows
-> net negative months backward
-> choose supplier/DC policy
-> choose 12-month vs 24-month reference window
-> apply planning-season scope
-> normalize obvious outlier months
-> detect intermittent / sparse demand
-> optionally blend product-group trend
-> optionally use current replenishment-window seasonal ramp
-> compute demand-only and service-level floors
-> build branch recommendations
-> decide what deviation stays local vs pools to DC
-> build DC / balancing recommendation
-> apply final policy constraints
-> emit min/max + flags + explanations
```

## Layer 1: Global Filtering

Rows are removed up front when they should never drive replenishment:

- location `9999`
- status in:
  - `Service`
  - `Ok to Sell Below Cost`
  - `Special`
  - `Inactive`
  - `Substitute`
  - `Exception`
- `Stock` rows when max is blank or zero

This filtering happens before demand math, so ignored rows do not distort averages, variance, or DC pooling.

## Layer 2: Negative Usage Handling

Negative usage is treated as returns or reversals, not replenishment demand.

Current rule:

- process months from oldest to newest
- when a month is negative, net it backward against the closest earlier positive month(s)
- only look back 12 months
- if there is still leftover negative amount after that, drop it from replenishment math

Business intent:

- keep net usage realistic
- do not let return months create fake volatility
- do not let negative months push stock into the DC

## Layer 3: Supplier Inventory Policy

Default DC:

- location `1`

Supplier-specific DC overrides:

- `HAILIANG AMERICA` -> location `118`
- `REFLECTIX` -> location `119`

Suppliers that do not pool to a DC at all:

- `M&M MANUFACTURING`
- `ATCO RUBBER`
- `MCDANIEL METALS`
- `CONKLIN METAL INDUSTRIES`
- `RYERSON & SON, JOSEPH T.`

When a supplier is marked non-hub-managed:

- variability stays local
- no DC absorption logic is used

## Layer 4: Reference Window Selection

The engine compares:

- recent 12 months
- prior 12 months

Rule:

- if YOY change stays between `-33%` and `+33%`, use `24` months
- otherwise use `12` months

Business intent:

- stable items use more history
- trending items use more recent history

## Layer 5: Seasonality And Replenishment Window Focus

Season definitions:

- `Summer` = April through September
- `Winter` = October through March

When seasonality is enabled:

- the model scopes demand to the planning season
- if history is thin, it keeps the whole-season view
- if history is strong enough, it uses a forward-looking replenishment window instead of a full-season average

This makes the engine answer:

- "what do I need for the next cycle?"

instead of:

- "what is the average for the whole season?"

## Layer 6: Product-Group Trend

The engine can lightly nudge the item mean using `Prod Group` trend.

Rules:

- prefer `supplier + prod_group` trend
- fall back to global `prod_group` trend
- clip the adjustment to `0.85x` through `1.15x`

Intent:

- allow a modest directional signal
- prevent category trend from overwhelming the item itself

## Layer 7: Base Demand Method

The dashboard still supports multiple historical methods, but the rule set has been tuned mainly around:

- `Active Demand with Active Variability`

Meaning:

- mean excludes zero months
- standard deviation excludes zero months

That method is deliberately aggressive about detecting "active" demand, which is why later protection rules are so important.

## Layer 8: Spike And Sparse-Demand Protection Ladder

This is the most important part of the model to understand.

The protections are global conditional rules, not one-off item exceptions.

### 1. Highest-month normalization

Always on.

When there are at least 3 non-zero scoped months:

- compare the highest month to the median of the other non-zero months
- if it is above the threshold, reset the highest month to the baseline month level

Current default threshold:

- `200%`

Intent:

- keep one big month from becoming the new normal

### 2. Two-point intermittent spike normalization

Used when there are exactly 2 non-zero scoped months and the top month is much larger.

Current trigger:

- top month is at least `5x` the second month

Action:

- reset the top month to the second month for scoped calculations

Intent:

- fix `220 + 20` type patterns without suppressing the item entirely

### 3. Intermittent branch protection

Used on non-DC branches for the active-demand method.

Typical triggers:

- `2` or fewer non-zero months
- `ADI >= 4`
- top 2 months hold at least `70%` of scoped demand

Action:

- stop trusting the zero-excluded active mean
- fall back to an inclusive mean

Intent:

- prevent isolated branch hits from looking like steady branch demand

### 4. Project-spike suppression

Used for obvious one-time non-replenishment usage.

Intent:

- remove project or job hits from both branch and DC replenishment math

### 5. Single-period pool guard

Used when a non-regional branch has only one scoped selling month and the item still lacks repeat proof.

Action:

- branch can influence its local floor
- branch cannot create pooled DC stock

Intent:

- stop one thin branch hit from seeding network stock

### 6. Sparse regional pool suppression

Used for thin `Regional` branch signals that are too sparse to justify pooled DC uncertainty.

Intent:

- let the explicit regional policy remain in force
- avoid exaggerating thin regional branch noise

### 7. DC sparse active-mean fallback

Used when the DC itself has only `1-2` non-zero scoped months and no pooled branch stock is creating the recommendation.

Action:

- fall back from zero-excluded active mean to inclusive mean

Intent:

- keep the DC from overreacting to a single isolated selling month

## Layer 9: Service Levels And Protection Days

The model translates monthly demand into protected-cycle coverage.

Core rules:

- `raw protection days = lead time + frequency`
- if raw protection days are below `28`, use `28`
- `Local` frequency is treated as `4 weeks`

Service level is driven by `ABC`:

- `A = 99%`
- `B = 92%`
- `C = 88%`
- `D = 84%`
- `E = 80%`
- `X = 80%`

Those percentages are user-editable in the dashboard.

## Layer 10: Base Min / Max Floors

Important internal calculations:

- `daily_demand = monthly_demand / 30.4375`
- `lead_time_demand = daily_demand * lead_time_days`
- `protected_cycle_demand = daily_demand * protection_days`

Branch min:

- demand-only branch floor

DC min:

- only covers the DC's own need across the protected cycle
- does not directly carry branch deviation stock

Branch/DC max:

- built from demand-only order-up-to plus service-level / variance logic

## Layer 11: Branch Logic

For branch locations, the engine generally does this:

1. estimate a branch demand signal
2. apply any spike / intermittent corrections
3. build a branch max from local need
4. decide what uncertainty stays local versus what is pooled

Current pooling behavior:

- ordinary intermittent branches pool variance only
- direct transfer to the DC is only allowed when an explicit spike rule fired

This was a deliberate change to stop every intermittent branch from linearly inflating the DC.

## Layer 12: DC / Balancing Logic

For hub-managed suppliers, the DC is also the balancing location.

The DC recommendation is built from:

- the DC's own rounded demand
- branch max already being held elsewhere
- the largest location deviation
- pooled branch uncertainty

Pooled branch uncertainty now uses:

- pooled variance via root-sum-square
- direct transfer only when an explicit spike rule allows it

This is more stable than summing every branch deviation directly.

## Layer 13: Stocking-Footprint Rules

These are policy rules, not forecasting rules.

### New branch stock gate

To create a new stocking branch from `current max = 0`, the item must show:

- more than 2 selling months in the last 12 months
- at least 3 stocked locations already

### Regional zero-max branch rule

If status contains `Regional` and a branch currently has max `0`:

- that branch stays non-stocked
- the signal is handled through the network policy, not by creating branch stock

### Single-stocked-branch hold

If:

- status is not Regional
- DC current max is `0`
- exactly one non-DC location currently stocks the item

Then:

- that one stocked branch keeps its own need
- other branches cannot create DC stock
- the DC is held at `0`

### Non-stockable location block

If:

- `Stockable != Y`
- `current max = 0`

Then:

- that location cannot seed a new branch max
- that location cannot create DC pooling

## Layer 14: Cost, Override, And Supplier-Minimum Rules

### Low-cost local deviation

If `MAC` is below the configured cutoff:

- deviation stays local instead of being pooled to the DC

Current default:

- `$1.00`

### Override

If `Override = Y`:

- recommended max is locked to current max

### Supplier minimum amount

If `S. Min Amt > 0` and the row still has a positive recommendation:

- final recommended max must be at least `S. Min Amt`

This floor is now enforced late enough that later trimming logic does not accidentally knock a positive max back below the supplier minimum.

## Layer 15: Sparse Seasonal Company Ceiling

This is a company-level protection.

When a seasonal item has:

- thin seasonal history
- very few active in-season months
- a long protection window

the model can cap the network total so one sparse selling season does not explode into a large stocking recommendation.

## Outputs

For each location, the engine emits:

- `recommended_min_amount`
- `recommended_new_max`
- min/max deltas versus current values
- key intermediate values
- rule-hit flags
- a plain-English explanation

For each item summary, it emits:

- total current min/max
- total recommended min/max
- pooled-to-DC and absorbed-by-DC totals
- counts of important rule hits

## What Another Team Should Reproduce First

If another team is reimplementing this engine, the best order is:

1. raw-data normalization
2. negative-return netting
3. reference-window choice
4. season scoping and seasonal ramp
5. spike-protection ladder
6. branch/DC pooling logic
7. stocking-footprint policy rules
8. final floors such as overrides and supplier minimums

Do not start by training a single model to imitate the final max directly without reproducing the intermediate rule logic.

## Plain-English Summary

The engine is designed to be skeptical of isolated demand.

In practice that means:

- returns do not count as demand
- one big month is often normalized
- two-point spikes are flattened
- one-time project usage is suppressed
- thin branch signals usually do not create DC stock
- regional and stocking-footprint rules can override ordinary demand logic
- supplier minimums and overrides still win at the end

That is the current behavior the programmers should treat as the model's source of truth.
