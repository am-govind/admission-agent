# Admissions & Finance AI Agent � Design & Architecture Spec

_Status: implemented. Derived from a grilling session on 2026-07-19 and `Business_Logic_Report_DETAILED.pdf`._

_Sections 1, 4, 5 and 6 still describe the system as built. Section 2 is preserved as the
original decision record; where implementation changed a decision, §2.1 says so and why.
The current code layout is documented in [backend/README.md](backend/README.md)._

## 1. Purpose

A **read-only** ("Action = none") conversational AI agent that answers natural-language
questions about the Maharashtra / South / AP&TS student-admissions business, by running the
**deterministic "blackbox" business logic** (the COUNTIFS/AVERAGEIFS rules from the business-logic
report) against a fresh daily data dump. Answers may include prose, a masked 5-row data preview,
tables, and matplotlib charts � all streamed into a chat window.

The agent **never writes** anything back to the source and **never invents a number**.

## 2. Decisions Locked (from grilling)

| # | Area | Decision |
|---|------|----------|
| 1 | Deliverable shape | **Standalone app** (own TS frontend + FastAPI backend + Ollama). Highspot ChatUI/SSE contract used as a *reference*, not a hard dependency. |
| 2 | Data source | **Google Sheets API** (service account), pulled each morning. |
| 3 | Storage / compute | **DuckDB** � each tab ? a table; every rule ? parameterized SQL. |
| 4 | Blackbox binding | **Fixed, sealed parameterized tools.** The LLM only selects a tool + extracts params; it never writes SQL. Numbers are always exact and auditable. |
| 5 | "RAG" role | **No vector DB.** Data dictionary + tool catalog live in the system prompt (small enough). Grounds tool selection + answers definitional questions. |
| 6 | LLM | **Qwen2.5** via Ollama (14B or 32B depending on VRAM). |
| 7 | Streaming | **v2-style SSE**: `renderState` + `state-delta` (RFC-6902 JSON Patch) + `text-message-*` token deltas. |
| 8 | Chart delivery | **matplotlib server-side ? PNG ? base64 data-URI** in an `image` content block. No file lifecycle. |
| 9 | Viz triggers | **Per-output tools**: `preview_columns`, `get_metric` family, `plot_trend`. LLM chooses. |
| 10 | Guardrails | **LLM-Guard both directions.** Input: prompt-injection/jailbreak/topic. Output: aggregates only; row-level `student_name`/`regno` **masked**. PII stays internal for computation. |
| 11 | Memory | **Persisted** conversation history in SQLite/DuckDB keyed by `conversationId`; backend is source of truth, UI history is a hint. |
| 12 | Tabs ingested | `RD26_DUMP`, `RD25_DUMP`, `Finance Dump`, **plus a targets table**. |
| 13 | Targets | Ingest a targets table (center/region/class) so % achievement, pending-to-target, ARPU delta/profit-loss work. |
| 14 | Scheduling | **APScheduler** morning job **replaces** working tables + manual `POST /refresh`. No multi-day snapshots (trends come from `joining_date`). |
| 15 | Reference date | Anchored to **data**: `reference_date = MAX(joining_date)` in current `RD26_DUMP` (like sheet `B1`). "Yesterday"/"this month" derive from data, not server clock. |
| 16 | Frontend | **React + Vite + TypeScript + Tailwind**; block-renderer registry + SSE/JSON-Patch client. |
| 17 | Auth / deploy | **User table** auth (bcrypt + token, per-user audit trail), internal GPU VM behind VPN. SSO/OIDC deferred. |
| 18 | Tool scope (v1) | **Full catalog** � every PDF metric + preview + plot + roll-ups. |
| 19 | Transparency | **Answer + concise provenance** (tool, filters applied, reference date). |
| 20 | Ambiguity | Resolve against a center/region registry; **clarify** on multiple/no match; default missing time period to reference-date MTD (and say so). |
| 21 | Out-of-scope | Answer definitional questions from the data dictionary; **honestly decline** causal/predictive/unrelated; never fabricate. |
| 22 | Data fidelity | **Replicate each formula EXACTLY per-metric** (`>3498` vs `>=3498`, `"False"` string vs `FALSE` bool, `*token*`, `*Disbural*` typo). Parity with the sheet is the goal, not "fixing" it. |
| 23 | Validation | **Golden-parity harness**: assert each tool == sheet's computed values per center/metric on each refresh; alert on drift. |
| 24 | Language | Accept English + Hindi/Hinglish; reply in user's language; **Indian money formatting** (?, lakhs/crores). |

## 2.1 Amendments During Implementation

| # | Original | Now | Why |
|---|----------|-----|-----|
| 3 | DuckDB for everything | **DuckDB for analytics, SQLite for app state** | The analytics file is dropped and rebuilt by every refresh. Users, chat history and conversation memory cannot live in a file that gets replaced. `core/migrate.py` moves pre-split state across once. |
| 4 | Sealed tools the LLM selects | **Unchanged, with the seam moved**: logic in `analytics/`, tools are validating wrappers | Eight of 28 tools are composites that fan out over the others, so the logic must be callable from Python, not only from the model. Thresholds are declared once in `analytics/filters.py`; a test fails the build if a threshold literal appears under `agent/tools/`. |
| 6 | Qwen2.5 via Ollama | **Any OpenAI-compatible endpoint**, defaulting to GitHub Models `gpt-4.1` | Native tool-calling made the provider interchangeable. Ollama and vLLM still work by changing two env vars. |
| 8 | matplotlib → base64 PNG image block | **Native `chart` content blocks rendered by Recharts** | A PNG cannot be hovered, resized or read by a screen reader, and it put a plotting library and font cache in the request path. The chart now ships as the tool's own data plus a `ChartSpec`. |
| 11 | Persisted transcript keyed by conversation | **Transcript plus explicit memory slots** | A follow-up needs the center, region and metric under discussion — a handful of short values. Storing them explicitly makes "and for Pune?" work, and makes what was inherited visible in provenance instead of silently scoping a number. |
| 14 | APScheduler morning job | **Catch-up scheduler** driven by a persisted `last_success` | A cron-style job that fires at 08:30 does nothing if the process was down at 08:30. Comparing against the last elapsed cutoff refreshes exactly once, and immediately after a restart. Ingestion also does not fabricate data when the source fails: the run is recorded as failed and the previous data stands. |
| 23 | Golden-parity harness | **Invariant harness in place; golden values pending the workbook export** | The invariants (ratios stay fractions, parts sum to the whole, scoped counts never exceed global) catch filter drift today. `GOLDEN` in `tests/test_parity.py` is the one dict to fill for cell-for-cell agreement. |

## 3. Architecture

```
??????????????????????????????????????????????????????????????????
? Frontend � React + Vite + TS + Tailwind                         ?
?  � Chat view                                                    ?
?  � SSE client ? applies JSON-Patch to renderState              ?
?  � Block-renderer registry: text | table | image | code        ?
??????????????????????????????????????????????????????????????????
                ?  POST /chat/stream (SSE)  �  POST /chat (REST)
                ?  simple-auth token
??????????????????????????????????????????????????????????????????
? Backend � Python FastAPI                                         ?
?                                                                 ?
?  Chat layer:  Pydantic AI agent (Qwen2.5 via Ollama)           ?
?    � system prompt = data dictionary + tool catalog            ?
?    � LLM-Guard (input + output scanners, PII masking)          ?
?    � SSE emitter (v2 events + state-delta)                     ?
?    � conversation store (SQLite/DuckDB)                        ?
?                                                                 ?
?  Blackbox tools (sealed):  metric fns ? parameterized DuckDB   ?
?    � center/region registry resolver                          ?
?    � matplotlib chart renderer ? base64 PNG                   ?
?                                                                 ?
?  Data layer:  DuckDB (RD26, RD25, Finance Dump, targets)       ?
?                                                                 ?
?  Ingestion:  APScheduler morning job + POST /refresh           ?
?    � Google Sheets API pull ? Pydantic validate ? replace      ?
?    � parity harness (golden values) ? drift alert              ?
???????????????????????????????????????????????????????????????????
```

### 3.1 Engine: Router -> Skill -> Tool -> Analytics (implemented)

The flat agent was replaced by a layered engine, held together by three contracts:

- **A skill is data.** `agent/skills/definitions/<id>/SKILL.md` — YAML frontmatter naming
  the tools it may call, plus `intents` and `triggers` for the fallback router, and a
  markdown body used verbatim as prompt text. Seven skills: Admissions, Finance, Revenue,
  Retention, Cancellations, Data Explorer, and Knowledge (definitions, greetings, honest
  out-of-scope; no tools). Adding a skill is adding a file.
- **A tool is a validated wrapper.** `@tool(name, description, ParamsModel)` derives the
  OpenAI function schema from a pydantic model and validates arguments before any SQL
  runs, so a hallucinated argument becomes a corrective message rather than a wrong
  number. 28 tools, all one-liners delegating to analytics.
- **`ToolResult` is the universal envelope.** `ok` with `values`, an optional table and
  `ChartSpec`, and a `Provenance`; or not-ok with `unavailable_reason` (source missing) or
  `clarification` (ambiguous center).

The **router** (`agent/router.py`) picks exactly one skill and never answers. It prefers an
LLM choice and falls back to scoring the frontmatter triggers and intents, so routing
still works with no model reachable.

### Request flow
1. User asks a question -> frontend `POST /chat/stream`.
2. Guardrails scan the input (injection, jailbreak).
3. Memory loads the center/region/metric slots for the conversation.
4. **Router** picks one skill (LLM, keyword fallback); the UI shows the decision.
5. **Loop** (`agent/loop.py`) runs a capped tool-calling loop offering only that skill's
   tools. Omitted center/region are inherited from memory, and every inheritance is
   recorded in provenance.
6. Each **tool** validates its arguments and delegates to a sealed **analytics** function,
   which runs parameterised DuckDB SQL anchored to the reference date. Ambiguous centers
   come back as a clarification; missing sources as an explicit decline.
7. The model composes prose from the returned `ToolResult`s; guardrails mask residual PII.
8. **Runtime** turns each result into native `table` and `chart` blocks, prepends a
   staleness note when the refresh is overdue, and appends the provenance line.
9. Backend streams `run-started -> thinking-start -> processing-status (per tool call) ->
   thinking-end -> state-delta (chart/table blocks) -> text-message-* deltas ->
   state-delta (provenance) -> run-finished`.
10. Frontend applies the JSON patches and renders blocks incrementally.

### 3.2 Repo structure (implemented)
Layered top -> bottom by dependency: `api/` (HTTP) -> `agent/` (router, skills, tools,
loop, memory) -> `analytics/` (sealed logic) -> `data/` (sources, ingestion, availability,
registry, reference date) -> `core/` (config, DuckDB, SQLite, security), plus
`guardrails/` (cross-cutting input/output safety) and `streaming/` (SSE). See
[backend/README.md](backend/README.md).

## 4. Tool Catalog (v1 � full)

All tools honor the standard filter set unless noted, and each replicates its source formula **exactly**.

**Metric tools**
- `fresh_registrations(center, region, date_cutoff?)` � `L>3498`, not-free, Active.
- `registration_achievement_pct(center, region)` � needs target.
- `senior_retention(center, region)` � two-part RD25 formula (`Total Paid` + `4th EMI Paid`, `enrolled_years>1`, `<>Admission Cancelled`); `senior_retention_pct` needs target.
- `monthly_admissions(center, region)` (+ `_pct`, + `pending_to_target`) � current month via EOMONTH logic on reference date.
- `dod_admissions(center, region, date)` and `dod_trend(center, region, days=20)`.
- `monthwise_trend(center, region)`.
- `classwise_breakdown(center)` � 8th�Dropper NEET (`>=3498`, `*<class>*` wildcards).
- `finance_1st_emi(center)` (+ `_pct`) � `>=3498`, `N <> *token*`.
- `autopay(center, region)` (+ `_pct`) � `R` not blank, `<>*Disbural*`, `<>*Cancel*`.
- `loan_eligibility(center, region)` � eligible / not-eligible (+ `_pct`).
- `second_emi(center, region)` � base (Finance Dump two-part), paid, `_pct`, `delta`.
- `arpu(center, region)` � current, delta, shortfall %, profit/loss label, revenue-in-crores.
- `cancellations(center, region)` � count + rate (note: cancellation count does NOT filter free/active/fees).

**Utility tools**
- `preview_columns(table, n=5)` � masked sample (names/reg-numbers never projected).
- `describe_tables`, `list_centers`, `get_data_freshness` � schema and availability.
- `explore_data(sql, limit?)` � guarded ad-hoc `SELECT` for questions no metric tool
  covers: single statement, row-capped, PII columns denied, running on a read-only
  `ATTACH` with external file access disabled.
- Roll-ups: center ? region subtotal ? grand total for every metric, plus
  `get_target_scoreboard`.
- Charting is not a tool. Any metric result that is worth plotting carries a `ChartSpec`,
  and the runtime emits the chart block � so the model cannot choose to visualise
  something it did not measure.

## 5. Data-Fidelity Notes (must replicate, do NOT normalize)
- Threshold: fresh-reg `L>3498`; class-wise & Finance `Reg` `L>=3498`. Kept per-metric.
- `free_admission` compared as both `"False"` (string) and `FALSE` (bool) across formulas.
- `newpayment_checks` wildcard `<>*token*`; `2nd EMI` also `<>1st EMI Paid`.
- `ep_status` autopay excludes `*Disbural*` (source typo � matched verbatim) and `*Cancel*`.
- `cancellations` uses only center + `form_status = 'Admission Cancelled'` (no free/active/fees filter).
- Finance Dump has **different column letters** than RD26_DUMP (J=center, A=region, T=scheme, I=status, P=payment, D=batch).

## 6. Guardrails & PII
- Aggregate-analytics posture: PII (name, regno) used internally for computation, **never emitted**.
- `preview_columns` and any row-level output mask/anonymize name + regno.
- Input scanners: prompt-injection, jailbreak, off-topic/toxic.
- Output scanners: PII leak, plus a final "no fabricated numbers" posture (numbers only ever come from tools).

## 7. Phased Build Plan

**Phase 0 � Foundations**
- Repo scaffold: `backend/` (FastAPI, DuckDB, Pydantic AI, LLM-Guard), `frontend/` (Vite React TS), shared type defs.
- Google Sheets service-account auth + `POST /refresh` pulling `RD26_DUMP` into DuckDB with Pydantic schema validation.
- Center/region registry from distinct data values.

**Phase 1 � End-to-end thin slice**
- One sealed tool (`fresh_registrations`) + `preview_columns`.
- Pydantic AI agent on Qwen2.5/Ollama with data-dictionary system prompt.
- v2 SSE streaming (`run-*`, `text-message-*`, `state-delta`) + React block renderer (text + table).
- Simple auth gate.

**Phase 2 � Full metric catalog**
- All admission/registration/monthly/DOD/classwise/finance/ARPU/cancellation tools + roll-ups.
- Targets table ingest ? % achievement / pending / ARPU delta / profit-loss.
- RD25 + Finance Dump ingest.
- Reference-date anchoring across all time-relative tools.

**Phase 3 � Visualization & polish** (done, via chart blocks rather than PNGs)
- Native `chart` blocks driven by each metric's `ChartSpec` (DOD, monthwise, classwise,
  region roll-ups).
- Provenance notes, ambiguity clarification flow, out-of-scope handling, Hinglish + Indian formatting.

**Phase 4 � Trust & ops**
- Done: invariant parity harness, refresh audit trail in `refresh_runs`, failure alerting
  (log + email), catch-up scheduler, guardrail and explorer-escape tests, freshness
  reporting on `GET /meta` with a staleness warning on every answer.
- Remaining: export golden values from the workbook into `GOLDEN` in
  `tests/test_parity.py` for cell-for-cell agreement, and deploy behind the VPN.

## 8. Resolved Configuration

### 8.1 Google Sheet + Targets (ASSUMED for now — confirm before ingest)
- Sheet ID + service-account credentials come from env/config: `GSHEET_ID`, `GOOGLE_APPLICATION_CREDENTIALS`. Placeholder until the real workbook is shared.
- **Assumed targets tab**: a tab named `Targets` with one row per (region, center) and columns:
  `region, center, class_course, reg_target, retention_target, monthly_target, arpu_target`.
  - `class_course` is optional (blank = center-level target); populated rows enable class-wise targets.
- Ingested into a DuckDB `targets` table; joined by `(region, center[, class_course])` for all % / delta / pending / profit-loss metrics.
- **To confirm later:** real Sheet ID, actual targets tab name + exact layout (adjust column mapping if different).

### 8.2 LLM — Qwen2.5 (free, open-weight, Apache-2.0)
- Runs locally via Ollama at zero API cost; only GPU/VRAM required.
- Size chosen by VM VRAM (4-bit quant): **32B if ≥24 GB** (preferred — best tool-calling), **14B if 12–16 GB**.
- Model tag configurable via env `OLLAMA_MODEL` (e.g. `qwen2.5:32b-instruct`).

### 8.3 Auth — User Table (free)
- v1 uses a **user table** (username + bcrypt-hashed password) in the app DB, session/JWT token gating all endpoints.
- Chosen over shared-secret because it gives a **per-user audit trail** (who queried what) — important with student PII.
- All three options are software-free; **SSO (OIDC)** is a later upgrade with no extra cost *if* the company IdP already exists. Deferred to post-v1.

### 8.4 Parity-Drift Alerts — Email + Log
- Golden-parity harness runs on every morning refresh.
- On drift: write a structured **log** entry (level=ERROR, per center/metric diff) AND send an **email** to a configurable recipient list (`ALERT_EMAIL_TO`, SMTP via env).
- No Slack in v1.
