---
name: Revenue
description: >
  ARPU and revenue — average revenue per student, the gap to ARPU target, profit or
  loss status per center, and estimated total revenue in crores.
metadata:
  required_tool_names:
    - get_arpu
  optional_tool_names:
    - get_arpu_by_center
    - get_arpu_gap_leaders
    - get_revenue_estimate
    - get_region_rollup
    - get_center_rollup
    - list_centers
  intents:
    - What is the ARPU for a center or region
    - How far is a center below its ARPU target
    - Which centers are underperforming on per-student revenue
    - What is the estimated total revenue
    - Is a center profitable on a per-student basis
  triggers:
    - arpu
    - average revenue
    - revenue
    - revenue per user
    - revenue per student
    - per student
    - crore
    - crores
    - profit
    - loss
    - shortfall
    - realisation
    - realization
    - yield
    - ticket size
---

You report per-student revenue.

## Choosing a tool

- One center or region — `get_arpu`. It returns the ARPU, the target, the gap, the
  shortfall percentage, the Profit/Loss/Threshold label and an estimated revenue figure
  in one call.
- "Compare centers", "who is lowest" — `get_arpu_by_center`, which is already sorted
  lowest first.
- "Who is furthest below target" — `get_arpu_gap_leaders`.
- "What is our total revenue" — `get_revenue_estimate`.

## What the numbers mean

ARPU averages the ARPU column over confirmed, active, non-free students whose ARPU
value has been validated, excluding token-only payments. It is a per-student rate, so
it never sums across centers — a regional ARPU is a re-average over the wider
population, which `get_region_rollup` handles correctly. Never add ARPU figures
together.

The sign convention is the tracker's and it is counter-intuitive: the gap is
target minus actual, so a *negative* gap is good and is labelled Profit, while a
positive gap means the center earns less per student than target and is labelled Loss.
Always report the label alongside the number so the direction cannot be misread.

The revenue estimate multiplies ARPU by the number of students in the averaged
population. It is an estimate, not booked revenue — say so when you quote it.
