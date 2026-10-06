# Friction Log

Challenges hit while building MatchLens: what happened, what it cost, and how it was handled. Newest first.

## F-015 · 2026-10-05 · Metric unit contract gap

**The M1 metric unit enum omitted two units required by M2**

- **What happened:** The M1 `MetricSnapshot` contract only allowed blank, percent, speed, distance, xG and index, but the M2 metric table specifies `count` for goals/passes/sprints and `ratio` for PPDA.
- **Impact:** Valid M2 snapshots could not pass the Pydantic contract or generated JSON Schema.
- **Resolution:** Added `count` and `ratio` to `MetricUnit`, regenerated `docs/schemas/MetricSnapshot.schema.json`, and reran the schema drift test.
- **Status:** Resolved

## F-014 · 2026-10-04 · Pyright `extraPaths`

**Adding `extraPaths` broke resolution of the project's own package**

- **What happened:** Setting `extraPaths = ["tests"]` (so tests can import a shared `support` module) replaced pyright's automatic `src` search path. Every `matchlens` import then resolved to the installed package without `py.typed`: 162 "Stub file not found" errors.
- **Impact:** Type checking failed across all tests.
- **Resolution:** `extraPaths = ["src", "tests"]`.
- **Status:** Resolved

## F-013 · 2026-10-04 · Coverage and performance tests

**Coverage tracing made the 5-second generation test fail**

- **What happened:** A full match with tracking takes ~1.7–2 s, but under `pytest --cov` (branch coverage) it took 5.8 s and the spec's "under 5 s" test failed. The full suite went from ~5 s to ~85 s.
- **Impact:** A performance assertion inside a traced process measures the tracer, not the code.
- **Resolution:** `matchlens sim` now reports its generation time; the test runs it in a subprocess (not traced) and reads the number. Slow simulation tests carry a `slow` marker: CI runs everything, `make backend-test-fast` skips them (9 s).
- **Status:** Resolved

## F-012 · 2026-10-04 · Simulator calibration

**Realism targets pull against each other**

- **What happened:** Calibrating the simulator against the spec's targets (passes, accuracy, shots, goals, fouls, yellows, possession) took ten measured rounds. Raising fouls to 15–30 produced 1.4 penalties a match, which inflated xG to 0.17 a shot; direct teams scored 4–5 goals because strikers waited in the box ahead of the ball; tightening defence then dropped scoring to 1.4.
- **Impact:** A single global constant change moved several stats at once, and one pairing could pass while others failed.
- **Resolution:** A scratch calibration script over 20–50 seeds and all 12 club pairings, and fixes that model real football instead of tuning the symptom: fewer fouls inside the box (all of them penalties), more careful booked players, an offside line capping attackers' depth, denser defending in the final third, and shot choice weighted by xG^0.85. The balanced pairing now sits mid-range on every target.
- **Status:** Resolved

## F-011 · 2026-10-04 · Pydantic JSON Schema → TypeScript

**Default Pydantic schemas generate poor TypeScript**

- **What happened:** Running `json-schema-to-typescript` on the exported schemas gave `type?: "pass"` (optional, although it's always serialized), aliases like `EventId1 = string` for every field title, and a duplicate `NoAttrs1` interface wherever a `$ref` had a sibling `default`.
- **Impact:** The frontend's generated types would have been loose and noisy.
- **Resolution:** `json_schema_serialization_defaults_required=True` on the base contract, and the exporter strips field titles and defaults (model titles stay). All 11 schemas now generate clean types.
- **Status:** Resolved

## F-010 · 2026-10-04 · Pyright strict / Pydantic

**Pyright strict rejects frozen Pydantic subclasses and narrowed fields**

- **What happened:** With `frozen=True` as a class keyword on the base contract, pyright flagged every subclass ("A non-frozen class cannot inherit from a class that is frozen"); with `frozen` in `model_config`, it flagged every event subclass that narrowed a base field (`outcome: str | None` → `Literal[...]`) as an incompatible override of a mutable attribute. 149 errors in total.
- **Impact:** The first event design (a base with every field, subclasses narrowing types) couldn't pass strict type checking without ignores.
- **Resolution:** `frozen` stays in `model_config` (immutable at runtime). The base event holds only the shared fields; each event class declares all of its own fields, so nothing is overridden.
- **Status:** Resolved

## F-009 · 2026-10-04 · Dependabot / TypeScript

**Dependabot proposed TypeScript 7, which typescript-eslint can't use yet**

- **What happened:** The first grouped Dependabot PR bumped `typescript` 6.0.3 → 7.0.2 and `@types/node` 24 → 26. TypeScript 7 is the Go-native compiler and only exposes `unstable/*` APIs; `typescript-eslint` 8.71 requires `typescript >=4.8.4 <6.1.0`. Node 26 typings don't match the Node 22 runtime.
- **Impact:** Merging would have broken frontend linting and allowed Node APIs that don't exist at runtime.
- **Resolution:** Dependabot ignores major updates for `typescript` and `@types/node`; the PR is closed. Revisit TypeScript 7 when typescript-eslint supports it.
- **Status:** Resolved

## F-008 · 2026-10-04 · GitHub Actions

**`astral-sh/setup-uv@v10` doesn't exist**

- **What happened:** The first CI run failed in "Prepare all required actions": `Unable to resolve action astral-sh/setup-uv@v10`. Since v8.0.0 (its first immutable release), setup-uv no longer publishes major or minor tags, only exact ones like `v10.2.0`, as a defence against tj-actions-style tag hijacking. The local container check couldn't catch this because it ran the Make targets, not the workflow.
- **Impact:** The Backend job never started; M0 couldn't be tagged.
- **Resolution:** Every action is pinned to a full commit SHA with a version comment (`@c18668a… # v10.2.0`); Dependabot updates both. The workflow also passes `actionlint`.
- **Status:** Resolved

## F-007 · 2026-10-01 · GitHub

**No secret scanning on a private repository**

- **What happened:** The repo stays private until submission. GitHub Pro (Student Developer Pack) covers branch protection, rulesets and 3,000 Actions minutes a month for private repos, but not push-protection secret scanning.
- **Impact:** Any secret committed now becomes public when the repo is made public.
- **Resolution:** gitleaks as a pre-commit hook on staged changes and as a CI job over the full history, both tested with a planted token. A `main` ruleset will require the CI checks once pushed.
- **Status:** Resolved

## F-006 · 2026-10-01 · Spec

**Spec's M0 commit order doesn't build at every commit**

- **What happened:** Config tests read `.env.example` and CI calls Make targets, but the spec adds both files in a later commit than the code that needs them.
- **Impact:** Commits 1 and 2 would fail on their own, breaking the "every checkpoint builds" rule.
- **Resolution:** Regrouped: `.env.example` moved into commit 1, the Makefile into commit 2.
- **Status:** Resolved

## F-005 · 2026-10-01 · Ruff

**ruff-pre-commit 0.16 formats Python code blocks inside Markdown**

- **What happened:** In a clean-clone check, the `ruff-format` hook reformatted `SPEC.md`: 83 insertions and 40 deletions across the Python snippets. Running `ruff format` directly changed nothing; only the hook targets Markdown.
- **Impact:** Every commit that touched docs would have silently rewritten them.
- **Resolution:** Limited both ruff hooks to `types_or: [python, pyi]`.
- **Status:** Resolved

## F-004 · 2026-10-01 · Windows / line endings

**CRLF from Python on Windows breaks formatting parity with Linux CI**

- **What happened:** A file written with `Path.write_text` on Windows got CRLF endings. Local ruff accepted it (line endings auto-detected); ruff on Linux reformatted it.
- **Impact:** Green locally, red in CI.
- **Resolution:** `.gitattributes` with `eol=lf`, `.editorconfig`, and ruff `line-ending = "lf"`.
- **Status:** Resolved

## F-003 · 2026-10-01 · Verification

**Piping test output through `tail` hid failing exit codes**

- **What happened:** The first container run of `make lint | tail` looked green, but the pipeline's exit code was `tail`'s.
- **Impact:** A failing step could have passed unnoticed.
- **Resolution:** Re-ran with `set -o pipefail` and per-step logs.
- **Status:** Resolved

## F-002 · 2026-10-01 · Pyright / pydantic-settings

**Pyright strict rejects `Settings(_env_file=None)`**

- **What happened:** pydantic-settings accepts `_env_file` at runtime, but pyright strict reports `No parameter named "_env_file"`.
- **Impact:** Tests would need a `pyright: ignore`.
- **Resolution:** Tests use small `Settings` subclasses that override `model_config`.
- **Status:** Resolved

## F-001 · 2026-10-01 · Local toolchain

**No uv, no make, wrong default Python on Windows**

- **What happened:** The machine had Python 3.14 and 3.11 but not 3.12, and neither `uv` nor GNU Make.
- **Impact:** `make setup && make lint && make test` can't be run locally as the spec states.
- **Workaround:** Installed uv with `pip install --user` (not on PATH); uv provisions Python 3.12. The Makefile and CI were checked in a `node:22-bookworm` container, and the README lists direct commands for Windows.
- **Status:** Open (install make and put uv on PATH)
