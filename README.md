# Kellan

Kellan turns a synthetic football event stream into fact-checked, personalized on-screen insights. It gives producers a live story-integrity layer: each insight is grounded in event evidence, checked before publication, and revised when the match facts change.
Code computes every number, agents write every sentence, and a Fact-Checker agent checks that they agree.

**Show me the play behind the words.**

Built for the Microsoft Premier League Hackathon (Inside the Game), Best Multi-Agent System category.
Everything in Kellan is fictional: league, clubs, players and venues are invented.

## Hero feature: Show me why

Every published insight stays in the story shelf after its overlay expires. Select **SHOW ME WHY** to inspect the evidence behind that exact version:

- Select an underlined numeric phrase to compare its saved metric with a fresh computation from historical event and tracking inputs.
- Replay the preceding 20 seconds at 1x in the 3D pitch. Select an event to seek to it; gold marks identify source events, teal marks provide context.
- Switch between published audience and language versions without losing the replay position or evidence reference.
- Inspect the agent decisions, including rejected drafts and verifier errors, while the match continues live.

Evidence is pinned when the insight is generated. Later tracking updates and match events cannot enter its inspection. The short replay provides context; full-match and rolling metrics are recomputed over their actual input window. Numeric verification does not establish tactical causation. Missing input history is reported as unavailable.

The endpoint is `GET /api/matches/{match_id}/insights/{insight_id}/evidence`. Only published insights are available; evidence remains in memory for the lifetime of that match session. See [the judge walkthrough](docs/hero-demo.md) for a short demonstration.

## Shared football simulation

The match engine now advances one shared player-and-ball world in bounded 50 ms steps. Passes, shots, blocks, interceptions and saves are resolved against moving players before their outcome events are emitted. The same world records positions for the 3D view; a separate animation simulation does not decide what happened.

Regular tracking frames are supplemented with kick/contact frames. Near-ball players include compact subsecond position and facing paths. Historical replay uses recorded frame intervals, while orbit, zoom and evidence markings remain available. All movement is synthetic and the football rules and contact model are simplified. See [simulation design and limits](docs/shared-simulation.md).

> **Status:** M1–M7 are complete; M8 Azure deployment is in progress on `m8-azure`. See [docs/CHANGELOG.md](docs/CHANGELOG.md) for progress.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | Python 3.12 package `matchlens`, managed with uv |
| `frontend/` | React + Vite + TypeScript web client |
| `infra/` | Bicep templates for Azure resources |
| `azure.yaml` | Azure Developer CLI services and Docker build settings |
| `docs/azure-deployment.md` | GitHub OIDC setup and Azure deployment instructions |
| `docs/` | Architecture, changelog, eval results, demo script |
| `.github/workflows/` | CI: lint, typecheck, tests, build and dependency audit |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.12+ (installs Python 3.12 automatically)
- Node.js 22 and npm
- GNU Make
- [gitleaks](https://github.com/gitleaks/gitleaks) 8.30+ for `make secrets-scan` (the pre-commit hook builds its own)
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd) for Azure deployment

No cloud account is needed. By default every component runs locally with a mock LLM.

## Quick start

```bash
cp .env.example .env
make setup   # backend and frontend dependencies, pre-commit hooks
make lint    # ruff, pyright, eslint, tsc
make test    # pytest with coverage, vitest
make backend-test-fast   # quick loop: skips the slow simulation tests
```

Run `make help` to list every target.

On Windows without Make, the same steps run directly:

```powershell
uv sync --directory backend --locked
npm --prefix frontend ci
uv run --directory backend pytest --cov
npm --prefix frontend test
```

## Configuration

Settings are read from environment variables or a `.env` file; see [.env.example](.env.example).
Each cloud dependency sits behind an interface with a local default:

| Variable | Local default | Cloud value |
| --- | --- | --- |
| `LLM_MODE` | `mock` (or `off`) | `foundry` |
| `TRANSPORT` | `local` | `eventhubs` |
| `STORE` | `memory` | `cosmos` |

Selecting a cloud mode requires its endpoint settings; startup fails fast if they are missing.

For Foundry mode, install the optional provider, sign in with Azure CLI, and set `LLM_MODE=foundry`, `FOUNDRY_PROJECT_ENDPOINT`, `FAST_MODEL` and `STRONG_MODEL` in `.env`:

```powershell
uv sync --directory backend --locked --extra foundry
az login
```

The Foundry adapter uses the [Microsoft Agent Framework Foundry provider](https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/model-providers/microsoft-foundry). The default mock and off modes do not require Azure credentials or the optional package.

For M4 acceptance, run `uv run --directory backend python scripts/check_m4.py` to check all three scenarios and three seeds in off and mock modes. After configuring Foundry, run `uv run --directory backend python scripts/check_foundry.py` for one live structured-output call and a console span. The local Foundry check requires both model names in `.env`; for this single call, they may refer to the same deployment.

Run `make eval` to evaluate three scenarios at seeds 1, 2 and 3 in mock mode. It writes [docs/eval-results.md](docs/eval-results.md) and `eval/report.json`. On Windows without Make, run `uv run --directory backend matchlens eval --scenarios all --seeds 1,2,3 --llm mock`. Use `--fault-rate 1.0` to exercise injected claim errors, or `--llm foundry` after installing the Foundry extra and configuring the project and model names. Foundry evaluation makes multiple paid model calls. The M5 harness measures completed insight verification; cue delivery latency will be measured after that pipeline exists.

The API starts a console OpenTelemetry exporter. LLM calls and Detector reviews create spans and `AgentTrace` records with a shared trace ID. These spans appear in the API console when the agent workflow runs.

The profile API exposes the seeded viewer profiles at `GET /api/profiles` and an individual profile at `GET /api/profiles/{profile_id}`. The seeds cover analyst English, casual English, casual Spanish, and player focus.

```bash
uv run --directory backend matchlens info   # print the active modes
```

## Simulating a match

The simulator plays a fictional Meridian League fixture from a scenario in [data/scenarios/](data/scenarios/) and writes `metadata.json`, `events.jsonl` and `frames.jsonl` (1 Hz tracking) to `data/samples/<match_id>/`.

```bash
make sim SCENARIO=late_comeback SEED=42
# or: uv run --directory backend matchlens sim --scenario late_comeback --seed 42 [--events-only]
```

| Scenario | Fixture | What happens |
| --- | --- | --- |
| `balanced` | Kestrel Bay Athletic v Ashmoor Rovers | Possession against pressing, nothing scripted |
| `late_comeback` | Vellmont City v Kestrel Bay Athletic | Visitors lead two-nil; hosts press from 60' and score three late |
| `red_card_press` | Port Halden FC v Kestrel Bay Athletic | Away red card at 55'; hosts raise their press from 60' |

The same scenario and seed always produce byte-identical files. `DATA_DIR` overrides where scenarios are read from and samples are written to (default: the repository's `data/`).

## Live match view

Start the local API and frontend in separate terminals:

```powershell
uv run --directory backend uvicorn matchlens.api.app:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

Open the Vite URL shown in the frontend terminal. Choose a scenario and playback speed, then kick off a match. The browser connects to the local API for the live score, tracking view, metrics, event feed and match controls. No Azure resources or LLM credentials are required.

The live pitch opens in a Three.js WebGL stadium with modeled footballers, articulated running animations, textured turf, goal nets, spectator stands, floodlights, and dynamic shadows. Drag or use a touch gesture to orbit, scroll or pinch to zoom, and choose a broadcast, sideline or goal-end camera. **FOLLOW BALL**, **PLAYER NUMBERS**, and **RESET CAMERA** control the view. Use **3D VIEW / 2D VIEW** to switch perspectives; the 2D view also works on devices without WebGL 2.

Players turn towards their movement and look towards the ball, with distance-driven strides, planted supporting feet, knee bends, arm swings and acceleration in the underlying simulation. Synthetic players anticipate their next involvement, move to receive passes, follow carries and react to shots. Passing and shooting poses follow the ball's authored contacts. Tracking is sampled at 1 Hz, with subsecond ball trajectory samples that preserve exact synthetic departures and arrivals. Lofted passes and shots have synthetic height; the UI does not infer it from flat coordinates. Dead balls stay stationary until their restart. Halftime, replay seeks and tracking gaps reset interpolation instead of animating a run across the pitch.

Select **REPLAY LAST 15s** to inspect the last 15 received tracking frames while the match continues live. Replay runs at 1x so pass contacts and player movement remain readable even when the live match is accelerated. Broadcast cues are hidden over replay frames so their live timing cannot be mistaken for replay evidence. All stadium and player assets are generated locally; the 3D engine loads separately from the initial application.

To run the full stack with Docker instead:

```powershell
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). The web container serves the built UI and proxies API and WebSocket requests to the backend. Set `MATCHLENS_WEB_PORT` to use a different host port; the default is `8080`.

## Replaying and computing metrics

Replay a saved match through the local queue and in-memory historical metric store:

```bash
uv run --directory backend matchlens replay ../data/samples/balanced-s42 --speed max
# Supported speeds: 1, 10, 30, 60, max (match-clock multiplier)
```

From `backend/` on Windows, use `.venv/Scripts/python.exe -m matchlens.cli replay ../data/samples/balanced-s42 --speed max`.
The replay command prints snapshot count, score and xG. It merges events and 1 Hz tracking by match clock, with events first on a tied timestamp. The metrics engine emits snapshots only when a value changes and retains sequence history for `get(match_id, metric_id, as_of_seq)`. Rolling possession, PPDA, field tilt and control windows use match time; PPDA is zero when there are no defensive actions in the window.

For Azure adapters, install `uv sync --directory backend --locked --extra azure`, set `TRANSPORT=eventhubs` and/or `STORE=cosmos`, and provide the endpoint settings from `.env.example`. Azure authentication uses `DefaultAzureCredential` (for example, `az login` locally or managed identity in Azure). Replay uses an Event Hubs application property to isolate runs of the same saved match. `pytest -m azure` runs live Event Hubs and Cosmos checks when their endpoint variables and resources are available; default CI skips them.

## Data contracts

Every payload that crosses a boundary (events, tracking frames, metric snapshots, insights, cues, recaps, traces) is a Pydantic model in `backend/src/matchlens/models/`.
The JSON Schemas in [docs/schemas/](docs/schemas/) are generated from those models; the frontend derives its TypeScript types from them.

```bash
make schemas   # or: uv run --directory backend matchlens schemas export --output-dir ../docs/schemas
```

A test fails if the committed schemas drift from the models.
