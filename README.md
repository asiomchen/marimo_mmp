# marimo_mmp

[![Python ≥3.11](https://img.shields.io/badge/Python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![TypeScript strict](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](tsconfig.json)
[![anywidget](https://img.shields.io/badge/widget-anywidget-7259D6)](https://anywidget.dev/)

`marimo-mmp` visualizes `mmpdb transform` results as an interactive molecular
graph: query compound, transformation rules, and generated products. Filter by
effect and support, select products, and inspect source pairs. It uses anywidget;
marimo is optional. Packaged JavaScript and CSS need no CDN or runtime npm.

## Quickstart

Requires Python ≥3.11. From a checkout, run `npm ci` before
`pip install '.[notebook]'` (or `pip install .` for other anywidget hosts).
For development, use the contributor setup below.

```python
import marimo as mo

from marimo_mmp import (
    EvidenceThresholds,
    TransformDataset,
    TransformFilters,
    TransformGraph,
)

dataset = TransformDataset.from_tsv(
    "transforms.tsv",
    original_smiles="CCO",  # optional query SMILES
    mmpdb="assay.mmpdb",  # optional provenance database
    evidence_thresholds=EvidenceThresholds(moderate=2, strong=5),
)
view = dataset.view(
    property="pIC50",
    filters=TransformFilters(direction="gain", min_support=2),
    max_nodes=100,
)
graph = mo.ui.anywidget(TransformGraph(view))
graph
```

In marimo, assign `graph` in one cell and read its immutable
`TransformGraphState` in a downstream cell that reruns on interaction:

```python
state = graph.state
state.selected_compound, state.selected_stats  # typed records, or None
state.property_name, state.filters            # active property and typed filters
state.shown_count, state.matching_count       # rendered versus matching products
state.rows()                                 # table-ready rows
state.source_pairs()                         # in-memory pairs for selected product
```

`graph.value` is marimo's synchronized trait dictionary; `graph.widget` is the
raw widget. `graph.update(view)` retains a still-visible selection. Other
anywidget hosts display `TransformGraph(view)` directly. The
[explorer notebook](notebooks/transform_explorer.py) includes the full state reference.

Changed-atom highlighting is off by default. Enable it with
`TransformGraph(view, highlight_changes=True)` when the dataset has query SMILES.
Highlighting can make the first render slower because it searches for the common
substructure of each product and the query; subsequent renders reuse cached SVGs.

## Data and API

`TransformDataset.from_tsv` accepts paths, bytes, or readable streams of UTF-8
TSV/CSV, optionally gzipped; `from_df` accepts pandas DataFrames. Both validate
`ID`, `SMILES`, and mmpdb statistic columns and discover property families.
Invalid transform data raises `TransformValidationError`. Optional MMPDBs are
validated and opened read-only during loading. Source pairs for every transform
and property, including pairs with missing values, are stored in memory;
`source_pairs()` needs no further database access. The database file can be
removed after loading. `dataset.mmpdb_path` retains its original path as source
metadata. Larger provenance sets increase loading time and memory use.

| Parameter | Meaning |
|---|---|
| `view(property=..., max_nodes=100)` | Property from `dataset.properties` (default: first); product limit after filtering and ranking. |
| `view(direction="higher")`, `TransformGraph(..., direction="higher")` | Favorable orientation: `higher` or `lower`; use the same value for both. |
| `TransformFilters(direction=...)` | `all` (default), `gain`, `loss`, or `neutral`, following the orientation. |
| Other filter fields | `min_abs_effect`, `min_support`, `radii`, `quality`, `text`, `max_std`, `max_p_value`. Use tuples for radii and evidence names in `quality`. |
| `EvidenceThresholds(moderate=2, strong=5)` | Inclusive pair-count minima: Moderate ≥2; Strong > Moderate. |
| `TransformGraph(..., height=1220)` | Stage height cap in pixels (minimum 480), also limited by the viewport. |
| `TransformGraph(..., highlight_changes=False)` | Constructor setting for changed-atom highlights; retained across updates and copies. Query structure remains visible when highlighting is off. |

Default evidence tiers summarize database support: **Exploratory** = 1 pair,
**Moderate** = 2–4, **Strong** ≥5. Generated products are not experimentally
validated by these labels. Missing standard deviation, quartiles, or p-values
produce warnings. Effects are supplied property deltas. Changing evidence chips
resets minimum support to 1; changing minimum support selects all evidence levels.

## Contributing

Use uv with Python 3.11 and Node.js ≥20. From the repository root:

```bash
npm ci
uv sync --locked --python 3.11 --group dev
npm run build
uv run marimo edit notebooks/transform_explorer.py
```

Sources: Python in `src/marimo_mmp/`, TypeScript/CSS in `frontend/`, examples in
`notebooks/`, tools in `scripts/`. See [WIDGET_ARCHITECTURE.md](WIDGET_ARCHITECTURE.md)
for internals and [AGENTS.md](AGENTS.md) for conventions.

Run the CI checks and package verification:

```bash
npm run check
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run pytest
uv run marimo check --strict notebooks/*.py
uv run hatch build --clean
uv run python scripts/verify_distribution_assets.py dist/*
```

`npm run check` type-checks TypeScript and tests rebuilt assets. After frontend
edits, run `npm run build`, or `npm run dev` to watch. Runtime assets in
`src/marimo_mmp/static/` are gitignored; Hatch builds missing assets and includes
them in wheels/sdists. Use `uv run hatch version [VERSION]` to inspect/update the
version. Ruff also runs via pre-commit.

The H1 example uses exact ChEMBL IC50 records and median
`pIC50 = 9 - log10(IC50_nM)`. Rebuild `data/processed/h1_ic50.mmpdb` with
`uv run python scripts/h1_pipeline.py` (network required; slow); explore with
`uv run marimo edit notebooks/h1_mmpdb.py`. [NOTES.md](NOTES.md) covers methodology,
provenance, and outputs.
