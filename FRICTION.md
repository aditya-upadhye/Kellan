# Friction Log

Challenges hit while building MatchLens: what happened, what it cost, and how it was handled. Newest first.

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
