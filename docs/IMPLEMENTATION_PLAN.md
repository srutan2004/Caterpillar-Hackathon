# TerraPilot — Implementation Plan

> Intelligent operator companion for heavy equipment (excavator, wheel loader, articulated dump truck).
> "TerraPilot" is a placeholder product name. Swap it in `config/app.yaml`. The UI reads the name from config, so it appears nowhere in the code.

> **Revision 2 (final)** adds the following. Nothing from revision 1 was removed.
> - **Groq cloud LLMs** wherever an LLM is used: an LLM gateway, a per-task model map, fallbacks and rate-limit handling (§4.1, §12.3).
> - **Sensor-based equipment/vehicle maintenance alerts** (§10.13).
> - **Optimal job start-time recommendation**, using environment, vehicle condition and charge/fuel as factors (§10.14).
> - **Companion maintenance-planning and estimation features** (§10.15): maintenance window, repair duration/cost, energy per task, readiness score, weather windows, machine selection and more.
>
> These additions are also woven into the dataset (§7), schema (§8), APIs (§9), models (§11), evals (§13), build plan (§16) and demo (§18).
>
> **Revision 3** reorganises the build plan (§16) into **4 phases**. The old phases 0–6 map onto them like this, with every task kept word for word:
> - old 0 + 1 → Phase 1 (1A, 1B);
> - old 2 + 3 → Phase 2 (2A, 2B);
> - old 4 + 5 → Phase 3 (3A, 3B);
> - old 6 → Phase 4.
>
> No feature was modified or removed.

---

## 0. How to read this document

| Section | What it gives you |
|---|---|
| 1 | Traceability from the problem statement to features. Use this list to check we have covered everything the judges will score |
| 2 | Non-negotiable engineering principles, including the **zero-hardcoding contract** |
| 3 | System architecture and runtime data flow |
| 4 | Tech stack, with the reason for each choice, and the **Groq LLM usage map** (§4.1) |
| 5 | Repository layout |
| 6 | The configuration system: manifests, rules, UI layouts, i18n, theme |
| 7 | **Synthetic dataset**: entities, generator design, scenarios, ground truth |
| 8 | Database schema |
| 9 | Backend services and API contracts |
| 10 | Feature specs, one per feature: logic, config keys, UI, acceptance criteria. Includes the new §10.13 maintenance alerts, §10.14 start-time recommender and §10.15 estimation suite |
| 11 | ML models: training, evaluation, serving |
| 12 | AI Copilot: Live mode, Ask mode, and the Groq LLM gateway (§12.3) |
| 13 | Guardrails and evals |
| 14 | Frontend architecture (server-driven UI) |
| 15 | Testing, CI, and tooling |
| 16 | Build plan in **4 phases** (with sub-phases, checkpoints and priorities) |
| 17 | Team workstreams |
| 18 | Demo script |
| 19 | Risks and mitigations |

Priority tags used throughout:

- **P0**: demo-critical. It must work live.
- **P1**: strong-to-have. It should work, and can run on replayed or staged data.
- **P2**: stretch. It can be mocked, but it is still driven by config and data, never faked in the UI.

---

## 1. Problem statement → feature traceability

| Problem-statement outcome | TerraPilot features (section ref) | Priority |
|---|---|---|
| **Daily task dashboard**: view scheduled tasks for the day | Shift task list + timeline, per-task ETC with confidence band, shift pacing gauge, pre-shift walkaround, voice cab notes (§10.3) | P0 |
| **Safety: seatbelt compliance** | Seat-occupancy + buckle rule with grace period → escalation, per-shift compliance %, supervisor rollup (§10.4.1) | P0 |
| **Safety: proximity hazards** | Pedestrian trajectory + time-to-collision, machine-to-machine P2P proximity, swing-envelope zones, utility and powerline geofences (§10.4.2–10.4.4) | P0 |
| **Safety: incident logging** | Automatic black-box capture (pre/post ring buffer), manual and near-miss report forms, playback timeline (§10.4.8) | P0 |
| **Safety: working conditions** | Weather, wind, heat, visibility and lightning rules, ground/terrain risk score, fatigue, whole-body vibration dose (§10.4.6, §10.4.7, §10.7.2) | P0/P1 |
| **Operator training hub**: e-learning videos, instructor booking, simulation module | Video lessons + quizzes, instructor slot booking, browser 3D simulator with scored drills, adaptive assignment, certification gating (§10.8) | P0 (videos, booking, adaptive), P1 (simulator) |
| **Unusual behaviour**: excessive idling, unsafe patterns | Rule + statistical + ML anomaly detection, idle fuel/CO₂ cost, unsafe-pattern catalogue, operator scorecard (§10.5) | P0 |
| **Task time estimation**: from past data + environmental conditions | Quantile gradient boosting + conformal calibration, live Bayesian ETC update, SHAP "why" factors, backward scheduling (§10.6) | P0 |
| **Equipment/vehicle maintenance alerts from sensor values** (team addition) | Limit, rate-of-change, time-to-threshold forecast, multivariate signatures, fleet-peer drift, service-interval counters, fluid-sample limits → maintenance alert lifecycle + work orders (§10.13) | P0 (limit/trend/forecast), P1 (signatures/peer) |
| **Recommended job start time** (team addition): finish faster than usual | Start-time optimiser over forecast weather, ground drying, machine health, SoC/fuel + charging, truck availability, operator fatigue → best start, time saved vs. usual, preconditions (§10.14) | P0 (single task), P1 (whole-day plan) |
| **Companion maintenance and estimation features** (team addition) | Maintenance window recommendation, repair duration/cost estimate, energy/fuel per task + "can I finish on this charge?", recharge/refuel time, wear/cost per task, readiness score, weather-window finder, machine selection, 7-day availability forecast (§10.15) | P0/P1 |
| *Beyond the brief*: intelligent companion | Live Situational Copilot (§12.1), Ask-mode assistant (§12.2), predictive maintenance + visual troubleshooting (§10.7), battery MILP (§10.9), fuel/power mode (§10.10), guardrails/evals (§13) | P0–P2 |

> **Gaps closed relative to the earlier drafts:** seatbelt compliance, instructor booking, e-learning videos, an explicit idling detector with cost, and "scheduled tasks for the day" were not first-class in the drafts. The problem statement names each of them, so each now has its own spec below.

---

## 2. Engineering principles

### 2.1 Zero-hardcoding contract

Nothing that describes the domain, the business, or the presentation lives in frontend code. The frontend is a **generic renderer**: it only knows how to draw widget *types*.

| Category | Where it lives | Frontend gets it from |
|---|---|---|
| Thresholds, limits, bands, envelopes | `config/manifests/*.yaml`, `config/rules/*.yaml` | `/api/machines/{id}/manifest`, and alerts arrive pre-classified |
| Labels, messages, units text, button text | `config/i18n/{locale}.yaml` | `/api/bootstrap` → `i18n` |
| Colours, spacing scale, typography, alert tier styles | `config/theme.yaml` | `/api/bootstrap` → `theme` (applied as CSS variables) |
| Navigation, screens, widget arrangement per device and machine class | `config/ui/layouts/*.yaml` | `/api/ui/layout?screen=&device=&machine_class=` |
| Forms (incident report, walkaround, booking, service request) | `config/ui/forms/*.yaml` (JSON Schema + UI schema) | `/api/ui/forms/{form_id}` |
| Feature flags, refresh intervals, WS URLs | `config/app.yaml` | `/api/bootstrap` |
| Units and number formatting | `config/units.yaml` | `/api/bootstrap` → `units` |
| All data (tasks, machines, operators, videos, slots…) | Database (seeded by the generator) | REST/WS |
| Demo scenarios | `config/scenarios/*.yaml` | Played by the simulator; the frontend is unaware of them |

**Allowed in frontend code:** `0`, `1`, `-1`, array indices, widget-type names in the component registry, and the API base URL (from a `VITE_API_BASE_URL` env var).
**Forbidden:** mock JSON fixtures, MSW handlers in the app bundle, inline thresholds, colour hex values, user-facing string literals.

**Enforcement (CI fails on violation):**
- ESLint `@typescript-eslint/no-magic-numbers` (ignore `[0, 1, -1]`, ignoreArrayIndexes).
- ESLint `react/jsx-no-literals` (no raw strings in JSX; every string goes through `t(key)`).
- A custom script `scripts/check_hardcoding.py`. It greps `apps/web/src` for hex colours, `rgb(`, `px` literals outside the theme adapter, and `"http`.
- Backend: `pydantic-settings` for env, and every domain constant is loaded from YAML. `ruff` rule `PLR2004` (magic value comparison) is enabled in `terrapilot/safety` and `terrapilot/analytics`.

### 2.2 Trust boundary

1. **Hard safety logic is deterministic.** Stability, proximity, geofences, seatbelt and weather-stop rules run in the rules engine. The LLM never computes or suppresses these rules.
2. **AI is advisory only.** The LLM narrates and prioritises *already computed* facts, and never issues machine commands.
3. **Warnings never wait on an LLM.** Caution and warning alerts render from i18n templates in under 100 ms. The LLM only narrates the advisory tier.
4. **Every prediction ships with a confidence band.** Every retrieval answer ships with a citation or an explicit "not in the manual".
5. **Cloud LLMs (Groq) do language, never the maths.** Thresholds, maintenance alert triggers, start-time optimisation, stability and ETC maths are deterministic or classical ML. Groq models only route, narrate, explain, extract, generate content and judge.
6. **Minimum data sent to the cloud.** Payloads to Groq are structured facts, retrieved text and operator queries. Driver-facing camera frames used for fatigue **never leave the edge**. Names and IDs are pseudonymised by the gateway (§12.3).

### 2.3 Other principles

- **Manifest-driven**: machine behaviour differences are data, not `if machine == "excavator"`.
- **Deterministic reproducibility**: the dataset generator and simulator are seeded, and `uv run tp demo` rebuilds everything from scratch.
- **Edge vs. cloud split in code**: the safety engine, simulator ingest and copilot arbiter are the "edge" modules, and they must run with the network down. Analytics, training and the fleet view are "cloud". For the hackathon both run in one `docker compose`, but they stay in separate modules with no cross-imports from edge → cloud.

---

## 3. Architecture

### 3.1 Component view

```
                        ┌───────────────────────────── CONFIG (YAML) ─────────────────────────────┐
                        │ manifests · rules · ui layouts · forms · i18n · theme · scenarios · datagen │
                        └───────────────┬──────────────────────────────────────────────┬───────────┘
                                        │                                              │
┌────────────────┐   10 Hz    ┌─────────▼─────────┐  state  ┌──────────────────┐     │
│ Telemetry       │──────────▶│  State Fusion      │───────▶│  Safety Rules     │──alerts──┐
│ Simulator /     │  Redis    │  (digital twin:    │        │  Engine (determ.) │          │
│ Replay / Real   │  streams  │  kinematics, CoG,  │        └──────────────────┘          │
│ sensor adapter  │           │  proximity, grade) │  state  ┌──────────────────┐          │
└────────────────┘           └─────────┬─────────┘───────▶│ Anomaly Detector  │─events──┤
        ▲                               │                   │ (idle/unsafe)     │          │
        │ scenario YAML                 │ state             └──────────────────┘          │
        │                               ▼                                                  ▼
┌───────┴────────┐           ┌───────────────────┐        ┌──────────────────┐   ┌────────────────┐
│ Vision adapters │─detects─▶│ Live Copilot       │◀─preds─│ ML Model Server   │   │ Event Store /  │
│ (PPE, pedestrian│           │ generators→arbiter │        │ ETC, RUL, risk,   │   │ Black box      │
│ fatigue)        │           │ →narrator→guard    │        │ fatigue, surface  │   │ (Postgres)     │
└────────────────┘           └─────────┬─────────┘        └──────────────────┘   └───────┬────────┘
                                        │ advisories                                       │
                                        ▼                                                  ▼
                              ┌────────────────────────────  FastAPI  ────────────────────────────┐
                              │ REST (bootstrap, ui, tasks, training, maint, incidents, chat)      │
                              │ WebSocket (/ws/machines/{id}: state, alerts, advisories)           │
                              └──────────────┬──────────────────────────────┬─────────────────────┘
                                             ▼                              ▼
                               Cab display (kiosk PWA)          Mobile PWA / Supervisor web
                                    same React app, different layout config

   Ask-mode Copilot (LangGraph): router → {text-to-SQL | hybrid RAG | prediction tools | twin state | VLM} → guard → answer
   Stores: Postgres+TimescaleDB (relational + time series) · Qdrant (vectors) · Redis (live bus, cache) · MinIO/local FS (images, video, black-box clips)

   LLM Gateway (backend/terrapilot/llm) ──HTTPS──▶ Groq Cloud (chat, vision, Whisper STT, Llama Guard, Prompt Guard, Batch API)
        │  per-task model routing · JSON-schema outputs · rate-limit buckets · cache · redaction · fallback → Ollama/templates
        └─ used by: live narrator, Ask mode, text-to-SQL, VLM, maintenance explainer, start-time explainer, summaries, datagen content, eval judge

   Planning & Maintenance Intelligence (backend/terrapilot/planning + maintenance)
        sensor forecasters → maintenance alerts → maintenance-window planner
        task_duration model × forecasts × machine/energy projections → start-time optimiser → recommendations
```

### 3.2 Live loop, one tick (10 Hz)

1. The simulator publishes a `RawFrame` to Redis stream `tp:raw:{machine_id}`.
2. **State Fusion** builds a `MachineState`:
   - forward kinematics → bucket tip pose;
   - grade deviation vs. the design surface;
   - stability margin;
   - proximity tracks with TTC;
   - geofence distances;
   - rolling aggregates such as idle timer, WBV dose and PERCLOS.
3. The **rules engine** evaluates the rules relevant to the manifest (hysteresis, `for_s`, escalation), then emits `Alert` open/update/clear events.
4. The **anomaly detector** updates episode state machines (idle, harsh swing…) and emits `BehaviorEvent` on episode close.
5. The **copilot arbiter** (at 2 Hz) builds candidate advisories and picks one. The narrator is async.
6. The **black box** keeps a ring buffer of the last N seconds (config). On a trigger it persists pre- and post-trigger frames.
7. The **WS gateway** pushes a `state` diff (throttled per layout config), plus `alerts` and `advisory` messages.

Latency budget (targets live in config, measured in tests): tick processing ≤ 30 ms, alert to screen ≤ 150 ms, advisory template ≤ 200 ms, LLM narration ≤ 2.5 s (advisory tier only). With Groq's `llama-3.1-8b-instant`, the working target for narration is ≤ 1.2 s p95.

### 3.3 Planning loop (event-driven + periodic)

- **Every `planning.refresh_min` (config), and on events** (new weather forecast, maintenance alert opened, SoC change > x%, task edited):
  1. Recompute sensor forecasts and time-to-threshold per machine.
  2. Open, update or close maintenance alerts.
  3. Recompute machine readiness scores.
  4. Re-run the start-time optimiser for today's and tomorrow's unstarted tasks.
  5. Push changed recommendations over WS (`recommendation` messages) and to the dashboard.
- **Nightly:** maintenance-window planning over the next N days, the 7-day fleet availability forecast, and retraining if drift is detected.

---

## 4. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Python toolchain | **uv** (already initialised), Python 3.12, ruff, mypy, pytest | Fast, reproducible, already in the repo |
| API | **FastAPI** + Uvicorn, Pydantic v2, `pydantic-settings` | Typed contracts → OpenAPI → generated TS types |
| CLI | **Typer** (`uv run tp …`) | Cross-platform (Windows-friendly, no Makefile dependency) |
| Live bus | **Redis 7** streams + pub/sub | Simple, fast, and replays well |
| DB | **PostgreSQL 16 + TimescaleDB** | One DB for relational + time series, which is also the text-to-SQL target |
| Vectors | **Qdrant** | Hybrid search (sparse + dense) with payload filters by `machine_class` |
| Object store | Local FS behind a `BlobStore` interface (MinIO optional) | Photos, videos, black-box clips |
| Expression engine for rules | **simpleeval** (sandboxed) | Rule conditions live in YAML, not code |
| ML | scikit-learn, **LightGBM** (quantile), **MAPIE** (conformal), **lifelines** (Cox PH), PyTorch (LSTM RUL, P1), **SHAP**, statsmodels | Calibrated intervals + explainability |
| Vision | **Ultralytics YOLOv8/11** (person + PPE weights), **MediaPipe Face Mesh** (EAR/head pose), OpenCV | Pretrained, with no training from scratch |
| Optimisation | **PuLP** + CBC (bundled) | MILP for charging/task allocation |
| LLM runtime (primary) | **Groq Cloud** via the official `groq` Python SDK (OpenAI-compatible endpoint), behind the `LLMProvider` interface in our LLM gateway. Per-task model map in `config/llm.yaml` (§4.1) | Very low latency (suits cab narration), strong open models, vision + Whisper + safety models on one API, free tier suits a hackathon |
| LLM runtime (fallback / offline) | **Ollama** (e.g. `qwen2.5:7b-instruct` for narration/SQL, `qwen2.5vl:7b` or `llava` for VLM) behind the same `LLMProvider` interface. Used only in the `offline` profile or when Groq is unreachable | Demo-day insurance. Templates remain the final fallback |
| Embeddings | Local **`BAAI/bge-small-en-v1.5`** via `fastembed` (or Ollama `nomic-embed-text`) | Groq does not serve embedding models. Embeddings are cheap to run locally |
| Agent orchestration | **LangGraph**, with a `ChatGroq` (`langchain-groq`) model, or our gateway wrapped as a LangChain chat model | Explicit state graph for Ask mode |
| Guardrails | **NeMo Guardrails** (topical, configured to use Groq through its OpenAI-compatible endpoint) + **Llama Guard 4** (moderation) and **Llama Prompt Guard 2** (injection), both on Groq + custom runtime rule engine | Structural enforcement |
| Forecasting | **statsmodels** (Holt / ETS), LightGBM quantile, `scipy` robust regression (Theil–Sen) | Sensor trend + time-to-threshold |
| Start-time optimisation | Grid search + constraint filter (P0), **PuLP** MILP extension for the day plan (P1), **Optuna** optional for tuning objective weights on backtests | Simple, explainable, verifiable against the generator oracle |
| Retrieval | `rank_bm25` / Qdrant sparse + dense, RRF fusion, optional cross-encoder rerank (`bge-reranker-base`) | Hybrid retrieval beats either method alone on manuals |
| SQL safety | **sqlglot** parse + allowlist | Read-only, view-scoped text-to-SQL |
| Speech | **Groq Whisper** (`whisper-large-v3-turbo`) for STT, with local **faster-whisper** as the fallback. Browser Web Speech API for TTS (voice/rate from config); a Groq TTS model can be switched on in `config/llm.yaml` if the account has one | Push-to-talk cab notes + voice queries |
| Frontend | **React 18 + TypeScript + Vite**, TanStack Query, Zustand, **react-three-fiber** (3D), **ECharts** (charts), **react-jsonschema-form** (server-driven forms), i18next (bundle loaded from API), `vite-plugin-pwa` | One codebase for cab kiosk, mobile, supervisor |
| API types | `openapi-typescript` generated from FastAPI's OpenAPI | No hand-written DTOs |
| Observability | structlog JSON logs, OpenTelemetry traces, **Langfuse** (optional) for LLM traces, MLflow for model registry | Reasoning traces shown in the UI come from here |
| Infra | Docker Compose (postgres, redis, qdrant, ollama, api, sim, worker, web) | One command to start |

### 4.1 Groq LLM usage map

Model IDs live **only** in `config/llm.yaml`. At startup the gateway calls Groq's `GET /openai/v1/models` and fails fast, with a clear message, if a configured model is unavailable. Groq retires and renames models over time, so the IDs below are the current defaults to verify, not constants.

| Task (gateway `task` key) | Where used | Default Groq model | Output mode | Fallback chain |
|---|---|---|---|---|
| `live_narration` | Live copilot advisory text (§12.1) | `llama-3.1-8b-instant` | JSON schema `{text}` | → i18n template (always) |
| `ask_router` | Ask-mode intent + tool plan (§12.2) | `llama-3.1-8b-instant` | tool calling / JSON | → `llama-3.3-70b-versatile` → keyword router |
| `ask_answer` | Grounded answer synthesis, streamed | `llama-3.3-70b-versatile` | streamed text + citation JSON | → `openai/gpt-oss-20b` → Ollama |
| `text_to_sql` | SQL over allowlisted views | `openai/gpt-oss-120b` (temperature 0) | JSON `{sql, rationale}` | → `llama-3.3-70b-versatile` → "can't answer" |
| `vlm_troubleshoot` | Photo diagnosis (§10.7.3) | `meta-llama/llama-4-scout-17b-16e-instruct` (image input) | JSON `{label, evidence, component}` × k samples | → `meta-llama/llama-4-maverick-17b-128e-instruct` → technician escalation |
| `stt` | Cab notes, voice queries | `whisper-large-v3-turbo` | text + segments | → `whisper-large-v3` → local faster-whisper |
| `moderation` | Input/output safety classification | `meta-llama/llama-guard-4-12b` | category labels | → NeMo rails only (fail closed on safety intents) |
| `injection_detect` | Prompt-injection screening of user text, cab notes, retrieved chunks | `meta-llama/llama-prompt-guard-2-86m` | score | → heuristic regex set |
| `maint_explainer` | Plain-language explanation of maintenance alerts from evidence + manual chunk (§10.13) | `llama-3.3-70b-versatile` | JSON `{summary, likely_cause, next_step}` | → template |
| `plan_explainer` | "Why this start time" narrative from optimiser factors (§10.14) | `llama-3.1-8b-instant` | JSON `{text}` | → template |
| `summaries` | Shift summary, incident report draft, work-order summary, cab-note tagging | `llama-3.1-8b-instant` | JSON | → template / keyword tagger |
| `content_gen` | Dataset build: manual expansion, quiz bank, lesson scripts, cab-note paraphrases, fault-catalogue prose (§7.7) | `openai/gpt-oss-120b` (or `llama-3.3-70b-versatile`) via **Groq Batch API** | JSON / markdown | → sync calls with rate limiting |
| `eval_judge` | LLM-as-judge for faithfulness/refusal evals (§13.2) | `qwen/qwen3-32b` (a **different model family** from the answer model, to reduce self-preference bias) | JSON score + reason | → `openai/gpt-oss-120b` |

**Where Groq is deliberately *not* used:** safety rules, stability/kinematics, maintenance alert triggering, forecasting, ETC and start-time optimisation, MILP, and on-edge fatigue vision. These are deterministic or classical ML. Groq explains their outputs but never produces them.

---

## 5. Repository layout

The root `pyproject.toml` becomes a **uv workspace**. Rename the project from `caterpillar` → `terrapilot`.

```
terrapilot/
├─ pyproject.toml                 # uv workspace root, ruff/mypy config
├─ docker-compose.yml
├─ .env.example                   # GROQ_API_KEY, DB/Redis/Qdrant URLs, profile (online|offline)
├─ config/                        # ALL domain + presentation config (single source of truth)
│  ├─ app.yaml                    # product name, feature flags, refresh rates, latency budgets
│  ├─ llm.yaml                    # providers (groq, ollama), per-task model map, limits, fallbacks, prompt versions
│  ├─ prompts/                    # versioned prompt templates per gateway task (jinja2)
│  ├─ planning.yaml               # start-time optimiser: horizon, step, objective weights, constraints
│  ├─ maintenance/                # sensor_limits.yaml, signatures.yaml, service_intervals.yaml, lifecycle.yaml, costs.yaml
│  ├─ units.yaml                  # unit systems, conversions, display precision
│  ├─ theme.yaml                  # design tokens (colour, type, spacing, alert tiers)
│  ├─ i18n/en.yaml, i18n/hi.yaml  # every user-facing string
│  ├─ manifests/                  # one per machine model: excavator_20t.yaml, wheel_loader_m.yaml, adt_30t.yaml
│  ├─ rules/                      # safety.yaml, conditions.yaml, behavior.yaml, maintenance.yaml
│  ├─ walkaround/                 # checklists per machine class
│  ├─ ui/layouts/                 # cockpit.cab.excavator.yaml, cockpit.mobile.yaml, supervisor.fleet.yaml …
│  ├─ ui/forms/                   # incident_report.yaml, service_request.yaml, booking.yaml …
│  ├─ ui/nav.yaml                 # nav per role
│  ├─ copilot/                    # advisory priorities, narrator prompt, guard rules, tool registry
│  ├─ guardrails/                 # NeMo config (colang), runtime enforcement rules
│  ├─ datagen/                    # world.yaml, climate.yaml, operators.yaml, degradation.yaml, behavior.yaml
│  ├─ scenarios/                  # demo_trench_pedestrian.yaml, demo_seatbelt.yaml, demo_idle.yaml …
│  └─ models.yaml                 # model registry: features, targets, horizons, alpha levels
├─ backend/terrapilot/
│  ├─ core/        # config loader + schema validation, units, ids, time, logging, settings
│  ├─ domain/      # Pydantic models: MachineState, Alert, Advisory, Task, …
│  ├─ db/          # SQLAlchemy models, Alembic migrations, read-only views for text-to-SQL
│  ├─ datagen/     # synthetic world generator (§7)
│  ├─ manuals/     # manual + fault-code corpus builder, chunker, indexer
│  ├─ sim/         # live simulator + scenario player + replay
│  ├─ twin/        # kinematics, stability, grade, geofence, proximity tracking
│  ├─ safety/      # rules engine, alert lifecycle, black box
│  ├─ behavior/    # anomaly/episode detectors, scorecards
│  ├─ analytics/   # ETC, pacing, fuel, scheduling, compliance rollups
│  ├─ ml/          # training pipelines, model server, calibration, SHAP
│  ├─ vision/      # PPE/pedestrian/fatigue adapters (simulated | video | camera)
│  ├─ energy/      # battery model, MILP charging scheduler
│  ├─ maintenance/ # health, RUL, risk index, fault codes, service/parts requests,
│  │               #   sensor alerting (limits/trend/forecast/signatures/peer/intervals), maintenance-window planner, repair estimates
│  ├─ planning/    # start-time optimiser, day-plan MILP, readiness score, weather windows, machine selection, availability forecast
│  ├─ llm/         # Groq gateway: provider clients, task router, rate limiter, cache, redaction, fallbacks, accounting
│  ├─ training/    # modules, videos, quizzes, bookings, adaptive assignment, simulator scoring
│  ├─ copilot/     # live (generators, arbiter, narrator) + ask (LangGraph graph, tools)
│  ├─ guard/       # runtime enforcement engine, output validators
│  ├─ speech/      # STT
│  ├─ api/         # FastAPI routers, WS gateway, auth
│  └─ cli.py       # Typer: tp gen | tp load | tp train | tp index | tp sim | tp eval | tp demo
├─ backend/tests/
├─ evals/          # eval datasets + runners (chat, sql, vlm, predictors, copilot, guardrails)
├─ apps/web/
│  ├─ src/
│  │  ├─ app/          # bootstrap loader, router built from nav config, auth
│  │  ├─ runtime/      # layout engine, widget registry, binding resolver, WS client, i18n adapter, theme adapter
│  │  ├─ widgets/      # Gauge, AlertStack, CopilotBanner, StabilityDial, ProximityRadar, Twin3D, TaskTimeline, …
│  │  ├─ forms/        # RJSF wrapper
│  │  └─ api/          # generated OpenAPI types + typed client
│  └─ eslint.config.js # hardcoding rules
├─ data/           # gitignored: generated parquet, models, media, blackbox
├─ media/          # licensed/stock training videos, fault photos (gitignored if large; manifest in config)
├─ scripts/check_hardcoding.py
└─ docs/
```

---

## 6. Configuration system

All YAML files are validated at startup against Pydantic schemas in `core/config_schema.py`. The app **refuses to start** on an invalid config, and the error message points to the file and key. Config is hot-reloadable in dev (`watchfiles`).

References between files use `ref:` keys, and rules can reference manifest values through `manifest.<path>`. That way a threshold has exactly one source.

### 6.1 Machine manifest (example: `config/manifests/excavator_20t.yaml`)

```yaml
id: excavator_20t
class: excavator
name_key: machine.model.excavator_20t
powertrain: diesel            # diesel | electric | hybrid
specs:
  operating_mass_kg: 21500
  counterweight_kg: 3900
  counterweight_offset_m: -2.6
  upper_mass_kg: 9800
  upper_cog_offset_m: -0.4
  track_gauge_m: 2.39
  track_length_m: 3.65
  boom: {length_m: 5.7, mass_kg: 1650, pivot: [0.15, 1.9]}
  stick: {length_m: 2.9, mass_kg: 750}
  bucket: {length_m: 1.45, mass_kg: 820, capacity_m3: 1.2}
  max_dig_depth_m: 6.7
  idle_fuel_lph: 3.2
  work_fuel_lph: {eco: 14.0, standard: 17.5, high: 20.5}
sensors:
  - {id: hydraulic.pump_pressure, unit: bar, range: [0, 380], hz: 10,
     bands: {normal: [0, 320], caution: [320, 345], warning: [345, 380]}}
  - {id: hydraulic.oil_temp, unit: degC, range: [-20, 120], hz: 1,
     bands: {normal: [-20, 85], caution: [85, 95], warning: [95, 120]}}
  - {id: seat.occupied, type: bool}
  - {id: seat.belt_fastened, type: bool}
  - {id: imu.pitch_deg, unit: deg}
  - {id: imu.roll_deg, unit: deg}
  # … boom/stick/bucket/swing angles, engine rpm, fuel, DPF soot, GPS, cameras, radar, P2P
envelopes:
  stability_margin: {advisory: 1.8, caution: 1.5, warning: 1.25}
  side_slope_deg: {caution: 10, warning: 15}
  travel_speed_boom_raised_kph: {caution: 2.0}
  swing_rate_near_person_deg_s: {caution: 20}
proximity:
  zones_m: {advisory: 15, caution: 8, warning: 4}
  ttc_s: {caution: 6, warning: 3}
  swing_radius_m: ref:specs.derived.tail_swing_radius
motion:
  moving_threshold_kph: 0.5
  hydraulic_active_pressure_bar: 40
seatbelt: {grace_s: 5, escalate_after_s: 20}
idle: {min_episode_s: 180, excessive_s: 600, max_idle_ratio: 0.25}
components: [engine, hydraulic_pump, swing_drive, undercarriage, get, dpf, final_drive, cooling, electrical]
maintenance_sensors:          # drives §10.13; limits and signatures are referenced, not repeated
  - {id: engine.coolant_temp,      component: cooling,        limits_ref: maintenance/sensor_limits.yaml#coolant_temp, forecast: true}
  - {id: engine.oil_pressure,      component: engine,         limits_ref: …#oil_pressure_vs_rpm, normalise_by: engine.rpm}
  - {id: hydraulic.oil_temp,       component: hydraulic_pump, limits_ref: …#hyd_oil_temp, forecast: true}
  - {id: hydraulic.pressure_ripple,component: hydraulic_pump, limits_ref: …#pump_ripple, forecast: true}
  - {id: hydraulic.filter_dp,      component: hydraulic_pump, limits_ref: …#filter_dp, forecast: true}
  - {id: engine.air_filter_restriction, component: engine,    limits_ref: …#air_restriction, forecast: true}
  - {id: dpf.soot_load_pct,        component: dpf,            limits_ref: …#dpf_soot, forecast: true}
  - {id: fuel.water_in_fuel,       component: engine,         limits_ref: …#wif}
  - {id: electrical.system_voltage,component: electrical,     limits_ref: …#sys_voltage}
  - {id: swing.vibration_rms,      component: swing_drive,    limits_ref: …#swing_vib, forecast: true}
  - {id: undercarriage.track_tension_mm, component: undercarriage, limits_ref: …#track_tension}
service_intervals_ref: maintenance/service_intervals.yaml#excavator_20t
energy:
  refuel_rate_lpm: 60            # for refuel-time estimate
  tank_l: 400
  # electric variants add: battery_kwh, charge_power_kw_by_station, soc_floor_ref: app.energy.soc_floor
training:
  required_modules: [safety_basics, excavator_controls, trenching_101]
  cert_validity_days: 365
walkaround: ref:walkaround/excavator.yaml
controls: ref:controls/excavator_iso.yaml     # used by simulator & in-cab hints
knowledge_scope: [excavator, common]          # RAG payload filter
ui:
  layouts: {cab: ui/layouts/cockpit.cab.excavator.yaml, mobile: ui/layouts/cockpit.mobile.yaml}
```

### 6.2 Rule (example: `config/rules/safety.yaml`)

```yaml
- id: SEATBELT_UNFASTENED_ACTIVE
  applies_to: [excavator, wheel_loader, adt]
  inputs: [seat.occupied, seat.belt_fastened, motion.ground_speed_kph, hydraulic.pump_pressure]
  when: >
    seat.occupied and not seat.belt_fastened and
    (motion.ground_speed_kph > manifest.motion.moving_threshold_kph or
     hydraulic.pump_pressure > manifest.motion.hydraulic_active_pressure_bar)
  for_s: manifest.seatbelt.grace_s
  clear_after_s: 2
  severity: caution
  escalate: {to: warning, after_s: manifest.seatbelt.escalate_after_s}
  message_key: alert.seatbelt.unfastened          # i18n, with {placeholders}
  actions: [log_event, compliance_tick, notify_supervisor_on_escalate, blackbox_mark]
  copilot_priority: 95
```

Conditions go through `simpleeval`, restricted to a whitelist of names and operators. Rule tests live next to the rules as `config/rules/tests/*.yaml` (given frames → expected alerts) and run in CI.

### 6.3 UI layout (example: `config/ui/layouts/cockpit.cab.excavator.yaml`)

```yaml
screen: cockpit
device: cab
grid: {columns: 12, rows: 8, gap_token: space.2}
modes:                      # workload-adaptive declutter
  normal:    {hide: []}
  precision: {hide: [fuel_card, task_card], trigger: "state.task.phase in ['finish_grade']"}
widgets:
  - {id: copilot, type: CopilotBanner, area: [1,1,12,1], bind: advisory}
  - {id: alerts, type: AlertStack, area: [9,2,4,4], bind: alerts, max_visible_ref: app.ui.alert_stack_max}
  - {id: twin, type: Twin3D, area: [1,2,8,5], bind: state, props: {camera: chase, show: [design_surface, geofences, persons, envelope]}}
  - {id: stability, type: StabilityDial, area: [9,6,2,2], bind: state.stability.margin, bands_ref: manifest.envelopes.stability_margin}
  - {id: hyd_p, type: Gauge, area: [11,6,2,2], bind: state.hydraulic.pump_pressure, sensor_ref: hydraulic.pump_pressure}
  - {id: grade, type: GradeProfile, area: [1,7,4,2], bind: state.grade}
  - {id: radar, type: ProximityRadar, area: [5,7,2,2], bind: state.proximity, zones_ref: manifest.proximity.zones_m}
  - {id: task_card, type: TaskProgress, area: [7,7,3,2], bind: state.task}
  - {id: fuel_card, type: EnergyCard, area: [10,8,3,1], bind: state.energy}
```

`bind` paths resolve against the live state or REST resources. `*_ref` resolves against the manifest or app config. Widgets never contain numbers.

### 6.4 Datagen and scenario config

See §7.2 and §7.6.

### 6.5 LLM config (`config/llm.yaml`, abridged)

```yaml
profile_env: TP_PROFILE            # online | offline
providers:
  groq:   {sdk: groq, base_url: https://api.groq.com/openai/v1, api_key_env: GROQ_API_KEY, verify_models_on_start: true}
  ollama: {base_url: http://ollama:11434, profiles: [offline]}
  local:  {kinds: [embeddings, stt]}
limits:                              # set to your Groq account tier; also adapts from x-ratelimit-* response headers
  llama-3.1-8b-instant:    {rpm: 30, tpm: 6000}
  llama-3.3-70b-versatile: {rpm: 30, tpm: 12000}
tasks:
  live_narration:
    provider: groq
    model: llama-3.1-8b-instant
    temperature: 0.2
    max_tokens: 60
    timeout_ms: 1200
    response_format: {type: json_schema, schema_ref: schemas/narration.json}
    prompt: prompts/live_narration.v3.j2
    cache: {ttl_s: 30, key: [category, facts_rounded, locale]}
    fallback: [template]
  ask_answer:
    {provider: groq, model: llama-3.3-70b-versatile, stream: true, timeout_ms: 8000,
     fallback: ["groq:openai/gpt-oss-20b", "ollama:qwen2.5:7b-instruct"]}
  text_to_sql:      {provider: groq, model: openai/gpt-oss-120b, temperature: 0, fallback: ["groq:llama-3.3-70b-versatile"]}
  vlm_troubleshoot: {provider: groq, model: meta-llama/llama-4-scout-17b-16e-instruct, samples: 3, max_image_px: 1280,
                     fallback: ["groq:meta-llama/llama-4-maverick-17b-128e-instruct", escalate]}
  stt:              {provider: groq, model: whisper-large-v3-turbo, fallback: ["local:faster-whisper-small"]}
  moderation:       {provider: groq, model: meta-llama/llama-guard-4-12b, fail_mode: closed}
  injection_detect: {provider: groq, model: meta-llama/llama-prompt-guard-2-86m, threshold: 0.5}
  maint_explainer:  {provider: groq, model: llama-3.3-70b-versatile, fallback: [template]}
  plan_explainer:   {provider: groq, model: llama-3.1-8b-instant, fallback: [template]}
  summaries:        {provider: groq, model: llama-3.1-8b-instant, fallback: [template]}
  content_gen:      {provider: groq, model: openai/gpt-oss-120b, batch_api: true}
  eval_judge:       {provider: groq, model: qwen/qwen3-32b}
  embeddings:       {provider: local, model: BAAI/bge-small-en-v1.5}
redaction: {pseudonymise: [operator_name, badge_id, phone], never_send: [driver_camera_frames]}
```

### 6.6 Maintenance and planning config (abridged)

`config/maintenance/sensor_limits.yaml`:

```yaml
coolant_temp:
  unit: degC
  bands: {normal: [null, 98], monitor: [98, 103], service_soon: [103, 108], stop: [108, null]}
  debounce_s: 30
  rate_limit: {per_min: 1.5, window_min: 5, tier: service_soon}          # rising too fast
  forecast: {model: holt, horizon_h: 72, lead_time_ref: parts_lead_time}  # time-to-threshold
  normalise: {by: [ambient_temp, engine_load_pct]}                        # residual used for peer/drift
oil_pressure_vs_rpm:
  unit: kPa
  curve: {rpm: [800, 1200, 1800, 2000], min_kpa: [100, 180, 260, 280]}  # limit is a function of rpm
  bands_on_margin: {monitor: 0.15, service_soon: 0.05, stop: 0.0}
```

`config/maintenance/signatures.yaml`:

```yaml
- id: SIG_HYD_PUMP_WEAR
  component: hydraulic_pump
  all_of: ["trend(hydraulic.oil_temp_resid) > 0.3/h", "trend(hydraulic.pressure_ripple) > 0.05/h", "hydraulic.flow_eff < 0.9"]
  window_h: 24
  tier: service_soon
  fault_catalogue_ref: HYD-PUMP-01
- id: SIG_RADIATOR_CLOGGING
  component: cooling
  all_of: ["engine.coolant_temp_resid > 4", "engine.fan_speed_pct > 90", "site.pm10 > 150"]
  tier: service_soon
  fault_catalogue_ref: COOL-RAD-02
```

`config/planning.yaml`:

```yaml
start_time:
  horizon_h: 36
  step_min: 15
  quantile_for_deadline: p90
  objective: {w_p50: 1.0, w_spread: 0.3, w_stop_risk: 0.8, w_safety_risk: 1.5, w_wait: 0.1}
  min_saving_to_recommend_min: 10         # don't nag for trivial gains
  usual_duration: {method: knn_similar_tasks, k: 25, lookback_days: 120}
  preconditions: {charge_target_soc_margin: 0.05, refuel_if_below_pct: 25}
readiness:
  weights: {health: 0.35, open_maint_alerts: 0.25, energy: 0.2, walkaround: 0.1, cert: 0.1}
  bands: {go: 80, caution: 60}
maintenance_window:
  horizon_days: 7
  prefer: [predicted_idle, weather_stop, low_priority_tasks]
  must_be_before: failure_eta_p10
  bundle_within_h: 50                     # opportunistic bundling of due items
```

---

## 7. Synthetic dataset

The problem statement says sensor data "will be arranged" and any data can be assumed. We still build **our own generator**. This gives us:

- data volume big enough to train on;
- hidden ground truth to evaluate against;
- scripted live scenarios for the demo;
- the ability to regenerate everything with one command.

The ingestion layer uses a `SensorAdapter` interface, so organiser-provided data plugs in with a new adapter and no other code changes (§7.8).

### 7.1 Design principles

1. **Causal, not random.** Outcomes come from hidden causal models with coefficients in `config/datagen/*.yaml`. For example, cycle time depends on soil, moisture, temperature, operator skill and bucket size. Models can therefore learn real signal, and we can check that they recover the known effects.
2. **Ground truth is kept separate.** `truth_*` tables store latent variables (true component health, true operator fatigue, injected anomaly labels). Models never train on them, and evals score against them.
3. **Relative time.** History is anchored to the run date (`now - history_days`), so the demo data always looks current. No dates are hardcoded.
4. **Seeded.** `tp gen --seed 42` is deterministic.
5. **Scale is configurable.** For example: 3 sites, 14 machines, 40 operators, 180 days of history.

### 7.2 World config (`config/datagen/world.yaml`, abridged)

```yaml
seed: 42
history_days: 180
shift: {start_local: "07:00", length_h: 10, break_minutes: [60, 15, 15]}
sites:
  - {id: site_north, type: highway_cut, climate: hot_arid, altitude_m: 450, soil_mix: {clay: .2, sand: .5, rock: .3}}
  - {id: site_quarry, type: quarry, climate: temperate_monsoon, altitude_m: 900, soil_mix: {rock: .7, gravel: .3}}
  - {id: site_metro, type: urban_excavation, climate: humid_subtropical, altitude_m: 20, soil_mix: {clay: .6, fill: .4},
     buried_utilities: 18, overhead_lines: 3}
fleet:
  - {manifest: excavator_20t, count: 6}
  - {manifest: wheel_loader_m, count: 3}
  - {manifest: adt_30t, count: 4}
  - {manifest: excavator_20t_electric, count: 1}
operators: {count: 40, experience_years: {dist: lognormal, mu: 1.6, sigma: 0.6}}
instructors: {count: 4}
```

### 7.3 Entities generated

| Group | Tables / files | Key generation logic |
|---|---|---|
| **Org** | sites, zones, geofences (polygons + 3D depth for utilities), design_surfaces (grid DEM per site), charging_stations | Procedural polygons; design surface = benches/trenches/slopes; utilities as 3D polylines with depth ± uncertainty |
| **Fleet** | machines, machine_manifest_ref, qr_codes, hour meters | From the fleet config; QR payload = signed machine id |
| **People** | users, operators (skill, experience, habits), instructors, supervisors, technicians | Latent traits: `skill` ∈ [0,1], `idle_propensity`, `belt_compliance_p`, `aggression` (harsh swings), `fatigue_susceptibility` |
| **Weather** | weather_hourly (temp, humidity, rain_mm, wind_ms, gust_ms, visibility_m, lightning_km, dust_pm10, heat_index) | Climate-zone seasonal curve + AR(1) noise + stochastic storms/dust events |
| **Ground** | ground_conditions_daily per zone (soil type, moisture, density, bearing capacity, slope FoS) | Moisture follows rain with decay; density varies by soil type; slope FoS depends on moisture |
| **Planning** | projects, tasks (type, quantity m³/loads/m, zone, design ref, planned start/end, priority, dependencies), shift_assignments | Task generator per site type; daily schedule per operator/machine; some tasks run late |
| **Execution** | cycles (per bucket cycle: dig/swing/dump/return durations, payload, fill factor, fuel, soil), task_progress, telemetry_1min (aggregates), telemetry_raw (1–10 Hz, only for the last 3 days + scenarios) | Cycle-time causal model (§7.4); progress = Σ cycle payloads |
| **Behaviour** | behavior_events (idle, harsh swing, travel boom-raised, belt off, over-slope, relief-stall, overload, cavitation, high-rpm idle), truth_behavior_labels | Driven by operator traits × context; labels kept for eval |
| **Safety** | alerts_history, proximity_encounters, near_misses, incidents (+ severity, root cause), blackbox_clips (raw frame slices), ppe_observations, seatbelt_compliance_daily | Incident probability = f(unsafe behaviour rate, visibility, fatigue, ground risk) — rare events |
| **Operator state** | fatigue_signals (PERCLOS, microsleeps, head-nods per 5 min), wbv_exposure (A(8) per shift) | Fatigue rises with hours awake, night shifts, heat; WBV from terrain roughness × speed × seat suspension |
| **Maintenance** | component_health_truth (latent), sensor trends (pressure ripple, temps, vibration RMS), fault_events (codes), maintenance_records, fluid_samples (Fe/Cu/Si/Na ppm, ISO cleanliness, viscosity, soot %), parts_catalog, service_requests, work_orders | Weibull degradation, sped up by climate (§7.5); faults fire when health crosses code thresholds; maintenance resets health; fluid samples every N hours are correlated with the latent wear |
| **Energy** | fuel_log, battery_log (SoC, kWh, temp, cycles), charging_sessions, idle_windows | Electric machine SoC from the load-state consumption model; idle windows emerge from truck-waiting times |
| **Training** | modules, lessons (video/quiz/drill/sim), video_assets (URL + duration + chapters), quiz_questions, attempts, certifications, instructor_slots, bookings, sim_sessions (scores), assignments (with reason: anomaly/maintenance/manual) | Historical completions correlate with skill; some certs expiring soon (so the demo shows gating) |
| **Knowledge** | manuals (markdown per machine class, sectioned), fault_code_catalog, procedures, service_bulletins | §7.7 |
| **Voice/notes** | cab_notes (text + audio ref) | Templated notes + a few LLM-paraphrased ones (Groq `content_gen`) |
| **Maintenance sensors** (rev 2) | sensor_1min for every `maintenance_sensors` channel (coolant temp, oil pressure vs rpm, hyd temp, pressure ripple, filter ΔP, air restriction, DPF soot, water-in-fuel, voltage, vibration, track tension, tyre pressure/temp for loaders/ADTs, brake/transmission temps, battery cell ΔV/temp for electric) | Each channel = physics baseline (ambient + load + rpm) + a component-health–driven drift term + noise. Injected **fault modes** (radiator clogging in dusty weeks, slow tyre leak, filter plugging, pump wear, cell imbalance, alternator failure) with onset time, growth curve and truth label |
| **Maintenance ops** (rev 2) | technician_slots, maintenance_durations/costs (in maintenance_records), parts lead times, service interval counters | Repair duration = f(component, work type, technician experience, part availability, site remoteness) + noise. Costs from `config/maintenance/costs.yaml` × parts |
| **Start-time natural variation** (rev 2) | tasks.actual_start varies around planned_start; start-time context snapshot (SoC/fuel, health, ground moisture, forecast) stored per task | Supervisors in the sim sometimes start early or late, some after rain or on low charge. This gives the duration model the variation it needs to learn start-time effects |
| **Forecasts** (rev 2) | weather_forecast (issued_at, valid_at, value, spread), ground_moisture_forecast, truck_availability_forecast | Forecast = truth + growing error with lead time (error spread from config), so the optimiser sees realistic forecast uncertainty |

### 7.4 Core causal models (coefficients all in `config/datagen/*.yaml`)

**Cycle time (excavator):**

```
t_cycle = base_class
        × soil_factor[soil] × (1 + k_moist · moisture)
        × (1 + k_temp · max(0, T − T_comfort))
        × (1 + k_rain · rain_mm_h) × (1 + k_vis · 1[visibility < v_thresh])
        × (1 − k_skill · skill) × (1 + k_fatigue · fatigue)
        × swing_factor(swing_angle) × depth_factor(dig_depth)
        × lognormal(0, σ)
fill_factor = f(soil, skill, bucket_type) · N(1, σ_fill)
task_duration = Σ cycles until quantity reached + waits(truck availability) + breaks + weather stoppages
```

Wheel loader: load-and-carry, so distance matters. ADT: haul cycles depending on haul distance, grade and road condition.
This gives the **task time model** real, recoverable dependencies on past data and environmental conditions.

**Idle:** at each wait (truck not present, break, radio call), the operator shuts down with probability `1 − idle_propensity`. Otherwise the idle episode lasts for the wait duration + the operator's tail. Fuel = `manifest.idle_fuel_lph` × duration.

**Unsafe patterns:** per-cycle hazard rates, e.g. `P(harsh_swing) = σ(a + b·aggression + c·time_pressure)`.

### 7.5 Degradation model

For each component, the latent health `h ∈ [0,1]` declines with a Weibull-shaped wear rate scaled by stress:

```
dh/dt = −λ_c · (β/η)(t/η)^(β−1) · AF
AF (acceleration factor) = exp(α_T·(T−T_ref)) · (1 + α_dust·PM10_norm) · (1 + α_hum·RH_norm)
                           · (1 + α_alt·alt_norm) · duty_severity · (1 + α_abuse·abuse_rate)
```

Observable symptoms are functions of `h` plus noise: pressure ripple ↑, oil temp ↑, vibration RMS ↑, and fluid-sample wear metals ↑. Fault codes fire at configured `h` thresholds, and failure happens at `h ≤ h_fail`. Maintenance (scheduled or triggered) resets `h` to a configured value. The result is survival data with covariates for the Cox model, plus time series for the LSTM RUL.

**Sensor mapping for maintenance alerts (rev 2).** Each maintenance sensor is generated as:

```
s(t) = baseline(ambient, load, rpm; θ_sensor) + g_c(1 − h_c(t)) + fault_mode_k(t − onset_k) + ε(t)
```

- `g_c` maps component wear to the symptom.
- `fault_mode_k` is an injected, labelled abrupt or accelerating fault (step, ramp, exponential).

Truth tables record `onset`, `first_detectable` (the time when the symptom exceeds noise by the configured SNR) and `failure_time`. This lets evals measure **detection lead time** and false alarms.

### 7.4b Oracle for start-time evaluation (rev 2)

The generator exposes `simulate_task(task, start_ts, world_state, seed)`. It runs the same causal cycle model under the *true* weather, ground and machine state for any hypothetical start time. The start-time optimiser (§10.14) is evaluated against this oracle with **counterfactual regret**: the true duration at the recommended start minus the best true duration over all feasible starts. We can only measure this because we own the generator.

### 7.6 Scenarios (live demo + tests)

`config/scenarios/demo_trench_pedestrian.yaml`:

```yaml
id: demo_trench_pedestrian
machine: EX-03
operator: op_017
site: site_metro
task: T-2031                   # trench to design grade
duration_s: 420
tick_hz: 10
baseline: {generator: excavator_trenching, skill: 0.6}
timeline:
  - {t: 5,   set: {seat.belt_fastened: false}}          # seatbelt demo
  - {t: 22,  set: {seat.belt_fastened: true}}
  - {t: 60,  inject: over_dig, params: {depth_cm: 4, duration_s: 15}}
  - {t: 110, spawn_person: {from: [18, -6], velocity_ms: [-1.1, 0.6], ppe: {helmet: true, vest: false}}}
  - {t: 150, inject: approach_buried_utility, params: {utility_id: U-07}}
  - {t: 200, weather: {wind_ms: 16, gust_ms: 21}}
  - {t: 240, inject: cavitation, params: {severity: 0.7}}
  - {t: 300, inject: idle, params: {duration_s: 90}}    # truck late → idle
  - {t: 380, inject: side_slope, params: {roll_deg: 12}}
```

Additional rev-2 scenarios:

- `demo_maintenance_alert.yaml`: during a dusty afternoon, coolant temp residual climbs. The system raises a trend alert, then a time-to-threshold forecast ("service_soon in ~9 h"), then the radiator-clogging signature. A maintenance window is suggested, and a work order is drafted.
- `demo_start_time.yaml`: the morning after heavy rain, the electric excavator is at 38% SoC and has a hydraulic filter ΔP alert, and a trenching task is due by 16:00. The recommender advises "charge to 85% during the 25-minute toolbox talk, start at 09:45 when the clay has drained, and finish ~22 min faster than usual". Starting now would cost an extra charge stop mid-task.

Scenarios drive the simulator (`tp sim --scenario …`) and the integration tests (expected alerts/advisories are asserted). Supervisors can also trigger a scenario from the admin panel during the demo.

### 7.7 Knowledge corpus

- **Manuals**: for each machine class we write an outline in `config/datagen/manual_outline.yaml`: safety, pre-start walkaround, controls, operating techniques, maintenance intervals, fluids and capacities, troubleshooting per fault code, sensor limits and alert responses (rev 2), and transport. A Groq model (`content_gen`, run through the Batch API) expands each section from the outline and the manifest values (capacities and intervals are pulled from the manifest, so the numbers stay consistent). We then **human-review** the result and commit it as markdown with frontmatter (`machine_class`, `section`, `procedure_id`, `page`). About 40–60 pages per class.
- **Fault-code catalogue** (`fault_codes.csv`, structured, not prose): `code, component, severity, title_key, description, probable_causes[], checks[], safe_to_continue, manual_ref, part_numbers[]`.
- **Parts catalogue**: part number, component, description, price, lead time, dealer stock.
- **Training content**: lesson scripts, quiz banks (LLM-drafted from manual sections, human-reviewed, each question with `source_chunk_id`), and videos. Videos are either stock/CC-licensed clips listed in `config/media.yaml` with their licence, or narrated slide videos generated from the lesson scripts (TTS + slides via ffmpeg).
- **Photo set for VLM**: 60–120 images (leaks, worn/missing teeth, damaged hoses, track tension, warning-light clusters, and clean "normal" controls). These are CC-licensed or staged photos, labelled in `evals/vlm/labels.csv`.

### 7.8 Pipeline commands

```
uv run tp gen      --config config/datagen --seed 42 --out data/generated   # parquet
uv run tp validate-data                                                     # distribution + learnability checks
uv run tp load     --from data/generated                                    # → Postgres/Timescale
uv run tp index    --manuals data/knowledge                                 # chunk → embed → Qdrant
uv run tp train    --all                                                    # → data/models + MLflow
uv run tp content  --task manuals|quizzes|notes                              # Groq Batch API content generation → review queue
uv run tp plan     --site site_metro --date today                            # run start-time optimiser + maintenance-window planner
uv run tp llm-check                                                          # verify GROQ_API_KEY, configured model IDs, rate limits
uv run tp demo                                                              # all of the above + start services + scenario
```

**Learnability gate** (`tp validate-data`): for each target, a trivial model must beat the naive baseline by a configured margin. Coefficients the model recovers (e.g. rain effect on ETC) must have the correct sign vs. the configured truth. This catches generator bugs before the demo.

**Adapter for organiser data:** `SensorAdapter` implementations are `SimulatorAdapter`, `ParquetReplayAdapter`, and `ExternalFeedAdapter`. The last one maps columns via `config/adapters/<source>.yaml`, so real provided data plugs in without code changes.

---

## 8. Database schema (Postgres + Timescale)

Core tables (abridged, all with `id`, `created_at`):

```
sites(id, name, climate_zone, altitude_m, tz, geom)
zones(id, site_id, kind[dig|haul|dump|exclusion|pedestrian], polygon, design_surface_id)
geofences(id, site_id, kind[utility_buried|overhead_line|exclusion], geom3d, clearance_m, depth_m, depth_uncertainty_m, source)
machines(id, site_id, manifest_id, serial, qr_token, hour_meter, powertrain, status)
users(id, name, role[operator|supervisor|instructor|technician|admin], locale, pin_hash)
operator_profiles(user_id, experience_years, home_site_id)
certifications(id, user_id, module_id, machine_class, issued_at, expires_at, status)
projects(id, site_id, name)
tasks(id, project_id, zone_id, machine_class, type, quantity, unit, design_ref, planned_start, planned_end,
      priority, depends_on[], status, assigned_operator_id, assigned_machine_id)
shift_assignments(id, date, operator_id, machine_id, site_id, shift_start, shift_end)
cycles(hypertable: ts, machine_id, operator_id, task_id, phase_durations jsonb, payload_t, fill_factor, fuel_l, soil, depth_m)
telemetry_1min(hypertable: ts, machine_id, <aggregated signals>)
telemetry_raw(hypertable: ts, machine_id, frame jsonb)          -- retention policy from config
weather_hourly(hypertable: ts, site_id, temp_c, rh, rain_mm, wind_ms, gust_ms, visibility_m, lightning_km, pm10, heat_index)
ground_conditions(date, zone_id, soil, moisture, density, bearing_kpa, slope_fos)
alerts(id, machine_id, rule_id, severity, opened_at, escalated_at, cleared_at, acked_by, context jsonb)
behavior_events(id, machine_id, operator_id, kind, start_ts, end_ts, metrics jsonb, cost jsonb, detector[rule|stat|ml], score)
seatbelt_compliance(date, operator_id, machine_id, active_s, unbelted_active_s, events)
incidents(id, machine_id, operator_id, kind[incident|near_miss|hazard], severity, source[auto|manual],
          occurred_at, location, description, root_cause, blackbox_clip_id, status, reviewer_id)
blackbox_clips(id, machine_id, trigger_rule_id, t0, pre_s, post_s, frames_uri, media_uri)
fatigue_samples(hypertable: ts, operator_id, perclos, microsleeps, head_nods, score)
wbv_exposure(date, operator_id, a8_ms2, vdv)
components(id, machine_id, kind, installed_at, hours)
fault_events(id, machine_id, code, ts, cleared_ts, occurrences)
fluid_samples(id, machine_id, compartment, ts, fe_ppm, cu_ppm, si_ppm, na_ppm, iso_4406, viscosity_cst, soot_pct, lab_rating)
maintenance_records(id, machine_id, component_id, ts, kind[scheduled|corrective], work_done, parts[])
parts(part_no, component_kind, description, price, lead_time_days, stock)
service_requests(id, machine_id, requested_by, kind[part|service], fault_code, part_nos[], diagnosis_ref, status, eta)
predictions(id, model, entity, ts, horizon, p10, p50, p90, calibrated, explain jsonb)   -- audit of what we showed
battery_log(hypertable: ts, machine_id, soc, kwh, power_kw, temp_c)
charging_sessions(id, machine_id, station_id, start, end, kwh, planned_by_schedule_id)
charge_schedules(id, created_at, horizon, solver_status, objective, plan jsonb)
modules(id, title_key, machine_class, kind, prerequisites[], est_minutes)
lessons(id, module_id, kind[video|quiz|drill|sim|reading], asset_id, order)
video_assets(id, uri, duration_s, chapters jsonb, licence)
quiz_questions(id, module_id, stem, options jsonb, answer, source_chunk_id)
attempts(id, user_id, lesson_id, score, started_at, completed_at, detail jsonb)
assignments(id, user_id, module_id, reason_kind[anomaly|maintenance|cert_expiry|manual], reason_ref, due_at, status)
instructor_slots(id, instructor_id, start, end, site_id, mode[onsite|remote|simulator], capacity)
bookings(id, slot_id, user_id, module_id, status, notes)
sim_sessions(id, user_id, drill_id, score, metrics jsonb, ts)
cab_notes(id, operator_id, machine_id, ts, text, audio_uri, tags[])
chat_sessions / chat_messages(id, session_id, role, content, tool_calls jsonb, citations jsonb, confidence, guard_actions jsonb)
guard_events(id, ts, layer, rule_id, input_hash, action, detail)
truth_* (component_health_truth, truth_behavior_labels, truth_operator_state,
         truth_fault_modes(onset, first_detectable, failure_time)) -- eval only, not exposed to text-to-SQL

-- rev 2: maintenance alerting
sensor_1min(hypertable: ts, machine_id, sensor_id, value, resid)              -- resid = value − normalised baseline
sensor_forecasts(id, machine_id, sensor_id, issued_at, horizon_h, threshold_tier, eta_p10, eta_p50, eta_p90, p_cross_h, model)
maintenance_alerts(id, machine_id, component, sensor_ids[], kind[limit|rate|forecast|signature|peer|interval|fluid|fault_code],
                   tier[monitor|service_soon|stop], opened_at, updated_at, state[open|acknowledged|scheduled|in_service|resolved|false_alarm],
                   evidence jsonb, eta jsonb, recommended_action_ref, safe_to_continue, parts[], est_repair jsonb, window_id,
                   work_order_id, explanation jsonb, feedback)
service_counters(machine_id, item, last_done_hours, due_hours, severity_factor, due_eta)
technician_slots(id, technician_id, site_id, start, end, skills[])
maintenance_windows(id, machine_id, alert_ids[], start, end, est_duration jsonb, est_cost jsonb, production_impact jsonb, status, rationale jsonb)

-- rev 2: planning & estimation
weather_forecast(issued_at, site_id, valid_at, var, value, spread)
start_recommendations(id, task_id, computed_at, recommended_start, alt_starts jsonb, duration jsonb, usual_duration jsonb,
                      saving_vs_now_min, saving_vs_usual_min, preconditions jsonb, factors jsonb, constraints jsonb,
                      feasible, explanation jsonb, accepted_by, accepted_at, outcome_duration)
task_start_context(task_id, soc, fuel_pct, health_index, open_alerts, ground_moisture, forecast_ref)
energy_estimates(id, task_id, machine_id, kwh_or_l_p10, p50, p90, can_finish_on_current bool, recharge_min, refuel_min)
readiness_scores(ts, machine_id, score, components jsonb, band)
availability_forecast(date, machine_id, p_available, planned_downtime_h, risk_downtime_h)
task_cost_estimates(task_id, fuel_cost, wear_cost, maintenance_accrual, cost_per_unit)

-- rev 2: LLM accounting
llm_calls(id, ts, task, provider, model, prompt_version, input_tokens, output_tokens, latency_ms, status[ok|fallback|error|cached],
          fallback_used, guard_flags jsonb, trace_id)
```

**Text-to-SQL exposure:** only through the `tp_ro` role and curated views (`v_cycles`, `v_tasks_today`, `v_idle_summary`, `v_alerts`, `v_fuel`, `v_fault_history`, and in rev 2 `v_maintenance_alerts`, `v_service_due`, `v_start_recommendations`, `v_energy_estimates`, …). Column comments on these views are fed to the SQL prompt.

---

## 9. Backend services and API

### 9.1 Processes (docker compose services)

| Service | Responsibility |
|---|---|
| `api` | FastAPI REST + WS gateway, auth |
| `edge` | State fusion + rules engine + black box + behaviour detectors + live copilot (one process per site; subscribes to Redis) |
| `sim` | Simulator / scenario player / replay adapters |
| `worker` | Background jobs (RQ/Arq): nightly rollups, retraining, MILP solves, report generation, STT, **planning loop (§3.3)**, **sensor forecasting + maintenance alerting**, Groq batch content jobs |
| `ml` | Model server (in-process in `api` for the hackathon; separate process is optional) |
| `postgres`, `redis`, `qdrant`, `ollama`, `web` | Infrastructure |

### 9.2 REST endpoints (grouped)

```
Auth & bootstrap
  POST /api/auth/login                     {badge_id|username, pin} → JWT
  POST /api/auth/machine-select            {qr_token|machine_id} → session + manifest + gating result
  GET  /api/bootstrap                      → {app, features, theme, i18n, units, nav(role), ws, refresh}
  GET  /api/ui/layout?screen&device&machine_class
  GET  /api/ui/forms/{form_id}             → {schema, ui_schema}

Machines & live
  GET  /api/machines, /api/machines/{id}, /api/machines/{id}/manifest
  GET  /api/machines/{id}/state            (snapshot)
  WS   /ws/machines/{id}                   msgs: state_diff | alert | advisory | task_update | notice
  WS   /ws/fleet/{site_id}                 supervisor feed

Tasks & day
  GET  /api/me/shift                       → today's assignment, tasks, pacing
  GET  /api/tasks?date&operator&status ;  POST/PATCH /api/tasks (supervisor)
  GET  /api/tasks/{id}/estimate            → p10/p50/p90, factors (SHAP), live ETC
  POST /api/tasks/backschedule             {task_ids, deadline} → latest safe start, feasibility, risk
  GET/POST /api/walkaround/{machine_id}    checklist (from manifest) + photos
  POST /api/notes                          (audio/text) → STT, tags

Safety
  GET  /api/alerts?machine&state ;  POST /api/alerts/{id}/ack
  GET  /api/compliance/seatbelt?scope&period ;  GET /api/compliance/ppe
  GET/POST /api/incidents ;  GET /api/incidents/{id}/playback  (frames + events timeline)
  GET  /api/conditions/{site_id}           weather + ground risk + active condition rules

Behaviour
  GET  /api/behavior/events?operator&kind&period
  GET  /api/behavior/scorecard/{operator_id}
  GET  /api/behavior/idle-summary?scope    fuel/CO₂/cost

Maintenance
  GET  /api/machines/{id}/health           component health, RUL p10/p50/p90, risk index, drivers
  GET  /api/faults/{code}                  structured lookup
  POST /api/troubleshoot/photo             image → VLM diagnosis + manual refs + confidence + safe_to_continue
  POST /api/service-requests ;  GET /api/parts?component&q
  GET  /api/fluid-samples?machine
  GET  /api/maintenance/alerts?machine&site&tier&state          (rev 2)
  GET  /api/maintenance/alerts/{id}                              evidence series, forecast, explanation, actions
  POST /api/maintenance/alerts/{id}/ack | /schedule | /resolve | /feedback {false_alarm|confirmed}
  GET  /api/machines/{id}/sensors/{sensor_id}/forecast           trend + ETA p10/p50/p90 to each tier
  GET  /api/machines/{id}/service-due                            interval counters with severity-adjusted ETA
  GET  /api/maintenance/windows?site&from&to ;  POST /api/maintenance/windows/plan
  GET  /api/maintenance/estimate?component&work_type&machine     repair duration + cost p10/p50/p90
  GET  /api/fleet/availability?site&days                         7-day availability forecast

Planning & estimation (rev 2)
  GET  /api/tasks/{id}/start-recommendation                      best start, alternatives, curve, preconditions, factors
  POST /api/tasks/{id}/start-recommendation/accept               → updates plan, schedules preconditions (charge/refuel)
  POST /api/planning/day-plan {site_id, date}                    multi-task/multi-machine plan (MILP)
  GET  /api/machines/{id}/readiness                              score + breakdown
  GET  /api/tasks/{id}/energy-estimate                           kWh/L band, can-finish flag, recharge/refuel time
  GET  /api/tasks/{id}/cost-estimate                             fuel + wear + maintenance accrual per unit
  GET  /api/planning/weather-windows?site&task_type&hours        next workable windows
  GET  /api/tasks/{id}/machine-options                           ranked machines for this task (ETC, readiness, energy)

Energy
  GET  /api/machines/{id}/energy           fuel or battery state, projections
  POST /api/energy/charge-plan             {site_id, horizon} → MILP plan (gantt)
  GET  /api/energy/power-mode/{machine_id} recommendation + reason

Training
  GET  /api/training/me                    assignments, progress, certs, expiring
  GET  /api/training/modules, /lessons/{id}, POST /attempts
  GET  /api/training/slots?instructor&from&to ;  POST /api/training/bookings ; PATCH (cancel/reschedule)
  GET  /api/training/sim/drills ;  POST /api/training/sim/sessions (score)

Copilot
  POST /api/chat                           (SSE stream) {message, image?, audio?} → tokens + tool trace + citations + confidence
  GET  /api/chat/sessions/{id}

Admin / demo
  POST /api/admin/scenarios/{id}/start|stop ;  GET /api/admin/config/validate ;  GET /api/evals/latest
  GET  /api/admin/llm/status                                     Groq model availability, rate-limit headroom, fallback counts (rev 2)
```

WS message types added in rev 2: `maintenance_alert` (open/update/clear), `recommendation` (start-time or readiness change), `plan_update`.

### 9.3 WebSocket message contract (Pydantic → JSON Schema → TS)

```json
{ "type": "advisory", "id": "adv_…", "category": "grade", "severity": "advisory",
  "text": "Raise bucket 4 cm — undercutting design grade.", "source": "llm|template",
  "facts": {"deviation_cm": -4.1, "direction": "raise"}, "expires_in_s": 6, "priority": 62 }
```

---

## 10. Feature specifications

Each spec gives **logic → config → UI → acceptance**. Numbers in examples are defaults that live in config.

### 10.1 Onboarding, auth and machine selection (P0)

- **Flow:** badge/PIN login → QR scan (camera via `BarcodeDetector`/zxing), or pick from a list of machines on the operator's site → backend returns the manifest + **gating result**.
- **Gating:** a valid cert for every `manifest.training.required_modules` item → `full`. An expired module inside a grace window → `restricted` (the UI shows a banner and a supervisor is notified). A missing module → `blocked`, with a CTA to "Book instructor / Start module".
- **Pre-shift:** mandatory walkaround (§10.3.3) and seatbelt check before the cockpit unlocks. Both are configurable per manifest.
- **Acceptance:** scanning a different machine's QR swaps the layout, gauges, rules and RAG scope with no reload of the app bundle. A blocked operator cannot open the cockpit.

### 10.2 Machine Profile Manifest (P0)

- Loader + validator + derived values: tail swing radius, reach envelope polygon, tipping lines.
- **Manifest swap demo:** a second class (wheel loader) is fully configured, with rules, layout and manual scope, even if its simulator generator is simpler.
- **Acceptance:** adding a new machine model = adding one YAML file + layout. Zero code changes (checked by a test that loads a fixture manifest and asserts the full pipeline runs).

### 10.3 Daily task dashboard (P0)

1. **Today view:** shift header (site, machine, hours, weather strip, **machine readiness score**), plus a task list/timeline with planned vs. predicted windows and a status for each task. Each card shows:
   - quantity and progress;
   - ETC p50 with a p10–p90 band;
   - top 2 "why" factors (e.g. "Rain +11 min", "Clay soil +7 min");
   - dependencies;
   - **rev 2:** a "Best start" chip (§10.14), an energy sufficiency badge (§10.15.3), and any maintenance alert that affects the task (§10.13).
2. **Shift pacing gauge:** actual cumulative output vs. the benchmark curve. The benchmark is the plan distributed across the shift, adjusted for scheduled breaks, and is pulled from `analytics.pacing`.
3. **Pre-shift walkaround** (60-second interactive): checklist items from `config/walkaround/<class>.yaml`. Each item is ok/issue/photo. Issues auto-create a maintenance note, and "critical" items block start.
4. **Cab notes:** push-to-talk → Groq Whisper (`stt`; faster-whisper fallback) → text → auto-tags (keyword + LLM classifier: maintenance/safety/site/other) → optional conversion to a service request or hazard report.
5. **Shift summary** (end of shift): output, idle cost, alerts, compliance, and suggested drills.
- **Acceptance:** everything on the page comes from `/api/me/shift` and the layout config. Changing a task's quantity in the DB changes its ETC and card with no frontend change.

### 10.4 Safety

#### 10.4.1 Seatbelt compliance (P0)

- **Signals:** `seat.occupied`, `seat.belt_fastened`, motion, hydraulic activity.
- **Rule:** `SEATBELT_UNFASTENED_ACTIVE` (§6.2), with a grace period, escalation, and a black-box mark.
- **Compliance metric:** `1 − unbelted_active_s / active_s` per shift, operator, machine and site.
- **Supervisor notification on escalation.**
- **"Interlock recommendation"** flag in the report (advisory only; we never actuate).
- **UI:** a persistent belt icon in the status bar, colour-coded by tier; a compliance % on the operator scorecard and the supervisor compliance board.
- **Acceptance:** the scenario unbuckles at t=5 → caution after the grace period → warning after escalation. The compliance number updates and the event appears in the behaviour log.

#### 10.4.2 Pedestrian proximity and trajectory prediction (P0)

- **Input:** detections (simulated or YOLO on video) → tracks (SORT/ByteTrack for video; the simulator provides IDs).
- **Tracking:** a constant-velocity Kalman filter per track. Static-object filtering: speed below `min_moving_speed` and not inside the swing envelope → suppressed. This keeps false alarms down.
- **Risk:**
  - closest point of approach (CPA) and **time-to-collision** vs. the machine's *dynamic* hazard zone (the swing envelope when slewing, the travel corridor when tracking);
  - zone membership (advisory/caution/warning radii from the manifest).
- **Severity** = max(zone tier, TTC tier). Swing toward a person raises the tier.
- **PPE:** the same pipeline classifies helmet/vest per track. A missing-PPE person inside the work zone → advisory to the operator + a supervisor compliance event.
- **UI:** proximity radar widget + persons in the 3D twin with predicted-path arrows.
- **Acceptance:** the scenario person walking toward the swing path triggers caution before entering the warning radius (shown by TTC). A parked person outside the envelope is not alerted.

#### 10.4.3 Machine-to-machine P2P proximity (P1)

- Each machine broadcasts its position, heading, speed and envelope over Redis (standing in for V2V radio).
- Pairwise CPA/TTC is computed. Rules cover haul-road crossings and blind-spot reversing.
- **Acceptance:** an ADT reversing toward an excavator's tail swing triggers alerts on both machines.

#### 10.4.4 Utility and overhead geofencing (P0 buried, P1 overhead)

- 3D distance from the bucket tip (via forward kinematics) to the buried utility polyline, minus depth uncertainty.
- Distance from the boom tip's highest point to the overhead line, minus the clearance.
- Tiers come from the geofence's `clearance_m` plus manifest multipliers. Source quality (`surveyed | as_built | estimated`) widens the margin.
- **Acceptance:** the scenario at t=150 triggers "Hold position — utility U-07 1.8 m ahead of dig line" as an advisory, then caution.

#### 10.4.5 Rollover and stability envelope (P0)

- A static stability model in the machine frame, including slope from IMU pitch/roll.
- Component masses (undercarriage, upper, counterweight, boom, stick, bucket + payload) at positions from forward kinematics, rotated by the slew angle and projected onto the tipping line in the load direction.

  ```
  margin = M_restoring / M_overturning   (about the relevant track edge, gravity vector tilted by slope)
  ```

- The payload comes from hydraulic pressure weighing (sim).
- Dynamic factor: swing angular acceleration adds a centrifugal term (P1).
- Output: margin, the limiting axis, and a "what reduces risk most" hint (reduce reach vs. stop slew vs. lower load), computed by finite difference on each input. The copilot uses this hint.
- **Acceptance:** unit tests against hand-computed cases. Scenario side-slope + extended reach → caution with the correct limiting axis.

#### 10.4.6 Working conditions (P0)

Rules in `config/rules/conditions.yaml`:

| Condition | Rule (thresholds in config) | Effect |
|---|---|---|
| Wind/gust | gust > limit for lifting/high boom | caution; copilot suggests lowering boom height |
| Lightning | strike within X km | warning: stop work, shelter protocol |
| Heat index | above tier → hydration/rest cadence | advisory timer; fatigue model input |
| Visibility | below threshold (dust/fog/rain) | reduce travel speed advisory; proximity zones scaled up |
| Rain / ground | ground risk score tier ↑ | slope/traction caution |
| Night | lux / time | proximity zones scaled, fatigue weight ↑ |

- **Ground/terrain risk score (P1):**

  ```
  risk = w1·surface_class_risk + w2·slip_ratio_risk + w3·(1/FoS) + w4·moisture
  ```

  - `surface_class_risk` comes from the camera classifier (wet/loose/rocky/firm).
  - `slip_ratio` = (track speed − GPS ground speed) / track speed, from wheel encoders vs. GNSS.
  - FoS comes from the slope model.
  - The weights are in config and are validated by logistic regression on the generated incident data.

#### 10.4.7 Fatigue and whole-body vibration (P1)

- **Fatigue:** MediaPipe Face Mesh → eye aspect ratio (EAR) → PERCLOS over a rolling window, microsleep (eye closure > t), head-nod frequency, gaze-off-road ratio.
  - Fatigue score = logistic model over these + hours on shift + circadian factor + heat.
  - Tiers → advisory ("take a 10-minute break"), then caution, then supervisor escalation (human-in-the-loop).
  - Demo inputs: webcam live, or simulated signals.
- **WBV:** seat accelerometer, frequency-weighted per ISO 2631-1 (Wk/Wd).

  ```
  A(8) = sqrt( (1/T0) Σ a_w,i² · t_i ),   T0 = 8 h
  ```

  - Compared against the exposure action/limit values in config (EU directive defaults are 0.5 / 1.15 m/s²).
  - Projected end-of-shift A(8) → advisory ("reduce travel speed on rough haul road").

#### 10.4.8 Incident logging and black box (P0)

- **Automatic:** ring buffer of `pre_s` seconds. Triggers are: warning-tier alert, IMU jerk/G spike > threshold, emergency stop, sudden hydraulic loss, or a manual "Mark" button. On a trigger, the buffer and `post_s` more seconds of frames are saved, along with the alert context and snapshots.
- **Manual report:** server-driven form (`config/ui/forms/incident_report.yaml`) for incident / near miss / hazard observation. Photos and voice are attached, and GPS and machine state are auto-filled.
- **Playback:** a timeline scrubber that replays the frames in the 3D twin, with alert and advisory markers. This is reused in the training hub as case studies.
- **Supervisor workflow:** new → under review → root cause → corrective action → closed. The workflow states come from config.
- **Acceptance:** the scenario's G-spike creates an auto incident, and playback reproduces the machine pose and the person track.

### 10.5 Unusual behaviour detection (P0)

Three detector layers write to `behavior_events`:

1. **Rule/episode detectors** (deterministic state machines, thresholds from the manifest):
   - **Idle:** engine on AND joysticks neutral AND ground speed ≈ 0 AND hydraulic flow ≈ 0 for ≥ `idle.min_episode_s`. "Excessive" when ≥ `idle.excessive_s` or when the shift idle ratio > `max_idle_ratio`. High-RPM idle is flagged separately.
   - **Unsafe patterns:** harsh swing (angular accel > limit), swing over a person/cab/truck cab, travel with the boom raised, travel/work beyond the side-slope limit, prolonged relief-valve stall, overload vs. rated payload, rapid control reversals, operating unbelted, work near a geofence without acknowledging it, and cavitation-inducing inputs.
2. **Statistical baselines:** per-operator and per-machine rolling baselines (median/MAD) of per-cycle features. A robust z-score > k flags "unusual for you", e.g. cycle time up 40% vs. your norm → possible fatigue or machine issue.
3. **ML:** Isolation Forest on per-cycle feature vectors (phase durations, payload, fuel/cycle, max pressure, swing accel, joystick entropy). The contamination rate is set in config. An LSTM autoencoder on raw sequences is P2.

- **Cost attribution:**
  - idle fuel = `idle_fuel_lph × duration`;
  - cost = fuel × price (config);
  - CO₂ = fuel × emission factor (config);
  - extra engine hours → maintenance cost.
- **Outputs:**
  - live advisory ("Engine idling 6 min — shut down? Truck ETA 9 min");
  - operator scorecard;
  - supervisor anomaly board;
  - **auto-assignment of training drills** (§10.8.5).
- **Evaluation:** precision/recall/F1 per kind vs. `truth_behavior_labels`, and the cost error vs. the truth.
- **Acceptance:** the idle scenario at t=300 shows the advisory, the idle event closes with the fuel and cost figures, and a training assignment is created if the operator's weekly idle count crosses the config threshold.

### 10.6 Task time estimation (P0)

- **Features:**
  - **task:** type, quantity, unit, depth, haul distance, design complexity;
  - **machine:** class, bucket/payload capacity, powertrain, health index;
  - **operator:** experience, rolling productivity, skill estimate;
  - **environment:** forecast temp, rain, wind, visibility, soil type, moisture, density, slope FoS;
  - **context:** truck count, time of day, day of week, site.
- **Models:**
  - **baseline:** a physics estimate (quantity / (bucket × fill × cycles/h)), shown for comparison;
  - **main:** LightGBM quantile regression (α = 0.1, 0.5, 0.9) on `log(duration)`, wrapped with **Conformalized Quantile Regression** (MAPIE) for calibrated 80% intervals;
  - a per-task-type residual correction if the data supports it.
- **Explainability:** SHAP on the p50 model → top positive and negative factors, localised through i18n keys (e.g. `factor.rain`).
- **Live ETC update:**

  ```
  rate_live = (n·rate_obs + k·rate_model) / (n + k)      # n = completed cycles, k = prior strength from config
  ETC = now + remaining_qty / rate_live  (interval from bootstrapped residuals of rate_obs + model interval)
  ```

- **Forward recommendation (rev 2):** the inverse question, "when *should* I start to finish fastest?", is handled by the start-time optimiser in §10.14. It reuses this model.
- **Backward scheduling:** given a deadline, invert the p90 (or a user-chosen confidence) to get the latest safe start. Dependencies are handled as a DAG critical path. For electric machines, battery floor feasibility is checked by calling the energy module.
- **Weather what-if:** a slider on the supervisor view (forecast scenarios from `weather_hourly` forecasts) → re-estimate.
- **Evaluation:** MAE/MAPE of p50, **PICP** (target ≈ nominal), mean interval width, pinball loss, and a comparison against the baseline. A per-condition breakdown (rain vs. dry) proves environmental conditions are used.
- **Acceptance:** evals meet the targets in `config/models.yaml`. The UI shows band + factors. The live ETC converges during the scenario.

### 10.7 Predictive maintenance

#### 10.7.1 Component health and RUL (P1)

- **Health index per component:** a weighted fusion of normalised trend features (pressure ripple, temp delta to ambient, vibration RMS/kurtosis, filter ΔP, DPF soot/regen frequency, fluid sample wear metals).
- **RUL:**
  - LightGBM on engineered windows (P1), with quantiles + conformal;
  - LSTM on sequences (P2);
  - both evaluated against `component_health_truth`.
- **Contextualised risk index:** a Cox PH model with climate/duty covariates. It gives the failure probability within a horizon H:

  ```
  P(fail ≤ t+H | survived t, x) = 1 − S(t+H|x)/S(t|x)
  ```

  This probability is blended with the fault history, and the blend weights are in config. Traffic-light bands come from config, and the top covariate contributions are shown ("dust +18%").
- **DPF regen countdown**, **GET wear** (wear rate ∝ cumulative dig energy × soil abrasiveness), **undercarriage wear** (hours × terrain roughness × travel share).
- **Fluid samples:** lab ratings folded in as features, plus a trend chart with ISO cleanliness.
- **Rev 2:** live sensor-based maintenance alerting, forecasting and window planning are specified in §10.13 and §10.15. The health index and risk index above are inputs to both.

#### 10.7.2 Fault codes and service actions (P0 lookup, P1 request)

- **Structured lookup tool:** code → catalogue row → linked manual chunk(s) → safe-to-continue flag → parts.
- **"Request Part / Request Service":** pre-filled form (server-driven) → `service_requests` → mock dealer adapter returns an ETA/stock → status on the mobile app.

#### 10.7.3 Visual troubleshooting (VLM) (P1)

- **Pipeline:**
  1. The photo is uploaded, with optional operator text.
  2. The VLM (Groq `vlm_troubleshoot`: Llama 4 Scout with image input) is prompted with the manifest components, and a **closed label set** from the fault catalogue plus "unknown". It returns JSON: `{label, confidence, visible_evidence, component}`.
  3. **Grounding:** the label maps to fault/procedure → RAG fetches the manual section → the answer cites it.
  4. **Guard:** if confidence < threshold (config) or the label is safety-relevant and ambiguous → escalate to a technician. It never auto-declares "safe to continue". The safe-to-continue flag comes from the catalogue, never from the VLM.
- **Calibration:** confidence from self-consistency (k samples, agreement rate) rather than the model's verbalised number. Temperature-scaling on the eval set is P2.
- **Acceptance:** 3–5 staged demo photos produce the correct label + manual page. An ambiguous photo triggers escalation.

### 10.8 Training hub

#### 10.8.1 E-learning videos (P0)

- Module → lessons. The video player has chapters (from `video_assets.chapters`), progress tracking, and resume.
- Completion = watched ≥ `completion_ratio` (config) + passed the quiz.

#### 10.8.2 Quizzes (P0)

- The question bank is grounded in manual chunks (each question links its source).
- Randomised, adaptive difficulty (P1). The pass mark is in config.
- Wrong answers show the cited manual excerpt.

#### 10.8.3 Instructor booking (P0)

- **Instructor side:** instructors publish availability slots (on-site / remote / simulator bay, capacity).
- **Operator side:** operators browse and book. Cancel/reschedule windows come from config. Conflict checks run against the shift schedule.
- **Notifications:** in-app, with email as a stub.
- **Supervisor view:** sees bookings tied to assignments.
- **Acceptance:** a double-booking or a clash with an assigned shift is rejected with a localised reason.

#### 10.8.4 Simulation module (P1)

- A browser 3D excavator built with react-three-fiber. It uses the **same kinematics/stability code**, ported to TS through a shared JSON spec of the manifest geometry, and the **same rules** evaluated server-side over WS, so trainees see real alerts.
- Controls: keyboard/gamepad mapped by `controls/excavator_iso.yaml` (ISO vs. SAE patterns are selectable).
- **Drills (config-defined):** dig to grade within tolerance, fill a truck to target payload ±%, avoid a pedestrian crossing, smooth swing (penalise jerk), and slope work within the stability margin.
- **Scoring:** weights in config; results go to `sim_sessions`.
- **Incident replays** (from the black box) as "what would you do" case studies (P2).

#### 10.8.5 Adaptive assignment (P0)

- A rules table maps a behaviour/maintenance signal → module. For example:
  - repeated cavitation → "Stick & bucket control" drill;
  - idle ratio > limit → "Fuel-efficient operation" video;
  - belt violations → "Restraint safety" + a supervisor talk;
  - a pedestrian near miss → "Proximity awareness".
- **Priority score** = severity × frequency × recency. Due dates come from config.
- Certification status gates machine access (§10.1). Expiring certs create assignments N days ahead.
- **VR walkthrough:** P2 (the same three.js scene in WebXR).

### 10.9 Battery and charging (electric machines) (P1)

- **SoC model:** consumption kW per load state (idle, travel, dig, swing, lift) from the manifest, adjusted by temperature. The SoC projection uses the planned tasks.
- **Hard floor:** `energy.soc_floor` (default 15%) from config. The rules engine enforces a warning when the projection crosses the floor before the next charge window.
- **Idle-window prediction:** truck-wait windows predicted from the haul cycle model and queue state.
- **MILP (PuLP):**

  ```
  sets: machines m, time slots t, tasks j, chargers k
  vars: a[m,j,t]∈{0,1} (work), c[m,t]∈{0,1} (charge), soc[m,t]≥0
  soc[m,t+1] = soc[m,t] + η·P_chg·Δt·c[m,t] − Σ_j e[m,j]·a[m,j,t]
  soc[m,t] ≥ floor                                   ∀m,t       (hard)
  Σ_m c[m,t] ≤ K_site(t)                             ∀t         (charger capacity)
  a[m,j,t] + c[m,t] ≤ 1                              ∀m,j,t
  Σ_t a[m,j,t]·rate[m,j] ≥ qty[j]  by deadline[j]    ∀j
  c[m,t] only if m at/near charger or idle window predicted (penalty otherwise)
  max  Σ utilisation − λ1·charging_outside_idle − λ2·lateness
  ```

- **UI:** a gantt of the charge + work plan, SoC projection lines with the floor, and a "why" explanation (binding constraints from the solver's duals/slacks).
- **Acceptance:** the solver returns a feasible plan that never crosses the floor. Infeasible cases say which constraint is binding.

### 10.10 Fuel efficiency and power mode (P1)

- Digging resistance proxy = pump pressure × flow / cycle payload.
- The recommendation (Eco / Standard / High) comes from a lookup band table + a hysteresis dwell time (config).
- Estimated fuel savings are shown.
- The shift summary shows fuel/m³ vs. the fleet median.

### 10.11 Supervisor and fleet view (P1)

- Site map (machines, persons, geofences, live alert pins).
- Alert queue with ack.
- Compliance boards (seatbelt, PPE, walkaround completion).
- Anomaly board.
- Task planner (create/assign, ETC, what-if).
- Charge plan.
- Incident review workflow.
- Training oversight.
- Fatigue escalation inbox (human-in-the-loop).
- **Rev 2:**
  - maintenance alert board (by tier/site);
  - maintenance window calendar;
  - day-plan optimiser gantt with recommended starts;
  - machine selection for a task;
  - 7-day fleet availability vs. workload;
  - readiness column on the fleet list;
  - an LLM status tile (Groq headroom and fallback counts, from `/api/admin/llm/status`).

### 10.12 Technician view (P2)

- Work orders from service requests.
- Health drill-down.
- Fluid sample history.
- Closing a work order resets health in the sim.
- **Rev 2:**
  - a maintenance-alert inbox (§10.13) with evidence charts;
  - technician slot management (feeds the maintenance-window planner, §10.15.1);
  - "confirm / false alarm" feedback buttons, which feed the eval labels.

### 10.13 Sensor-based equipment/vehicle maintenance alerts (rev 2) (P0 core, P1 advanced)

**Goal:** catch developing equipment and vehicle problems from live and historical sensor values, early enough to plan the repair (parts lead time + scheduling), and tell the right person what to do.

**Scope:** every channel in `manifest.maintenance_sensors`, across all classes:

- **Common:** engine (coolant temp, oil pressure vs. rpm, air-filter restriction, water-in-fuel, DPF soot, voltage), hydraulics (oil temp, pressure ripple, filter ΔP, flow efficiency) and drivetrain (transmission/brake temps).
- **Excavator:** swing-drive vibration, track tension.
- **Wheel loader / ADT (vehicles):** tyre pressure/temperature, brake temperature, suspension strut pressure.
- **Electric machines:** battery cell ΔV, pack temperature, insulation resistance, charger faults.

**Detection layers** (all deterministic or classical ML; each outputs an `EvidenceItem`):

| # | Layer | Logic | Example | Priority |
|---|---|---|---|---|
| A | **Limit / band** | Value (or margin vs. a curve such as oil pressure vs. rpm) in the monitor / service_soon / stop band, with debounce + hysteresis. Runs in the edge rules engine for stop-tier, so it works offline | Coolant 104 °C → service_soon | P0 |
| B | **Rate of change** | Robust slope (Theil–Sen) over a sliding window > configured rate | Hyd oil temp +1.8 °C/min at normal load | P0 |
| C | **Time-to-threshold forecast** | Per-sensor trend model on duty-normalised residuals (Holt/ETS; LightGBM quantile where covariates like ambient temp matter). Outputs `P(cross tier within H)` and ETA p10/p50/p90. **Lead-time aware:** raise when `eta_p10 < parts_lead_time + scheduling_buffer` | Filter ΔP will hit the service limit in ~31 h (p10 18 h) → order filter now | P0 |
| D | **Multivariate signatures** | Condition patterns from `config/maintenance/signatures.yaml`, evaluated on windowed features | Temp↑ + ripple↑ + flow efficiency↓ → pump wear | P1 |
| E | **Fleet-peer drift** | Residual vs. same-model machines under similar ambient/load (regression-normalised). Robust z > k for sustained N hours | EX-03 runs 6 °C hotter than peers in the same conditions | P1 |
| F | **Service-interval counters** | Hours / fuel / loads since last service vs. manifest intervals, adjusted by the climate severity factor from §10.7.1 | "250 h service due in 14 h (dusty-site severity ×1.3)" | P0 |
| G | **Fluid sample limits** | Lab values vs. limits table (wear metals, silicon, water, viscosity) | Si 38 ppm → dirt ingestion | P1 |
| H | **Fault codes** | Existing fault events (§10.7.2) merged into the same alert object | — | P0 |
| I | **Multivariate anomaly** (catch-all) | Isolation Forest / Mahalanobis on normalised residual vectors per component | Unknown pattern → monitor tier + technician review | P2 |

**Alert fusion and lifecycle:**

- **Merge:** evidence items are merged per (machine, component) into one `maintenance_alert`. Tier = max of the items, promoted when ≥ 2 independent layers agree (config). This dedupes and prevents alert storms.
- **Lifecycle** (from `config/maintenance/lifecycle.yaml`): `open → acknowledged → scheduled → in_service → resolved | false_alarm`. Alerts are auto-suppressed while a work order is open and auto-reopened if they recur within N hours after a fix.
- **Enrichment:**
  - fault-catalogue action + **safe_to_continue** (always from the catalogue, never from an LLM);
  - parts;
  - repair duration/cost estimate (§10.15.2);
  - suggested maintenance window (§10.15.1).
- **Groq explanation:** a plain-language explanation (`maint_explainer`) built only from the evidence JSON + the retrieved manual chunk. Numbers are validated like the live narrator (§12.1), and the template is the fallback.
- **Routing by tier:**

  | Tier | Operator (cab) | Mobile | Technician / supervisor |
  |---|---|---|---|
  | `stop` | Caution/warning alert **through the safety rules engine** | Yes | Push |
  | `service_soon` | Advisory via the live copilot candidate generator `maintenance` (respects declutter) | Yes | Inbox |
  | `monitor` | Not shown (declutter) | No | Dashboard only |

- **Work order draft:** one tap from the alert → service request (§10.7.2) pre-filled with evidence and parts.
- **Link to training:** if the wear is attributed to operating behaviour (e.g. repeated relief-valve stalls → hydraulic heat), the adaptive assignment rule fires (§10.8.5).

**UI:**
- a maintenance alert card with tier chip, sensor sparkline + forecast cone with threshold lines, ETA, "why" bullets, safe-to-continue, actions (Ack, Schedule, Request part);
- a machine health page tab "Sensor watch", with all channels, bands and forecasts.

Every visual is config-driven (bands and colours from config/theme).

**Evaluation:** against `truth_fault_modes`:
- detection rate;
- **median lead time** (detection → failure) and lead time vs. the parts lead time;
- false alarms per 100 machine-hours;
- precision by tier;
- forecast PICP for the ETA.

**Acceptance:**
- The maintenance scenario raises a trend alert, then a forecast alert with an ETA band, then the signature match. They merge into **one** alert with rising tier.
- Stop-tier alerts work with Groq disconnected.
- No duplicates.
- A work order can be created in one tap.

### 10.14 Optimal job start-time recommendation (rev 2) (P0 single task, P1 day plan)

**Goal:** for each upcoming task, recommend **when to start** (and what to do first) so the operator finishes **faster than usual** and within the deadline. The factors are environment, vehicle condition and charge/fuel.

**Factors (all projected to each candidate start time `t`):**

| Group | Factors | Source |
|---|---|---|
| Environment | Forecast temp, rain, wind/gusts, visibility, lightning risk, heat index, daylight; ground moisture/drying curve, bearing capacity, slope FoS | weather_forecast, ground model (§7.3) |
| Vehicle condition | Readiness score, component health, open maintenance alerts + forecast ETAs (avoid starting a long task that will hit a `service_soon` threshold mid-task), scheduled maintenance windows, walkaround issues | §10.13, §10.15.5 |
| Energy | SoC/fuel at `t` (including charging possible before `t`), energy needed for the task (§10.15.3), charger availability, 15% floor | energy module, MILP |
| Operations | Truck/haul availability forecast, dependency completion, site congestion, shift/break windows | tasks, truck forecast |
| Operator | Fatigue projection over the work window, hours on shift, skill for this task type | fatigue model, profiles |

**Algorithm (P0):**

1. **Candidates:** a grid of start times over `planning.start_time.horizon_h` in steps of `step_min`, filtered to shift windows and after dependencies.
2. **For each candidate `t`:**
   - **Duration distribution:** call `task_duration` (§10.6) with covariates averaged over the *expected work window* `[t, t + D]`. Because the window depends on D, iterate a fixed point 2–3 times.
   - **Pre-work time:** charge minutes needed so that `SoC(t) − E_task,p90 ≥ floor` (or a mid-task charge stop is added, with its time); refuel minutes; any mandatory pre-start items.
   - **Stoppage risk:** `P(weather hard-stop during window)` from forecast spread (lightning, gusts over the lifting limit) × expected delay.
   - **Safety risk index:** ground risk, night/visibility, wind for high-boom work, fatigue.
   - **Maintenance conflict:** `P(maintenance alert crosses service_soon during window)` from the sensor forecasts.
3. **Constraints (hard):**
   - completion at `quantile_for_deadline` ≤ deadline;
   - SoC ≥ floor at all times;
   - no overlap with a scheduled maintenance window;
   - no active weather hard-stop rule;
   - machine readiness ≥ the `caution` band.
4. **Score:**

   ```
   J(t) = w_p50·D50(t) + w_spread·(D90−D50) + w_stop·E[stop delay] + w_safety·risk(t) + w_wait·(t − now)
   ```

   All weights are in `config/planning.yaml`. Pick `t* = argmin J` among the feasible candidates.
5. **"Usual" baseline:** the median actual duration of the k most similar historical tasks (kNN on task features), shown as "usual". Also computed: the saving vs. starting **now** and vs. **usual**. Only recommend a change if the saving ≥ `min_saving_to_recommend_min`.
6. **Why:**
   - SHAP delta between `t*` and `now` (e.g. "ground drained: −14 min; full charge avoids mid-task stop: −11 min; cooler temps: −4 min");
   - binding constraints;
   - a Groq `plan_explainer` sentence (validated; template fallback).
7. **Preconditions** turn into actions: "Charge to 85% (25 min) — reserve charger C2", "Refuel before start", "Clear filter ΔP alert — technician slot 08:30". Accepting the recommendation creates or reserves these.

**Day plan (P1):**
- The MILP from §10.9 is extended with slot-dependent durations `d[j,t]` precomputed from the model.
- Objective: minimise total expected completion + lateness, subject to machines, chargers, operators, maintenance windows and dependencies.
- Output: a gantt with recommended starts for every task and machine.

**Live integration:**
- The live copilot generator `plan` can emit "Starting at 10:30 instead of now saves ~18 min (ground drying, full charge)".
- If conditions change (new forecast, alert opened), the recommendation updates and a `recommendation` WS message is pushed.

**UI (all bound to API data):**
- on each task card, a "Best start" chip;
- a detail sheet with the **duration-vs-start-time curve** (p50 line + p10–p90 band), infeasible regions shaded by constraint type, markers for "now", "recommended" and "usual", factor bars, a preconditions checklist, and an Accept button.

**Evaluation:**
- counterfactual **regret** vs. the generator oracle (§7.4b);
- the % of tasks where following the recommendation beats the planned start;
- mean minutes saved vs. usual;
- constraint-violation rate (must be 0 in backtest);
- PICP of the predicted duration at the recommended start.

**Acceptance:** the `demo_start_time` scenario produces the recommendation with preconditions. Accepting it reserves the charger. The backtest regret and savings meet the targets in `config/models.yaml`.

### 10.15 Companion maintenance and estimation features (rev 2)

#### 10.15.1 Maintenance window recommendation (P1)

For each open alert and each due service item, choose the best service window:

- **Before:** `failure_eta_p10` (or the tier deadline).
- **After:** parts arrival (lead time).
- **Within:** technician availability.
- **Preferring:** predicted idle / weather-stop / low-priority periods.
- **Bundling:** other due items within `bundle_within_h` (opportunistic maintenance, so one stop replaces two).

The objective minimises production impact (lost task hours × priority) + failure risk cost. It is solved as a small MILP or by greedy + local search.
**Output:** window, estimated downtime (from §10.15.2), cost, production impact avoided vs. run-to-failure, rationale. It feeds §10.14 (the optimiser avoids these windows) and the 7-day availability forecast.

#### 10.15.2 Repair duration and cost estimation (P1)

- LightGBM quantile on `maintenance_records`. Features: component, work type, technician experience, parts in stock vs. ordered, site remoteness, machine age/hours.
- Output: p10/p50/p90 hours + parts + labour cost (rates in `config/maintenance/costs.yaml`).
- Shown on alerts, work orders and window plans.

#### 10.15.3 Energy/fuel per task + "can I finish on this charge?" (P0)

- Energy model: per-cycle kWh/L from the cycle model × predicted cycles (quantiles), plus travel and idle allowance. Output: p10/p50/p90.
- **Can-finish flag:** `SoC_now − E_p90 ≥ floor` (or the fuel equivalent).
- **Recharge/refuel time estimate:** minutes to reach the target given the charger power curve (taper above x% SoC, from the manifest) or the refuel rate.
- The cockpit energy card shows "Enough for this task: yes (margin 12%)" or "Charge 22 min first".

#### 10.15.4 Task wear and cost estimate (P1)

- Per task:
  - fuel/energy cost;
  - GET wear (abrasiveness × dig energy);
  - undercarriage/tyre hours consumed;
  - maintenance accrual (cost per hour by component);
  - → **cost per m³ / per load**.
- Compared across candidate machines (§10.15.7) and start times (wet ground → more wear).

#### 10.15.5 Machine readiness score (P0)

```
readiness = Σ w_i · component_i
```

- Components: health index, open maintenance alert tiers, energy vs. next task, walkaround result, operator cert validity. Weights and bands are in `config/planning.yaml`.
- Shown at machine select and on the supervisor fleet list, and used as a constraint and factor in §10.14.
- A breakdown explains each deduction.

#### 10.15.6 Weather-window finder (P1)

- For weather-sensitive task types (lifting, grading, compaction, haul on clay), the rule set in config defines "workable" (wind < x, no rain for y h, ground moisture < z).
- The finder scans the forecast for contiguous workable windows long enough for the task's p90 duration and returns them with a confidence based on forecast spread.

#### 10.15.7 Machine selection for a task (P1)

- Rank the available machines for a task by expected completion time (task_duration with the machine's features), readiness, energy sufficiency and cost per unit (§10.15.4).
- This is a supervisor tool, and the chosen machine feeds the day plan.

#### 10.15.8 Fleet availability forecast (P1)

- A 7-day `P(available)` per machine from scheduled windows, open alert failure probabilities (Cox/forecast) and charging needs.
- The supervisor sees the expected capacity vs. planned workload.

#### 10.15.9 Service-due countdowns (P0)

- Severity-adjusted interval counters from §10.13-F, shown as countdowns ("250 h service in 14 h").
- They automatically feed the maintenance-window planner.

---

## 11. ML model inventory

Registered in `config/models.yaml`. Training is `tp train <name>`, artefacts are tracked in MLflow, and they are served in-process.

| Model | Type | Target | Key metrics (targets in config) | Priority |
|---|---|---|---|---|
| `task_duration` | LightGBM quantile + CQR | task minutes | MAPE, PICP@80 within ±5 pts, pinball | P0 |
| `live_etc` | Bayesian blend (analytic) | remaining time | convergence error vs. truth over progress | P0 |
| `idle_detector` | rule state machine | idle episodes | F1 vs. truth | P0 |
| `cycle_anomaly` | Isolation Forest + robust z | unusual cycles | precision@k, recall vs. truth labels | P0 |
| `fatigue_score` | logistic over PERCLOS etc. | fatigue tier | AUROC, recall at fixed FPR | P1 |
| `component_rul` | LightGBM quantile (+LSTM P2) | hours to failure | MAE, PICP | P1 |
| `risk_index` | Cox PH (lifelines) | P(fail within H) | C-index, Brier score, calibration curve | P1 |
| `surface_class` | Pretrained ResNet/EfficientNet fine-tuned on a small set, or simulated labels | wet/loose/rocky/firm | accuracy, confusion | P2 (simulated class P1) |
| `ppe_person` | YOLO pretrained (person + PPE) | detections | mAP on a small labelled clip set; FN weighted | P1 |
| `slip_estimator` | small MLP/GBM on IMU + encoders | slip ratio | RMSE vs. sim truth | P2 |
| `vlm_troubleshoot` | prompted VLM, closed label set | fault label | accuracy, ECE, FN rate on safety labels | P1 |
| `ground_risk` | weighted formula, weights fit by logistic regression | incident likelihood | AUROC | P1 |
| `sensor_baseline` (rev 2) | per-sensor regression (ambient, load, rpm) → residuals | normal value | residual RMSE, stationarity on healthy data | P0 |
| `sensor_forecaster` (rev 2) | Holt/ETS on residuals; LightGBM quantile where covariates matter | value at horizon, ETA to tier | ETA PICP, MAE of ETA vs. truth crossing | P0 |
| `maint_alert_fusion` (rev 2) | rules + signatures + peer z-score (+ IForest P2) | alert/tier | detection rate, median lead time, false alarms / 100 h | P0/P1 |
| `repair_estimate` (rev 2) | LightGBM quantile + CQR | repair hours, cost | MAPE, PICP | P1 |
| `energy_per_task` (rev 2) | cycle-energy model × predicted cycles (quantile) | kWh / L per task | MAPE, PICP, can-finish accuracy | P0 |
| `start_time_optimizer` (rev 2) | grid search over `task_duration` + constraints (P0), MILP day plan (P1) | recommended start | counterfactual regret vs. oracle, minutes saved vs. usual, violations = 0 | P0/P1 |
| `usual_duration` (rev 2) | kNN over historical similar tasks | "usual" baseline | coverage of similar-task set, stability | P0 |
| `availability_forecast` (rev 2) | combination of window plan + failure probabilities | P(available) per day | Brier score | P1 |

Shared utilities:
- `ml/calibration.py` (conformal wrappers, PICP, ECE);
- `ml/explain.py` (SHAP → i18n factor keys);
- `ml/features.py` (one feature-definition registry used by both training and serving to avoid skew).

---

## 12. AI Copilot

### 12.1 Live Situational Copilot (P0)

**Pipeline (runs in the `edge` process at `copilot.tick_hz` from config):**

1. **Advisory generators** are deterministic pure functions of `MachineState`. Each returns `Candidate{key, category, severity, base_priority, facts{}, template_key, ttl}`. Generators:
   - grade deviation (with direction + magnitude);
   - stability ("reduce reach" vs. "stop slew" from the sensitivity hint);
   - proximity (with bearing + TTC);
   - utility/overhead distance;
   - cavitation/hydraulic temp;
   - payload (target vs. current pass);
   - idle;
   - power mode;
   - pacing ("2 loads behind plan");
   - fatigue break;
   - weather;
   - **rev 2:** `maintenance` (service_soon alerts relevant *now*, e.g. "Coolant trending hot — reduce load, service booked 15:00");
   - **rev 2:** `plan` (start-time/readiness advice before a task starts);
   - **rev 2:** `energy` ("Enough charge for this task: margin 12%" or "Charge 22 min first").
2. **Arbiter:**

   ```
   score = base_priority(category) × severity_weight × urgency(TTC or trend) × novelty
   ```

   - Hysteresis + minimum dwell time + a per-category cooldown (config) stop flicker.
   - **Workload-adaptive:** in precision mode, only grade + safety categories are allowed.
   - Any open **caution or warning** alert pre-empts, and the banner shows the alert's template.
3. **Narrator:**
   - A Groq model (`live_narration`: `llama-3.1-8b-instant`, JSON schema output) gets `{facts, category, locale, max_words}` and returns JSON `{text}`. Identical fact sets are cached, so repeated advisories cost no tokens. The system prompt forbids new numbers, commands to override, and speculation.
   - The template is shown immediately. The LLM text replaces it if it arrives within the TTL and passes the validator.
4. **Output validator (guard):**
   - every number in the text must match a fact value (after unit rounding);
   - direction words must match `facts.direction`;
   - no banned phrases (config list);
   - length ≤ max.
   - On failure → keep the template and log a `guard_event`.
5. **Delivery:** WS `advisory` to the cab + mobile, with optional TTS (voice and rate from config) and an audible chime per tier from theme config.

**Acceptance:**
- The scenario produces, in order: the belt alert; a grade advisory ("Raise bucket 4 cm…"); a proximity caution; a utility hold; a wind advisory; a cavitation advisory; an idle advisory; a slope caution.
- The narrator never shows a number that isn't in the facts. This is tested by fuzzing facts.
- With the LLM down, everything still works on templates.

### 12.2 Ask mode (P0 basic, P1 full)

**LangGraph state graph:**

```
input (text | voice→Groq Whisper | image)
  → input_guard (Llama Prompt Guard 2 injection score + Llama Guard 4 moderation + NeMo topical + runtime rules)
  → router (Groq llama-3.1-8b-instant, tool calling, few-shot; outputs tool plan)
      ├─ sql_tool        : NL → SQL over allowlisted views (sqlglot validate: SELECT-only, allowed views, LIMIT, timeout, scoped to user's machine/site)
      ├─ rag_tool        : hybrid BM25 + dense (Qdrant) → RRF → optional rerank; filter machine_class ∈ manifest.knowledge_scope
      ├─ fault_tool      : structured code lookup
      ├─ predict_tool    : ETC / RUL / risk / charge-plan (returns p10/p50/p90)
      ├─ twin_tool       : current MachineState snapshot
      ├─ vlm_tool        : image diagnosis (§10.7.3)
      ├─ maint_tool      : maintenance alerts, sensor forecasts, service-due, repair estimates (rev 2)
      ├─ plan_tool       : start-time recommendation, readiness, energy-per-task/can-finish, weather windows, machine options (rev 2)
      └─ action_tool     : draft service request / booking / incident / accept start recommendation (requires user confirm in UI)
  → synthesizer (Groq llama-3.3-70b-versatile, streamed; answer ONLY from tool outputs; cite chunk ids / SQL / model ids)
  → output_guard (grounding check: every claim sentence has a citation or tool value; numeric consistency; refusal rules)
  → response {text, citations[], confidence, trace[], suggested_actions[]}
```

- **Bounded knowledge:** if retrieval's top score < threshold, or the grounding check fails → a localised "Not in the manual for this machine" + "Contact technician / dealer" action. Never guess.
- **Confidence badge:** a function of retrieval score, tool success, and model interval width (formula in config) → high/medium/low.
- **Reasoning trace:** a UI panel lists the tools called, the SQL executed (read-only), the chunks retrieved, and the model versions.
- **Chunking:** structure-aware chunking by heading/procedure. Each procedure is one chunk, with its steps kept together. Chunk metadata: `{machine_class, section, procedure_id, page, fault_codes[]}`.
- **Voice:** push-to-talk in the cab. Answers are short in the cab profile and detailed on mobile (profile in config).
- **Rev 2 example questions:**
  - "When should I start the trench on grid C?"
  - "Can I finish this on the current charge?"
  - "Why is the coolant alert on?"
  - "When is the next service due?"
  - "Which excavator is best for task T-2044?"

### 12.3 LLM gateway on Groq (rev 2) (P0)

`backend/terrapilot/llm/` is the **only** code path to any LLM. Every feature calls `llm.run(task="…", inputs=…)`, never a vendor SDK directly.

- **Provider clients:**
  - `GroqProvider` (official `groq` SDK: chat completions, tool calling, JSON-schema / JSON-object response formats, streaming, vision messages with base64 images, audio transcriptions, Batch API);
  - `OllamaProvider`;
  - `LocalProvider` (embeddings, faster-whisper);
  - `TemplateProvider` (i18n templates).
- **Task router:** resolves `task` → provider/model/params/prompt version from `config/llm.yaml`. Changing models is a config edit.
- **Structured outputs:** every task declares a Pydantic output schema. Responses are validated, repaired once on failure (a re-ask with the validation error), then the call falls back.
- **Rate limiting:** a token-bucket per model (RPM/TPM from config), continuously corrected from Groq's `x-ratelimit-remaining-*` / `retry-after` headers. Priority lanes: `live_narration` and `moderation` > `ask_*` > `summaries` > `content_gen`. Low-priority work yields when headroom is low.
- **Resilience:** per-task timeouts, retry with jittered backoff on 429/5xx (bounded by the task's latency budget), a circuit breaker per model, and the fallback chain from config. For example, the live narrator never retries; it just falls back to the template.
- **Caching:** Redis cache keyed by (task, prompt version, normalised inputs) for deterministic tasks (narration, explanations, SQL for identical questions).
- **Privacy / redaction:** pseudonymise operator names/IDs before sending and re-hydrate after. Enforce `never_send` (driver camera frames). Size-limit and strip EXIF from uploaded photos.
- **Prompt registry:** `config/prompts/*.j2` with versions. The prompt version is logged with every call, so evals compare versions.
- **Accounting and tracing:** every call is written to `llm_calls` (tokens, latency, model, fallback, cache hit) and to OpenTelemetry/Langfuse. The admin panel shows headroom and fallback rate.
- **Offline profile:** `TP_PROFILE=offline` routes to Ollama/templates. The demo can run with no internet.
- **Batch content jobs:** `tp content` submits JSONL to Groq's Batch API for manuals, quizzes and paraphrases. Results go to a human review queue before indexing.
- **Testing:** recorded responses (VCR-style cassettes) for CI, so tests don't consume Groq quota. A nightly "live" eval job hits Groq for real.

---

## 13. Guardrails and evals

### 13.1 Guardrail layers

| Layer | Mechanism | Examples (all rules in `config/guardrails/`) |
|---|---|---|
| Architectural | Safety logic outside the LLM; no actuation API exists | The copilot can't clear/suppress alerts: there is no tool for it |
| Input | NeMo Guardrails topical rails + **Llama Prompt Guard 2** (injection) + **Llama Guard 4** (moderation), both on Groq + length/attachment limits | Off-topic, legal/liability questions → redirect to supervisor/dealer. Injected instructions in cab notes/manual chunks → stripped/blocked |
| Runtime enforcement | Custom engine, `trigger → condition → action` | `vlm.confidence < 0.6 and label.safety_relevant → escalate`; `intent == override_alert → refuse`; `sql touches truth_* → block` |
| Output | Grounding validator, numeric consistency, banned-phrase list, PII scrub, Llama Guard 4 output check | Uncited claim → drop sentence or refuse. Maintenance/plan explanations with numbers not in the evidence → template |
| Decision authority (rev 2) | Only deterministic modules may set `safe_to_continue`, alert tiers, or recommended start times | An LLM explanation cannot change a recommendation or downgrade a maintenance tier |
| Human-in-the-loop | Escalation queue for low confidence, fatigue, safety-relevant VLM | Supervisor/technician inbox |
| Audit | `guard_events`, `predictions`, `chat_messages` with traces | Shown in the evals dashboard |

### 13.2 Eval suites (`evals/`, run with `uv run tp eval <suite>`, results in the DB + dashboard)

| Suite | Dataset | Metrics |
|---|---|---|
| `rag` | ~150 Q/A pairs from the manuals, with gold chunk ids (incl. 30 unanswerable) | Recall@k, MRR, answer faithfulness (LLM-judge + string checks), **bounded-knowledge accuracy** (refuses unanswerable, answers answerable) |
| `sql` | ~80 NL questions with gold SQL/results | execution accuracy, safety violations (must be 0) |
| `copilot_live` | Scenario frames + expected top advisory | top-1 agreement, numeric-hallucination rate (must be 0), latency p95 |
| `guardrails` | Adversarial bank: injection in cab notes/manual text, override requests, off-topic, jailbreaks, ambiguous images | block rate, false-refusal rate |
| `vlm` | Labelled photos | accuracy, ECE, safety-label FN rate (weighted) |
| `predictors` | Hold-out time split | MAE/MAPE, PICP, interval width, C-index, Brier |
| `behavior` | truth labels | per-kind P/R/F1 |
| `rules` | YAML frame fixtures | exact alert sequence match |
| `maintenance_alerts` (rev 2) | Generated fault modes with truth onset/failure | detection rate, median lead time, lead time ≥ parts lead time %, false alarms / 100 h, ETA PICP |
| `start_time` (rev 2) | Backtest tasks + generator oracle | counterfactual regret, minutes saved vs. usual and vs. planned start, constraint violations (= 0), duration PICP at recommended start |
| `estimates` (rev 2) | Hold-out maintenance records + tasks | repair hours/cost MAPE + PICP, energy-per-task MAPE, can-finish accuracy |
| `llm_explanations` (rev 2) | Evidence → explanation pairs | numeric-hallucination rate (= 0), faithfulness (Groq `eval_judge`, a different model family), template-fallback rate |
| `llm_ops` (rev 2) | Live nightly run on Groq | p50/p95 latency per task, 429 rate, fallback rate, tokens/day vs. quota |

- **Drift monitoring (P2):** PSI on key features by week; the soil/climate mix is shifted in a generated "future" slice to demo drift detection.
- **Shadow mode:** new model versions log predictions next to the served ones, compared in the dashboard.

---

## 14. Frontend architecture (server-driven)

- **Boot:**
  1. `GET /api/bootstrap` → install theme tokens as CSS variables, load the i18n bundle into i18next, build the router from `nav` for the user's role, and configure the WS URL and refresh intervals.
  2. Nothing renders before the bootstrap resolves. A minimal neutral skeleton shows until then; its strings come from a tiny `index.html` fallback provided by the server.
- **Layout engine:** `LayoutRenderer` fetches the layout for (screen, device, machine_class) and places widgets on a CSS grid. The template comes from the config, and the spacing from theme tokens.
- **Widget registry:** `{ Gauge, AlertStack, CopilotBanner, StabilityDial, ProximityRadar, Twin3D, GradeProfile, TaskTimeline, TaskCard, PacingGauge, EnergyCard, HealthList, ChatPanel, VideoPlayer, Quiz, SlotCalendar, SimViewport, IncidentPlayback, MapView, ComplianceBoard, AnomalyBoard, Gantt, KpiTile, DataTable, FormView }`.
  - Rev 2 adds `MaintenanceAlertCard`, `SensorForecastChart` (sparkline + forecast cone + tier lines), `ServiceCountdown`, `ReadinessBadge`, `StartTimeCurve` (duration-vs-start band with constraint shading), `PreconditionChecklist`, `FactorBars`, `MaintenanceCalendar`, `AvailabilityChart` and `LlmStatusTile`. Each is driven by API data and layout config like the rest.
  - Each widget declares a props schema (zod), and props are validated at runtime.
  - An unknown widget type renders a dev-only error tile.
- **Binding resolver:** `bind: "state.hydraulic.pump_pressure"` subscribes to that path in the Zustand live store (fed by WS diffs). `*_ref` resolves against the cached manifest/app config.
- **Units:** values arrive in SI. The `units` bootstrap defines the display unit per quantity and locale, with precision; `formatValue(quantity, value)` is the only formatter.
- **Alert styling:** tier → theme token (`alert.warning.bg`, etc.). Sound and flash cadence also come from theme.
- **Device profiles:**
  - `cab`: large targets (min target size token), dark theme default, glove-friendly, physical-dial support via keyboard events mapped in config;
  - `mobile`;
  - `desk` (supervisor).
- **Offline:** PWA caches the bootstrap + last layout. If the WS drops, the banner shows a localised "Connection lost — edge safety still active" (the edge runs alerts locally in a real deployment).
- **Accessibility:** colour is never the only signal (icons + text + tier label), there are TTS options, and high-contrast is a theme variant.
- **Testing:** Vitest for the resolver/formatters, Playwright for the demo flow against the running backend with a scenario. No UI mocks.

---

## 15. Tooling, testing and CI

- **Pre-commit:** ruff (lint + format), mypy (strict on `domain`, `safety`, `twin`), eslint, prettier, `check_hardcoding.py`, YAML schema validation (`tp validate-config`).
- **Tests:**
  - unit (twin math, rules, detectors, calibration);
  - property-based (Hypothesis: stability monotonic in reach; narrator validator never passes unmatched numbers);
  - rule fixtures;
  - integration (scenario → expected alerts/advisories/events);
  - API contract (schemathesis on OpenAPI);
  - E2E (Playwright).
- **GitHub Actions:** lint → unit → config validate → small-scale datagen (`--scale tiny`) → train tiny → evals (thresholds enforced) → E2E on compose.
  - LLM calls in CI replay recorded cassettes.
  - `GROQ_API_KEY` is a repository secret, used only by the nightly live-eval workflow.
  - `tp llm-check` runs on startup and in the nightly job to catch retired model IDs early.
- **Secrets:** `GROQ_API_KEY` only in `.env` (gitignored) or CI secrets. It is never sent to the frontend; all LLM calls are server-side.
- **Make it runnable on the team's Windows laptops:** everything goes through `uv run tp …` and `docker compose`. Ollama is native on Windows; GPU is optional. Model sizes are in config, with a `cpu` profile using smaller models.

---

## 16. Build plan

The build runs in **four phases**, ordered by dependency. Each phase has sub-phases (A/B) that can run in parallel across workstreams (§17) once the phase's shared contracts exist. Durations assume a 3–5 person team and are relative, so adjust them to the hackathon calendar. Each sub-phase ends in a **checkpoint**, and each phase ends in a demoable **phase exit**.

| Phase | Name | Share | Sub-phases | Priority focus |
|---|---|---|---|---|
| 1 | Foundations & Data | ≈25% | 1A Platform foundations · 1B Synthetic data & knowledge | Enablers for everything |
| 2 | Live Safety Core & Operator Day | ≈35% | 2A Live safety core · 2B Operator day, analytics, maintenance & estimation core | P0 |
| 3 | AI Copilot, Training, Maintenance & Energy | ≈30% | 3A AI Copilot (Groq) · 3B Training, maintenance, energy & advanced planning | P0/P1 |
| 4 | Supervisor, Evals & Demo Hardening | ≈10% | single phase | P1 + polish |

---

### Phase 1: Foundations & Data (≈25%)

**Goal:** a running platform shell where everything is config-driven, the Groq gateway works, and 180 days of coherent synthetic data plus the knowledge corpus are loaded.

#### 1A. Platform foundations

- [ ] Convert to a uv workspace, rename the package to `terrapilot`, add the Typer CLI skeleton.
- [ ] `docker-compose.yml`: postgres+timescale, redis, qdrant, ollama.
- [ ] `core/config`: YAML loader, Pydantic schemas, `ref:` resolution, `tp validate-config`.
- [ ] Domain models (`MachineState`, `Alert`, `Advisory`, `Task`…) + OpenAPI → TS type generation.
- [ ] FastAPI skeleton with `/api/bootstrap`, `/api/ui/layout`, auth (JWT, roles).
- [ ] React shell: bootstrap loader, theme adapter, i18n adapter, router from nav, layout engine, widget registry, WS client.
- [ ] ESLint hardcoding rules + `check_hardcoding.py` in pre-commit and CI.
- [ ] **LLM gateway skeleton (rev 2):** `config/llm.yaml`, `GroqProvider` + `TemplateProvider`, `tp llm-check`, rate limiter, `llm_calls` logging, cassette test harness.

**Checkpoint 1A:** the app boots, a login screen is rendered entirely from config, and an empty cockpit layout renders from YAML.

#### 1B. Synthetic data and knowledge

- [ ] Datagen: world, weather, ground, fleet, people, tasks, cycles (causal model), behaviour, degradation, fluid samples, faults, incidents, energy, training records.
- [ ] Truth tables + `tp validate-data` learnability gate.
- [ ] Alembic migrations, loaders, read-only views + `tp_ro` role.
- [ ] Manual outlines → LLM expansion → human review; fault catalogue; parts; quiz bank; media manifest.
- [ ] Scenario YAMLs (trench-pedestrian, seatbelt, idle, slope, wind, utility, electric-charging, **maintenance-alert**, **start-time**).
- [ ] **Rev 2 data:** maintenance sensor channels + injected fault modes + `truth_fault_modes`; weather/ground/truck forecasts with lead-time error; start-time variation + `task_start_context`; technician slots; repair durations/costs; `simulate_task` oracle.
- [ ] Manual/quiz/cab-note content generated via Groq Batch API (`tp content`) → review queue.

**Checkpoint 1B:** `tp gen && tp load` produces 180 days of coherent data, and the notebook shows the expected effects.

**Phase 1 exit:** the config-driven shell boots against a loaded database. `tp llm-check` passes against Groq. `tp validate-config` and `tp validate-data` are green in CI. The hardcoding lint gate is active.

---

### Phase 2: Live Safety Core & Operator Day (≈35%), P0

**Goal:** everything the problem statement scores as P0, running live: the safety engine, the daily task dashboard with ETC, behaviour/idle detection, plus the rev-2 maintenance-alert and start-time cores.

#### 2A. Live safety core

- [ ] Simulator + scenario player + Redis publishing.
- [ ] Twin: forward kinematics, design-surface grade deviation, stability margin + sensitivity, geofence distances, proximity tracks + TTC.
- [ ] Rules engine (simpleeval, for_s, hysteresis, escalation) + rule fixtures.
- [ ] Seatbelt, proximity, utility, stability and condition rules.
- [ ] Black box + auto incidents + playback API.
- [ ] WS gateway; cockpit widgets: AlertStack, StabilityDial, Gauge, ProximityRadar, GradeProfile, Twin3D (basic).

**Checkpoint 2A:** the trench-pedestrian scenario plays end-to-end with correct tiered alerts on the cab display.

#### 2B. Operator day, analytics, maintenance and estimation core

- [ ] `/api/me/shift`, task timeline, pacing gauge, walkaround (server form + photos), cab notes (STT).
- [ ] `task_duration` model + CQR + SHAP; live ETC; backward scheduling.
- [ ] Idle + unsafe-pattern detectors, Isolation Forest, cost attribution, scorecard.
- [ ] Manual incident/near-miss form + supervisor incident workflow.
- [ ] **Rev 2, maintenance core:** sensor baselines + residuals, limit/rate layers (A, B), time-to-threshold forecaster (C), service counters (F), fault-code merge (H), alert fusion + lifecycle + routing, maintenance alert card + sensor forecast chart, work order from alert.
- [ ] **Rev 2, estimation core:** energy per task + can-finish + recharge/refuel time; readiness score; `usual_duration` kNN; start-time optimiser (single task) + StartTimeCurve UI + accept flow; service-due countdowns.

**Checkpoint 2B:** the operator sees today's tasks with calibrated ETC and factors. The idle scenario logs a costed event. The maintenance scenario raises one merged, forecast-backed alert. Each task shows a "Best start" with preconditions and savings vs. usual.

**Phase 2 exit:** the operator flow works end to end, entirely from backend data and config, with no LLM required:

- login → walkaround → today's tasks (ETC, best start, energy badge) → live cockpit (seatbelt, proximity, utility, stability, conditions, idle) → incident capture/playback;
- maintenance alerts from sensor values.

---

### Phase 3: AI Copilot, Training, Maintenance & Energy (≈30%), P0/P1

**Goal:** the intelligent layer on Groq, plus the remaining problem-statement features (training hub) and the advanced maintenance, energy and planning features.

#### 3A. AI Copilot (Groq)

- [ ] Live copilot generators, arbiter, templates, narrator + validator, TTS.
- [ ] Knowledge indexing (structure-aware chunks, Qdrant hybrid), rag/fault/sql/twin/predict tools.
- [ ] LangGraph Ask mode with citations, confidence, trace panel, bounded fallback.
- [ ] NeMo topical rails + runtime enforcement engine + guard_events.
- [ ] **Rev 2:**
  - all LLM tasks on Groq via the gateway (narration, router, answer, SQL, STT);
  - Llama Guard 4 + Prompt Guard 2 in input/output guards;
  - `maint_explainer` + `plan_explainer` with numeric validation;
  - `maint_tool` + `plan_tool` in Ask mode;
  - `maintenance` / `plan` / `energy` live-copilot generators.

**Checkpoint 3A:** the live banner narrates scenario events. The chat answers manual/telemetry questions with citations and refuses unanswerable and override requests.

#### 3B. Training, maintenance, energy and advanced planning

- [ ] Training hub: modules, video player, quizzes, instructor slots + booking, adaptive assignment, cert gating wired to onboarding.
- [ ] Maintenance: health index, Cox risk index, RUL, fault lookup, service/part request, fluid samples chart.
- [ ] VLM troubleshooting with closed label set + escalation.
- [ ] Battery model + MILP charge plan + gantt; power-mode recommendation.
- [ ] Fatigue (webcam EAR/PERCLOS) + WBV A(8).
- [ ] P2P proximity.
- [ ] **Rev 2:**
  - VLM on Groq (Llama 4 Scout, self-consistency);
  - signature (D), peer-drift (E) and fluid-sample (G) alert layers;
  - repair duration/cost estimates;
  - maintenance-window planner with bundling;
  - day-plan MILP with slot-dependent durations;
  - weather-window finder;
  - machine selection;
  - task wear/cost estimate;
  - 7-day availability forecast.

**Checkpoint 3B:** every problem-statement bullet and every rev-2 addition can be demoed.

**Phase 3 exit:** the full feature set is demoable:

- the copilot narrates and answers via Groq, with guardrails and template/Ollama fallbacks;
- the training hub (videos, quizzes, booking, adaptive assignment, cert gating);
- VLM troubleshooting;
- the battery MILP;
- fatigue/WBV and P2P;
- advanced maintenance layers;
- maintenance windows, the day plan and every estimation feature.

---

### Phase 4: Supervisor, Evals & Demo Hardening (≈10%)

**Goal:** the supervisor and technician views, measured quality, and a demo that cannot fail.

- [ ] Supervisor fleet map, compliance boards, anomaly board, planner what-if, escalation inbox.
- [ ] Evals dashboard (all suites, including rev-2 `maintenance_alerts`, `start_time`, `estimates`, `llm_explanations`, `llm_ops`) + CI thresholds.
- [ ] Supervisor rev-2 views: maintenance board + calendar, day-plan gantt, availability chart, LLM status tile.
- [ ] Rate-limit rehearsal: run the full demo twice back-to-back on the Groq tier we'll use and confirm there's no 429-driven degradation (otherwise raise the tier or tighten caching).
- [ ] Browser simulator drills (P1), manifest swap to the wheel loader in the demo.
- [ ] Hindi (or a second locale) i18n bundle, to prove there is no hardcoded text.
- [ ] Demo hardening: `tp demo` one-shot, fallback recordings, rehearsal.

**Phase 4 exit:**
- The demo script (§18) runs end to end twice in a row, online (Groq) and offline (`tp demo --offline`).
- All eval suites meet their `config/models.yaml` / CI thresholds.
- The second locale and the wheel-loader manifest swap work with zero code changes.

### Cut line if time runs short (in order)

Drop VR → LSTM RUL → slip estimator → multivariate anomaly alert layer (I) → surface CNN (use simulated class) → availability forecast → machine selection → P2P → day-plan MILP (keep the single-task start optimiser) → browser simulator (keep drills as video + quiz) → VLM (keep structured fault lookup).
**Never cut:** the rules engine, seatbelt, proximity, incident logging, tasks + ETC, idle detection, training videos + booking, the copilot's template path, **sensor maintenance alerts (layers A, B, C, F)**, **single-task start-time recommendation**, **energy can-finish estimate**, or the **Groq gateway with fallbacks**.

---

## 17. Team workstreams

| Workstream | Owns | Interfaces |
|---|---|---|
| **WS1: Platform & Data** | uv workspace, config system, DB, datagen, loaders, docker, CI | Provides schemas + data to everyone |
| **WS2: Live Safety Engine** | sim, twin math, rules engine, black box, detectors, WS gateway | Consumes manifests; emits alerts/events |
| **WS3: ML & Analytics** | ETC, anomaly ML, RUL/risk, fatigue, MILP, calibration, explainability; **rev 2:** sensor baselines/forecasters, maintenance alert fusion, start-time optimiser, energy/repair/cost estimates, readiness, maintenance-window planner | Model server API used by the copilot + UI |
| **WS4: AI Copilot & Guardrails** | live narrator, Ask-mode graph, RAG/SQL tools, VLM, guardrails, evals; **rev 2:** Groq LLM gateway, prompt registry, Llama Guard/Prompt Guard, explainers, Batch content jobs | Consumes state/predictions; exposes chat + advisories |
| **WS5: Frontend** | runtime (layout/registry/binding), widgets, cab/mobile/supervisor screens, 3D twin, simulator | Consumes bootstrap/layout/APIs only |

With 3 people: merge WS1+WS2 and WS3+WS4. Contract-first: freeze `domain/` models and the WS message schema at Checkpoint 1A (end of Phase 1A).

| Workstream | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| WS1 Platform & Data | 1A config/DB/docker/CI, 1B datagen + loaders + scenarios | data fixes, read-only views | content review queue, index refresh | demo `tp demo`, offline profile |
| WS2 Live Safety Engine | 1A domain models, WS contract | 2A sim, twin, rules, black box; 2B detectors | P2P, fatigue/WBV | scenario rehearsal, latency checks |
| WS3 ML & Analytics | 1B learnability gate | 2B ETC, anomaly ML, sensor forecasters, alert fusion, start-time optimiser, energy/readiness | 3B RUL/risk, repair estimates, maintenance windows, day-plan MILP, availability | eval thresholds, backtests |
| WS4 AI Copilot & Guardrails | 1A Groq gateway skeleton, 1B Groq Batch content | 2B STT for cab notes | 3A live narrator, Ask mode, guardrails, explainers; 3B VLM | guardrail/LLM evals, rate-limit rehearsal |
| WS5 Frontend | 1A runtime shell, registry, adapters | 2A cockpit widgets, 2B dashboard, maintenance + start-time widgets | 3A chat/trace panel, 3B training hub, simulator, energy gantt | supervisor/technician views, second locale, polish |

---

## 18. Demo script (≈7 minutes)

1. **Login + QR** (30 s): operator scans EX-03. The layout configures itself, and a cert check shows one module expiring in 5 days (auto-assigned).
2. **Walkaround** (30 s): three taps + one photo of a "leaking hose" → issue logged.
3. **Today dashboard** (45 s): three tasks, ETC bands, "Rain +11 min, clay +7 min". The pacing gauge is on track.
   - **3b. Best start time (rev 2, 45 s):** open the trench task on the electric excavator.
     - The StartTimeCurve shows "Start now: 3 h 05 m (with mid-task charge stop)" vs. "Recommended 09:45: 2 h 38 m, 22 min faster than usual".
     - Factors: ground draining, full charge, cooler hours.
     - Preconditions: charge to 85% during the toolbox talk, filter ΔP check.
     - Accept → the charger is reserved.
     - The energy badge flips to "Enough for this task".
4. **Cockpit live scenario** (2.5 min):
   - belt unfastened → caution → warning;
   - grade advisory narrated;
   - pedestrian with no vest approaching → TTC caution + PPE flag;
   - utility hold;
   - wind gust advisory;
   - cavitation advisory;
   - truck late → idle advisory with cost.
5. **Incident** (30 s): G-spike → auto black box → playback in the 3D twin.
6. **Ask mode** (45 s):
   - "Why is hydraulic oil hot?" → cited manual answer + live temp;
   - "How much did I idle this week?" → SQL result;
   - "Turn off the proximity alarm" → refused, with the reason;
   - an unanswerable question → "not in the manual".
7. **Maintenance + VLM** (30 s): photo of worn teeth → label + manual page + Request Part.
   - **7b. Sensor maintenance alert (rev 2, 45 s):** play `demo_maintenance_alert`.
     - Coolant residual trend → forecast "service_soon in ~9 h (p10 5 h)" → radiator-clogging signature. All merge into one alert.
     - A Groq explanation cites the manual.
     - The cab gets a declutter-respecting advisory.
     - The technician inbox shows the suggested maintenance window, bundled with the 250 h service due in 14 h, plus repair estimate and cost.
     - One tap creates the work order.
8. **Training** (30 s): cavitation events auto-assigned a stick-control drill; book an instructor slot; start the video.
9. **Supervisor + manifest swap** (30 s):
   - the compliance board and anomaly board;
   - the charge-plan gantt for the electric excavator;
   - scan the wheel loader: a different layout, rules and manual scope, with no code change;
   - switch the locale to prove every string is config.
10. **Evals slide** (15 s): PICP, bounded-knowledge accuracy, zero numeric hallucinations, guardrail block rate, **maintenance lead time vs. parts lead time**, **start-time regret and minutes saved vs. usual**, **Groq p95 latency and fallback rate**.

Backup: a recorded video of the full run, plus the `tp demo --offline` profile (Ollama/templates, no internet).

Total runtime grows to ≈9 minutes with the rev-2 steps. If the slot is 7 minutes, shorten steps 2 and 8.

---

## 19. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Local LLM too slow on laptops | Template-first design; the narrator only does the advisory tier; `cpu` model profile; hosted provider swap via config. **Rev 2:** Groq is now primary, so local LLMs are only the offline fallback |
| Groq rate limits (429) during the demo | Per-model token buckets + header-driven backoff, priority lanes, Redis caching, the narrator never retries (template fallback), rate-limit rehearsal, an upgraded tier for demo day if needed |
| Groq model retired/renamed | Model IDs only in `config/llm.yaml`; `tp llm-check` at startup + nightly; fallback chain per task |
| Internet outage at venue | `TP_PROFILE=offline` → Ollama + templates; safety, alerts, forecasting and the optimiser need no LLM |
| Sensitive data sent to the cloud | Gateway redaction/pseudonymisation, `never_send` list (driver camera stays on edge), structured facts instead of raw logs, all calls audited in `llm_calls` |
| LLM explanation contradicts the deterministic decision | Decision-authority guard (§13.1); numeric validation; explanation built only from evidence JSON |
| Maintenance alert fatigue (too many alerts) | Per-component fusion/dedupe, tier promotion only on multi-layer agreement, declutter routing, false-alarm feedback loop, false alarms / 100 h tracked as an eval |
| Start-time recommendations unrealistic or naggy | Hard constraints, minimum-saving threshold, forecast-uncertainty penalty, oracle-based regret eval, and the supervisor/operator always chooses |
| Synthetic data looks fake or unlearnable | Causal generator + learnability gate + injected real-world patterns (weather seasonality, operator heterogeneity) |
| VLM wrong or overconfident | Closed label set, self-consistency confidence, catalogue-owned safe-to-continue flag, escalation |
| Text-to-SQL unsafe | Read-only role, views only, sqlglot allowlist, LIMIT/timeout, truth tables unreachable |
| Hardcoding creeps into the UI under time pressure | Lint + CI gate from day one; the widget props schema rejects literals |
| Scope explosion | Priority tags + a cut line (§16); P0 is the problem-statement coverage |
| Demo-day network/GPU failure | Offline profile, recorded fallback, all assets local |
| Physics of stability questioned by judges | Documented static model, unit-tested, framed as advisory with conservative margins from config |
| Branding/IP | Neutral product name and generic terminology; licences tracked for videos/photos in `config/media.yaml` |
