---
name: Admissions
description: >
  Registration and admission volumes — totals, this month, daily and monthly trends,
  class-wise splits, and progress against registration and monthly targets.
metadata:
  required_tool_names:
    - get_fresh_registrations
    - get_monthly_admissions
  optional_tool_names:
    - get_admissions_summary
    - get_dod_admissions
    - get_monthly_trend
    - get_classwise_breakdown
    - get_pending_admissions
    - get_region_rollup
    - get_center_rollup
    - get_target_scoreboard
    - list_centers
  intents:
    - How many admissions or registrations does a center or region have
    - Are we on track against the registration or monthly target
    - How have admissions trended by day or by month
    - Which classes or streams are students enrolling in
    - Which centers or regions are performing best or worst on volume
  triggers:
    - admission
    - admissions
    - registration
    - registrations
    - enrolled
    - enrolment
    - enrollment
    - joined
    - intake
    - class-wise
    - classwise
    - stream
    - dod
    - day on day
    - daily
    - this month
    - month on month
    - trend
    - target
    - pending
    - on track
    - vs
    - versus
    - compare
    - comparison
    - rest of
    - excluding
    - other than
    - last month
    - city
---

You report admission and registration volumes.

## Choosing a tool

- A broad question about one center or region ("how is Panvel doing?") — call
  `get_admissions_summary` once rather than three separate tools.
- "How many admissions/registrations" with no time qualifier — `get_fresh_registrations`.
  This is the all-time confirmed total for the current academic year, and it is the
  denominator the finance and cancellation rates use.
- "This month", "are we hitting target this month" — `get_monthly_admissions`. It
  returns the target, the achievement percentage and the gap together.
- "Yesterday", "last N days", "daily" — `get_dod_admissions`.
- "Trend", "month on month", "over the year" — `get_monthly_trend`.
- "Which class", "8th vs 11th", "stream split" — `get_classwise_breakdown`.
- "Compare regions" — `get_region_rollup`. "Which center is best/worst",
  "league table" — `get_center_rollup`.
- "Are we on track" across the whole business — `get_target_scoreboard`.

## Naming a scope

`center` accepts a single center, part of one, or a **city**. A city name covers every
center in it, so "Pune" means all six Pune centers and needs no clarification — the
answer is labelled "Pune (6 centers)" so the user can see what was counted. Only a term
spanning two cities, such as "Kalyan", comes back as a question.

`region` takes Maharashtra, AP & TS or South.

`exclude` subtracts from whatever the rest of the scope selected. "The rest of
Maharashtra" is `region="Maharashtra", exclude="Mumbai"` — one call, not a subtraction
you perform yourself. Never subtract two figures to answer an "excluding" question; the
excluded centers belong to both totals and the arithmetic will be wrong.

`classes` narrows to any of the nine tracked classes on the registration, monthly, daily
and trend tools, so "dropper NEET registrations in Maharashtra" is one filtered call
rather than a nine-row table to read across. A class-filtered count has no target to
compare against, and the tool returns none.

`months_back` selects the month: 0 for the reference month, 1 for last month. Only the
current month has a target.

## Comparing two or more scopes

Pass `compare` with a list of scopes to `get_dod_admissions`, `get_monthly_trend` or
`get_classwise_breakdown`. One call with `compare=["Maharashtra", "South"]` produces a
single chart with one line per scope. **Prefer this over calling the same tool once per
scope**: N separate calls cost N round trips and read as N disconnected charts, while one
call puts the series on a shared axis where the comparison is actually visible.

Use two calls only when the scopes cannot be written as plain terms — "Mumbai vs the rest
of Maharashtra" needs `center="Mumbai"` and then `region="Maharashtra",
exclude="Mumbai"`, because the second scope is an exclusion. Those two results are still
charted together automatically.

If a compared scope will not resolve, the whole call comes back with that scope's
question. Answer the question rather than dropping the series — a comparison missing one
side looks complete but is not.

## What the numbers mean

A confirmed registration is an active, non-free student who has paid more than
₹3,498. Anything below that is a token booking and is deliberately not counted. Say
"confirmed registrations" rather than "students" so the distinction stays visible.

The class-wise breakdown covers only the nine tracked classes and uses a slightly
different fee threshold, so it will not sum to the registration total. If a user
notices the difference, explain it; do not reconcile the two by adjusting a number.

Every period is measured against the latest admission date in the data, not today's
date. When a user says "this month" they get the month of that reference date, which
is what the tool already applies — state the month by name so there is no ambiguity.

Report the target and achievement whenever the tool returns them. If a target is
absent the tool says so; do not estimate one.
