# AGENTS.md

## What this repo is

Python anywidget package (`marimo-mmp`) visualizing mmpdb matched-molecular-pair transforms, with a TypeScript frontend bundled by esbuild. Core package does not depend on marimo; notebooks use the `notebook` extra.

- `src/marimo_mmp/` — Python package (`dataset.py`, `widget.py`, `depiction.py`)
- `frontend/` — strict TypeScript + CSS sources; single widget module `transform_graph.ts`
- `notebooks/` — marimo notebooks; run with `uv run marimo edit notebooks/<name>.py`
- `scripts/h1_pipeline.py` — builds `data/processed/h1_ic50.mmpdb` from the ChEMBL web API (network, slow)
- `WIDGET_ARCHITECTURE.md`, `NOTES.md` — architecture reference and data-pipeline methodology

## Commands

Python (uv, 3.11): `uv sync --group dev`, then `uv run ty check`, `uv run pytest`.

JS/TS (Node >= 20): `npm ci` first, then `npm run check` (tsc --noEmit + JS tests).

Single test:

```bash
uv run pytest tests/test_dataset.py -k name
npm run build && node --test tests/js/transform_graph.test.js
```

Full verification order (mirrors CI): `npm run check` -> `uv run ty check` -> `uv run pytest` -> `uv run hatch build --clean` -> `uv run python scripts/verify_distribution_assets.py dist/*`.

Notebook checks: `uv run marimo check --strict notebooks/*.py`.

## Generated frontend assets

`src/marimo_mmp/static/transform_graph.js|.css` are gitignored build artifacts from `npm run build` (esbuild). They must exist at runtime; build them after editing anything under `frontend/`.

- `npm run test:js` rebuilds first — JS tests run against the bundled output, not the TS sources.
- `uv run hatch build --clean` invokes the Hatch hook (`scripts/hatch_build.py`) which runs `npm run build` when assets are missing, so a clean checkout needs `npm ci` before building. Set `MARIMO_MMP_SKIP_FRONTEND_BUILD=1` to skip.
- Hatch reads the dynamic project version from `marimo_mmp.__version__`; use `uv run hatch version [VERSION]` to inspect or update it.
- Wheels/sdist must ship the assets; verify with `scripts/verify_distribution_assets.py`.

## Style and conventions

- Ruff runs via pre-commit (`ruff-check --fix`, `ruff-format`) with rules `E4,E7,E9,F,B`.
- Notebooks have per-file ignores `F841`, `B018` (marimo cell idiom) — do not "fix" those in `notebooks/*.py`.
- `ty` type-checks `src`, `tests`, and `scripts` — keep scripts type-clean.
- Published widget uses minified local assets only; no CDN or runtime npm dependency.
