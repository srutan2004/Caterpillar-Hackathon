# TerraPilot

Intelligent operator companion for heavy equipment (excavator, wheel loader, articulated dump truck).
"TerraPilot" is a placeholder name set in `config/app.yaml`; it appears nowhere in code.

The full design is in [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md). **Phase 1 (Foundations & Data) is implemented.**

## Quick start (Windows, macOS, Linux)

Prerequisites: [uv](https://docs.astral.sh/uv/), Docker Desktop, Node.js 20+.

```bash
cp .env.example .env              # then set GROQ_API_KEY (the only external key Phase 1 needs)
uv sync                           # Python 3.12 workspace (backend/)
docker compose up -d              # Postgres 16 + TimescaleDB, Redis, Qdrant  (Ollama: --profile offline)

uv run tp validate-config         # every YAML under config/ → schema + cross-file references
uv run tp gen                     # synthetic world: 180 days, 3 sites, 14 machines (~3.3M rows, ~40 s)
uv run tp validate-data           # integrity checks + learnability gate
uv run tp load                    # migrations → Timescale hypertables, read-only views, tp_ro role → COPY (~45 s)
uv run tp llm-check               # verifies GROQ_API_KEY, every configured model ID, rate-limit headroom

uv run tp api --reload            # FastAPI on :8000 (reloads on code AND config changes)
cd apps/web && npm install && npm run dev   # React shell on :5173 (apps/web/.env: VITE_API_BASE_URL)
```

Sign in with any generated user and the demo PIN from `config/datagen/operators.yaml`, e.g. operator **op_017**,
supervisor **sup_metro**, admin **admin_01**. Faster data for development: `uv run tp gen --scale tiny` (or `small`).

## What Phase 1 delivers

| Plan item (§16) | Where |
|---|---|
| uv workspace, `terrapilot` package, Typer CLI (`tp …`) | `pyproject.toml`, `backend/`, `backend/terrapilot/cli.py` |
| Docker Compose: Postgres+Timescale, Redis, Qdrant, Ollama | `docker-compose.yml` |
| Config system: YAML → Pydantic → `ref:` resolution → cross-file checks; refuses to start on errors | `backend/terrapilot/core/config*.py`, `config/` |
| Domain models + WS contract → OpenAPI → TypeScript | `backend/terrapilot/domain/`, `apps/web/src/api/schema.d.ts` (`tp openapi` + `npm run gen:api`) |
| FastAPI: `/api/bootstrap`, `/api/ui/layout`, `/api/ui/forms/*`, JWT auth + roles, machine select + cert gating, WS skeleton | `backend/terrapilot/api/` |
| React shell: bootstrap loader, theme + i18n adapters, router from nav, layout engine, widget registry, WS client | `apps/web/src/` |
| Hardcoding gate: ESLint (`no-magic-numbers`, `jsx-no-literals`, colour/URL bans) + `check_hardcoding.py` | `apps/web/eslint.config.js`, `scripts/`, `.pre-commit-config.yaml`, CI |
| LLM gateway: `config/llm.yaml`, Groq + template (+ Ollama) providers, task router, JSON-schema validation + one repair, rate limiter from `x-ratelimit-*`, circuit breaker, cache, redaction, `llm_calls` accounting, cassettes | `backend/terrapilot/llm/` |
| Synthetic data: world, weather (+ forecasts), ground, fleet, people, tasks, causal cycle model, behaviour, degradation, maintenance sensors + injected fault modes, fluids, faults, incidents, energy, training | `backend/terrapilot/datagen/`, `config/datagen/` |
| Truth tables + learnability gate | `truth_*` tables, `tp validate-data`, `config/models.yaml → learnability` |
| Alembic migrations, loader, read-only views + `tp_ro` role | `backend/terrapilot/db/` |
| Start-time oracle (`simulate_task`) | `backend/terrapilot/datagen/oracle.py` |
| Manual outlines → Groq Batch API → human review queue; fault catalogue; parts; quiz bank; media manifest | `tp content`, `tp content-status`, `tp review`, `config/maintenance/`, `config/media.yaml` |
| Scenario YAMLs (all 9) | `config/scenarios/` |
| Effects notebook | `notebooks/01_data_effects.ipynb` (`uv sync --group notebook`) |

### Checkpoints

* **1A** — the app boots; the login screen and an empty cockpit are rendered entirely from config
  (verified end to end in a browser: login → machine list → cert gating → cockpit, cab/desk themes).
* **1B** — `tp gen && tp load` produces 180 days of coherent data; the notebook and `tp validate-data`
  show the configured effects (rain, wet clay, heat, experience, machine health, idling, seatbelt habits, sensor drift).
* **Phase exit** — `tp validate-config` and `tp validate-data` are green; the hardcoding gate is active in
  pre-commit and CI. **`tp llm-check` needs your `GROQ_API_KEY`** (see below).

## Needs your Groq API key

Add `GROQ_API_KEY=` to `.env`, then:

```bash
uv run tp llm-check                                   # verify models + rate limits on your account tier
uv run tp content --task manuals --mode batch         # manual sections via the Batch API (or --mode sync / dry-run)
uv run tp content-status                              # pull finished batches into data/review_queue/
uv run tp review list | show <id> | approve <id|all> | reject <id>
uv run tp content --task quizzes --mode batch         # quiz bank grounded in the approved manual chunks
uv run tp content --task notes --mode sync            # cab-note paraphrases
uv run tp gen                                         # re-run to pick up approved quizzes / paraphrases
```

Nothing generated reaches `knowledge/` without review. Without a key, every narrating LLM task falls back to its
i18n template (`llm_template.*`), so the app still works.

## Development

```bash
uv run pytest                     # 43 tests (config, gateway, API on SQLite, datagen determinism, oracle, Postgres load)
uv run ruff check backend scripts && uv run ruff format --check backend scripts
uv run mypy                       # strict on domain/safety/twin
cd apps/web && npm run lint && npm run typecheck && npm test && npm run build
uv run python scripts/check_hardcoding.py
uv run pre-commit install
```

The Postgres integration test uses a separate `terrapilot_test` database and is skipped if no server is reachable.
