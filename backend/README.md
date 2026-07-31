# Backend — Architecture Guide

FastAPI service that answers admissions and finance questions by **routing** each
question to one **skill**, which calls **tools** that delegate to a sealed **analytics**
layer over DuckDB, and streams tables and charts back to the browser.

## The one-minute mental model

```
  user question
       │
       ▼
  GUARDRAILS ── injection screening on the way in, PII masking on the way out
       │
       ▼
  MEMORY ────── loads the center/region/metric under discussion
       │
       ▼
  ROUTER ────── picks exactly ONE skill; never answers the question itself
       │
       ▼
  SKILL ─────── a SKILL.md file: prompt text plus the list of tools it may call
       │
       ▼
  TOOL ──────── validates arguments against a pydantic model, then delegates
       │
       ▼
  ANALYTICS ─── sealed business logic: parameterised SQL, exact numbers
       │
       ▼
  ToolResult ── values + optional table/chart + provenance
       │
       ▼
  RUNTIME ───── native table and chart blocks, comparable series merged into one
                chart, staleness note, provenance line
```

Three contracts hold it together:

- **A skill is data.** A directory containing `SKILL.md`: YAML frontmatter declaring
  which tools it may call, plus a markdown body used verbatim as prompt text. Adding a
  skill means adding a file, not writing code.
- **A tool is a validated wrapper.** `@tool(name, description, ParamsModel)` derives the
  OpenAI function schema from a pydantic model and validates arguments before any SQL
  runs. A hallucinated argument becomes a corrective message, not a wrong number.
- **`ToolResult` is the universal envelope.** Either `ok` with `values`, an optional
  table and `ChartSpec`, and a `Provenance`; or not-ok with `unavailable_reason` (the
  source is missing) or `clarification` (the center was ambiguous).

## Why business logic is not inside the tools

`app/analytics/` holds the logic; `app/agent/tools/` holds one-line wrappers:

```python
@tool("get_arpu", "Average revenue per user for a center or region.", ScopeParams)
def get_arpu(center: str | None = None, region: str | None = None) -> ToolResult:
    return revenue.arpu(center=center, region=region)
```

Roughly eight of the 28 tools are composites — `get_finance_summary`,
`get_region_rollup`, `get_target_scoreboard`, `get_arpu_by_center` — that fan out over
the other twenty, so the logic has to be callable from Python and not only from the
model. More importantly, thresholds must be declared once: the workbook deliberately
uses `fees_paid > 3498` for some metrics and `>= 3498` for others, and a second copy of
that literal in a wrapper is a second source of truth that will drift.
`tests/test_tools.py` fails the build if any threshold from `analytics/filters.py`
appears under `agent/tools/`.

## Naming a scope

`analytics/filters.py` turns free text into SQL predicates. Four kinds of scope resolve;
anything ambiguous or unrecognised declines instead.

| Input | Resolves to | Label |
|---|---|---|
| `center="Panvel"` | one center | `Mumbai - Panvel Vidyapeeth` |
| `center="Pune"` | every center in that city | `Pune (6 centers)` |
| `region="Maharashtra"` | one region | `Maharashtra region` |
| `region="Maharashtra", exclude="Mumbai"` | the region minus a city | `Maharashtra region excluding Mumbai (17 centers)` |

Centers are named by city (`Pune - FC Road Vidyapeeth`), so a term matching several
centers of the *same* city is not ambiguous — "Pune" means all six, and asking which one
was meant is the wrong question. A term spanning two cities is genuinely ambiguous and
still asks: `"Kalyan"` exists in both Dombivali and Mumbai. Exact center and region names
always win before any grouping is considered, so `"Nagpur Vidyapeeth"` is that one center
rather than the Nagpur group.

Aggregating trades a clarifying question for an assumption, so the center count is part
of the label and travels into the chart title and the provenance line. The scope is
always visible in the answer.

`exclude` exists because "Mumbai versus the rest of Maharashtra" cannot be answered by
subtracting two figures — the excluded centers are in both totals. It has to be a
predicate, and `tests/test_scope.py` asserts the part plus the rest equals the whole.

## When the model is unreachable

`agent/llm.py` is the only place a model is called. Free endpoints fail transiently, and
some report a server error as a `200` whose `choices` is `null`, which used to surface as
an `AttributeError` far from its cause. Both are normalised into one `LlmUnavailable`
exception after retrying each model in `LLM_FALLBACK_MODELS` in turn.

The more important decision is what a dead model means. A tool result costs a query and
is still true, so when the model dies *after* tools have run, `loop.py` composes the reply
from each `ToolResult.summary` and flags the outcome as degraded — the charts, tables and
provenance render exactly as they would have. Only a turn that gathered nothing reports
the outage, and it does so as a service message rather than as "I cannot answer that",
because the data was never the problem.

## Comparisons are one chart

Two charts side by side force the reader to reconcile two axes before they can compare
two numbers, so a comparison is drawn as one chart with a series per scope wherever it
can be. `analytics/series.py` owns that pivot.

It has two callers because a comparison arrives two ways. The model may pass `compare` to
one tool, which is preferred and costs one round trip; or it may call the same tool once
per scope, in which case `runtime._blocks()` groups results by `(metric, x, kind)` and
merges them. One implementation serves both, since the frontend only knows how to draw
one shape.

The pivot refuses more than it accepts, because a merged chart hides its own mistakes: it
declines when the metrics differ, when two series would carry the same name, or when the
series share no x value at all — two region leaderboards have no centers in common, and
one chart of two disjoint halves is worse than two charts. X values are ordered by
distance from the newest, so a 3-day and a 6-day window ending on the same day interleave
chronologically instead of the shorter one being appended after the longer one.

## Storage split

| Store | File | Holds | Lifetime |
|---|---|---|---|
| DuckDB | `data/analytics.duckdb` | `rd26`, `rd25`, `finance_dump`, `targets` | replaced wholesale each morning |
| SQLite | `data/app.sqlite3` | `users`, `conversations`, `messages`, `conversation_memory`, `meta`, `refresh_runs` | survives every refresh |

The split exists because the analytics file is dropped and rebuilt daily; logins and
chat history cannot live somewhere that gets replaced. `core/migrate.py` moves state out
of the pre-split `app.duckdb` once, on first startup.

## Directory layout (top → bottom by dependency)

```
app/
├── main.py              app factory, lifespan, catch-up refresh scheduler
├── models.py            wire schemas (request/response, renderState, content blocks)
│
├── api/                 HTTP layer (thin)
│   ├── auth.py            POST /auth/login
│   ├── chat.py            POST /chat, POST /chat/stream
│   └── admin.py           GET /health, GET /meta, GET /refresh/history, POST /refresh
│
├── agent/               THE AI ENGINE
│   ├── llm.py             the only model call: retries, model fallback, LlmUnavailable
│   ├── router.py          skill selection: LLM choice, deterministic keyword fallback
│   ├── loop.py            capped tool-calling loop, scoped to the chosen skill's tools
│   ├── runtime.py         orchestration; ToolResult → table/chart blocks + provenance
│   ├── memory.py          conversation slots, context injection, scope inheritance
│   ├── prompts.py         shared rules, data dictionary, prompt composition
│   ├── skills/
│   │   ├── loader.py        SKILL.md frontmatter parser and validation
│   │   ├── __init__.py      registry; verifies every declared tool exists at import
│   │   └── definitions/     admissions, finance, revenue, retention,
│   │                        cancellations, data-explorer, knowledge
│   └── tools/
│       ├── registry.py      @tool decorator, schema derivation, parameter models
│       ├── admissions_tools.py  finance_tools.py  explorer_tools.py
│
├── guardrails/          CROSS-CUTTING SAFETY
│   ├── input_scanners.py  block prompt injection and jailbreak attempts
│   └── output_scanners.py mask residual PII
│
├── analytics/           SEALED BUSINESS LOGIC (pure functions over DuckDB)
│   ├── result.py          ToolResult, Provenance, ChartSpec
│   ├── filters.py         thresholds; scope resolution (center/city/region/exclude)
│   │                      and class filters, as SQL predicates
│   ├── series.py          pivots single-series results into one multi-series chart
│   ├── query.py           count/avg/sum/select helpers, provenance, target lookup
│   ├── admissions.py  finance.py  revenue.py  retention.py  cancellations.py
│   ├── rollups.py         region/center roll-ups, target scoreboard
│   └── explorer.py        guarded ad-hoc SELECT
│
├── data/                DATA LAYER
│   ├── schema.py          tables, typed columns, required columns, PII columns
│   ├── sources/           base.py, google_sheets.py, excel.py, sample.py
│   ├── tabular.py         typed staging load and atomic swap
│   ├── ingestion.py       refresh() and audited run_refresh()
│   ├── availability.py    what is loaded, how fresh, what is missing
│   ├── reference_date.py  data-anchored "today" (MAX(joining_date)) and month offsets
│   ├── registry.py        center/city/region resolver with clarification
│   └── conversation.py    chat history
│
├── core/                FOUNDATIONS
│   ├── config.py          settings from .env
│   ├── logs.py            logging config + per-request correlation ids
│   ├── database.py        DuckDB: read-write plus a read-only snapshot for the explorer
│   ├── appdb.py           SQLite app state
│   ├── migrate.py         one-time move out of the pre-split DuckDB file
│   └── security.py        bcrypt + JWT
│
└── streaming/           SELF-CONTAINED SSE
    ├── events.py          frame builders (run-*, text-message-*, state-delta)
    └── sse.py             turn → event stream
```

## Ingestion

`DATA_SOURCE` selects exactly one of `gsheets`, `excel` or `sample`. There is no fallback
chain: if the chosen source fails, the refresh is recorded as failed and the last good
data stays in place. Silently synthesising numbers when the sheet is unreachable is
indistinguishable from success, which is worse than an outage.

Each table is read in 5000-row windows, loaded all-`VARCHAR` into `<table>__raw`, cast
into `<table>__staging` per the types in `data/schema.py`, then atomically swapped into
place — so the write lock is held only for a rename, and a mid-load failure leaves the
previous data intact. Missing tabs are recorded by `availability.py`, and the tools that
depend on them decline with a reason.

The scheduler is catch-up driven rather than sleep-until: it compares a persisted
`last_success` against the most recent elapsed 08:30 Asia/Kolkata cutoff, so a process
that was down at 08:30 refreshes as soon as it is back, and one that was up refreshes
exactly once.

## Logging

`core/logs.py` owns configuration. Nothing else calls `basicConfig`, and every module
just does `log = logging.getLogger(__name__)`, so the logger name tells you which layer a
line came from.

Each line carries a **request id**, held in a context variable and stamped on by a filter
attached to the handler — so records from uvicorn and third-party libraries carry it too.
The id is also returned as the `X-Request-Id` response header, and an inbound
`X-Request-Id` is honoured, so a user reporting "that answer was wrong at 3pm" can be
traced without guessing from timestamps. One chat turn reads as a single story:

```
INFO app.core.security  [4f2127d02d4d] Login succeeded for 'admin'
INFO app.main           [4f2127d02d4d] POST /auth/login -> 200 in 231ms
INFO app.agent.runtime  [72570db92f32] Turn starting: how many registrations this month?
INFO app.agent.runtime  [72570db92f32] Routed to admissions via keyword (matched registrations, this month)
INFO app.agent.loop     [72570db92f32] Tool get_monthly_admissions() -> ok in 34ms
INFO app.agent.runtime  [72570db92f32] Turn done in 812ms: skill=admissions tools=[get_monthly_admissions] blocks=2 chars=412
INFO app.main           [72570db92f32] POST /chat -> 200 in 818ms
```

What is deliberately logged, and why:

| Event | Level | Why it matters |
|---|---|---|
| Login success and failure | INFO / WARNING | The data is student PII, so who queried it is part of the audit trail |
| Blocked input, with the rule that fired | WARNING | A guardrail block is a security event worth reviewing |
| Explorer query, and every refusal | INFO / WARNING | The only place model-written SQL reaches the database |
| One line per tool call, with arguments and duration | INFO | How a given number was produced, and what was slow |
| Tool budget exhausted | WARNING | The model is looping instead of answering |
| Serving stale data | WARNING | Pairs with the warning the user sees in the reply |
| Insecure defaults at startup | WARNING | Default `JWT_SECRET` or admin password in a real deployment |
| Refresh outcome and per-table row counts | INFO | Whether this morning's data actually landed |

`LOG_LEVEL=DEBUG` adds model round-trip timings and the memory slots in scope. Set
`LOG_FORMAT=json` for one object per line, `LOG_FILE=./data/agent.log` to add a rotating
file alongside the console. Noisy libraries (`httpx`, `openai`, `googleapiclient`) are
capped at WARNING so they cannot bury the application's own lines.

Two caveats worth knowing. `run.py` passes `log_config=None` to uvicorn, because
uvicorn's default configuration would otherwise replace the formatter and drop the
request id; uvicorn's access log is disabled for the same reason, since the middleware
logs the same information with the id attached. And `/health` is not logged, because a
monitor polling it would drown everything else.

## Adding a skill

1. Add the metric functions to `app/analytics/<domain>.py`, returning `ToolResult`. Put
   any new threshold in `analytics/filters.py`.
2. Add one-line wrappers in `app/agent/tools/<domain>_tools.py` using `@tool`.
3. Create `app/agent/skills/definitions/<skill-id>/SKILL.md` with frontmatter naming the
   tools, plus `intents` and `triggers` for the fallback router, and a markdown body
   telling the model how to use them.

Nothing else needs editing. The registry discovers the directory, validates the tool
names at import, and both routers start considering the skill immediately.

## Invariants

- Every number in a reply comes from a `ToolResult`. The model writes no SQL for a known
  metric.
- The router selects a skill and never answers.
- The explorer is `SELECT`-only, single-statement, row-capped, PII-denied, and runs on a
  read-only `ATTACH` with external file access disabled.
- Missing data produces an explicit decline, never a synthesised figure.
- Every answer carries the reference date, and a staleness warning when the refresh is
  overdue.
- A scope that aggregates says how many centers it covered, in the label, the chart title
  and the provenance.
- A model outage never discards a tool result that already came back.
- A comparison renders as one chart, or as separate charts — never as a merge the pivot
  could not justify.

## Tests

```bash
pytest tests/
```

No model or network access is needed: `tests/conftest.py` redirects every path into a
temp directory and loads the synthetic dataset, and the router tests exercise the
deterministic fallback — which is also what runs in production whenever the model is
unreachable.

| File | Covers |
|---|---|
| `test_skills.py` | frontmatter validity, every declared tool exists, every tool is reachable |
| `test_tools.py` | schema shape, argument validation, no thresholds or SQL in wrappers |
| `test_router.py` | keyword routing, and that every trigger selects its own skill |
| `test_memory.py` | slot persistence, scope inheritance, global-scope override |
| `test_explorer.py` | writes, escapes, multi-statement and PII attempts all refused |
| `test_parity.py` | analytics invariants, plus a golden-value harness for the workbook |
| `test_render.py` | table/chart block shapes, dedupe, refresh catch-up logic |
| `test_scope.py` | city grouping, exclusion arithmetic, month offsets, class filters |
| `test_compare.py` | `compare` and auto-merge produce one chart; what the pivot refuses |
| `test_llm.py` | retry, model fallback, and that tool results survive a dead model |
| `test_logs.py` | logging config is idempotent, correlation ids reach the output |
