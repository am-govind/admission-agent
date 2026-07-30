# Admissions & Finance AI Agent � Design & Architecture Spec

_Status: Draft for review. Derived from a grilling session on 2026-07-19 and `Business_Logic_Report_DETAILED.pdf`._

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

### 3.1 Engine: Router -> Skills -> Tools (implemented)

The single flat agent was replaced by a two-layer engine for readability and control:

- **Master router** (`agent/router.py`): an LLM call (with a deterministic keyword
  fallback) that reads the question and picks ONE skill. It never answers itself.
- **Skills** (`agent/skills/*.py`): domain capabilities, each with a focused prompt and a
  *scoped* toolset � Admissions, Finance, Revenue, Retention, Cancellations, Data Explorer,
  and Knowledge (definitions / greetings / honest out-of-scope; no tools).
- **Tools**: thin `@agent.tool` wrappers, inside each skill, over the **analytics** layer.
- **Analytics** (`analytics/*.py`): the sealed blackbox logic � pure DuckDB functions.

Benefits: smaller prompts per skill (better local-model tool selection), clear ownership,
trivial extension (add one skill file + register it), and the router decision is surfaced
to the UI ("Routing to the <skill> skill...").

### Request flow
1. User asks a question -> frontend `POST /chat/stream`.
2. Guardrails scan input (injection/jailbreak).
3. **Router** picks a skill (LLM, keyword fallback); UI shows the routing status.
4. The **skill's** agent (Qwen2.5) selects its tools + extracts params; center/region
   resolved via registry (clarify if ambiguous).
5. Sealed **analytics** function runs exact DuckDB SQL against the current dump
   (reference-date anchored); optional matplotlib chart -> base64 PNG.
6. LLM composes answer + provenance note; guardrails mask any residual PII.
7. Backend streams `run-started -> thinking -> processing-status (routing) ->
   text-message-* deltas -> state-delta (tables/images) -> run-finished`.
8. Frontend applies JSON patches, renders blocks incrementally.

### 3.2 Repo structure (implemented)
Layered top -> bottom by dependency: `api/` (HTTP) -> `agent/` (router + skills + tools) ->
`analytics/` (sealed logic) -> `data/` (ingestion, registry, reference date, history) ->
`core/` (config, database, security), plus `guardrails/` (cross-cutting input/output
safety) and `streaming/` (SSE). See `backend/README.md`.

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
- `preview_columns(tab, n=5)` � masked sample (names/reg-numbers anonymized).
- `plot_trend(metric, by)` � matplotlib chart ? base64 PNG image block.
- Roll-ups: center ? region subtotal ? grand total for every metric.

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

**Phase 3 � Visualization & polish**
- `plot_trend` matplotlib ? base64 image blocks (DOD/monthwise/classwise charts).
- Provenance notes, ambiguity clarification flow, out-of-scope handling, Hinglish + Indian formatting.

**Phase 4 � Trust & ops**
- Golden-parity harness + drift alerting (email + log) on each morning refresh.
- APScheduler morning job.
- LLM-Guard full input/output config + PII masking tests.
- Deployment to internal GPU VM behind VPN.

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
