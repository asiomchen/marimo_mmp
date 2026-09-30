# marimo_mmp

[![Python ≥3.11](https://img.shields.io/badge/Python-%E2%89%A53.11-3776AB?logo=python&logoColor=white)](https://github.com/asiomchen/marimo_mmp/blob/main/pyproject.toml)
[![TypeScript strict](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](https://github.com/asiomchen/marimo_mmp/blob/main/tsconfig.json)
[![anywidget](https://img.shields.io/badge/widget-anywidget-7259D6)](https://anywidget.dev/)

`marimo-mmp` visualizes `mmpdb transform` results as an interactive molecular
graph: query compound, transformation rules, and generated products. Filter by
effect and support, select products, and inspect source pairs. It uses anywidget;
marimo is optional. Packaged JavaScript and CSS need no CDN or runtime npm.

Use `mmpdb>=3.1.3` to [prepare input data](#preparing-data-with-mmpdb).


## Quickstart

Requires Python ≥3.11. Install with pip:

```
pip install 'marimo-mmp[notebook]'
```
Or with uv:
```bash
uv add 'marimo-mmp[notebook]'
```


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
graph = mo.ui.anywidget(
    TransformGraph(
        dataset,
        property="pIC50",
        filters=TransformFilters(direction="gain", min_support=2),
        max_nodes=100,
    )
)
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
raw widget. `graph.update(dataset, property=..., filters=..., max_nodes=...)`
retains a still-visible selection. Omitted options select the dataset's first
property, all products, and a limit of 100; direction retains its current value
unless supplied. Other anywidget hosts display `TransformGraph(dataset)` directly. The
[explorer notebook](https://github.com/asiomchen/marimo_mmp/blob/main/notebooks/transform_explorer.py) includes the full state reference.

Changed-atom highlighting is off by default. Enable it with
`TransformGraph(dataset, highlight_changes=True)` when the dataset has query SMILES.
Highlighting can make the first render slower because it searches for the common
substructure of each product and the query; subsequent renders reuse cached SVGs.

## Preparing data with mmpdb

Use [mmpdb](https://github.com/rdkit/mmpdb) to build a matched-pair database and
apply its transformations to a query compound. With `compounds.smi` containing
SMILES and compound IDs, and `properties.tsv` containing an `ID` column and a
numeric `pIC50` column with matching IDs:

```bash
pip install 'mmpdb>=3.1.3'
mmpdb fragment compounds.smi --num-jobs 1 -o compounds.fragdb
mmpdb index compounds.fragdb --properties properties.tsv -o assay.mmpdb
mmpdb transform assay.mmpdb --smiles 'CCO' --property pIC50 -o transforms.tsv
```

Replace `CCO` and `pIC50` with your query SMILES and property name. Use the same
query SMILES as `original_smiles` when loading the output in the quickstart.

| Output | Use in the widget |
|---|---|
| `transforms.tsv` from `mmpdb transform` | Required input: generated product SMILES, transformation rules, environments, and property-change statistics. |
| `assay.mmpdb` from `mmpdb index` | Optional SQLite input via `mmpdb=...`: source compound pairs and their measured property values for provenance. Use the same database that generated the TSV. |
| `compounds.fragdb` from `mmpdb fragment` | Intermediate used by indexing; the widget does not read it. |

Keep property statistics in the transform output; `--no-properties`,
`mmpdb generate` output, and pair tables exported by `mmpdb index` do not supply the columns the widget requires. The widget loads existing TSV and SQLite files directly, so the `mmpdb` Python package is needed only for data generation. The
repository's development dependency group includes its CLI.

## Data and API

`TransformDataset.from_tsv` accepts paths, bytes, or readable streams of UTF-8
TSV/CSV; `from_df` accepts pandas DataFrames. Both validate
`ID`, `SMILES`, and mmpdb statistic columns and discover property families.
Invalid transform data raises `TransformValidationError`. Optional MMPDBs are
validated and opened read-only during loading. Duplicate column names, empty
rule fragments, negative standard deviations, p-values outside `[0, 1]`, and
out-of-order min/quartile/median/max summaries are rejected. Source pairs for
every transform and property, including pairs with missing values, are stored in memory;
`source_pairs()` needs no further database access. The database file can be
removed after loading. `dataset.mmpdb_path` retains its original path as source
metadata. Larger provenance sets increase loading time and memory use.

| Parameter | Meaning |
|---|---|
| `TransformGraph(dataset, property=..., max_nodes=100)` | Property from `dataset.properties` (default: first); product limit after filtering and ranking. |
| `TransformGraph(..., direction="higher")` | Favorable orientation: `higher` or `lower`; controls gain/loss filtering and colors. |
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

For data-only filtering and table export, `dataset.view(...)` remains available
and provides `rows()` and `source_pairs()` without constructing a widget.

## Example data

The explorer and tests use `data/processed/bilastine_transforms.tsv` and
`data/processed/h1_ic50.mmpdb`. These examples derive from ChEMBL 37 data for the
human histamine H1 receptor (HRH1, UniProt `P35367`,
[ChEMBL target `CHEMBL231`](https://www.ebi.ac.uk/chembl/explore/target/CHEMBL231)),
retrieved on August 26, 2026. Cite ChEMBL 37 when reusing this derived data.
[build_report.json](https://github.com/asiomchen/marimo_mmp/blob/main/data/processed/build_report.json) records the release,
retrieval timestamp, and validation counts.

The database uses exact, positive IC50 measurements in nM from direct human H1
binding assays, excluding potential duplicates and records with data-validity
comments. RDKit cleanup and parent-fragment selection standardized structures.
Each measurement was converted to `pIC50 = 9 - log10(IC50_nM)`; the median per
parent ChEMBL molecule became its sole property. The selection retained 117
measurements across 107 compounds, with 74 compounds indexed in the MMPDB.

## Contributing

Use uv with Python 3.11 and Node.js ≥20. From the repository root:

```bash
npm ci
uv sync --locked --python 3.11 --group dev
npm run build
uv run marimo edit notebooks/transform_explorer.py
```

Sources: Python in `src/marimo_mmp/`, TypeScript/CSS in `frontend/`, examples in
`notebooks/`, tools in `scripts/`. See [WIDGET_ARCHITECTURE.md](https://github.com/asiomchen/marimo_mmp/blob/main/WIDGET_ARCHITECTURE.md)
for internals and [AGENTS.md](https://github.com/asiomchen/marimo_mmp/blob/main/AGENTS.md) for conventions.

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

## License

Code and documentation are licensed under the [MIT License](https://github.com/asiomchen/marimo_mmp/blob/main/LICENSE).
The ChEMBL-derived example data is distributed under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/); see
[Example data](#example-data) for provenance and attribution.
