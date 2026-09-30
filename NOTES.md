# H1 receptor matched-pair database: build notes

## Scope and primary property

The database covers the human histamine H1 receptor (HRH1), ChEMBL target
`CHEMBL231`, UniProt `P35367`. Only compounds with a usable IC50 measurement
are included. The sole mmpdb property is `pIC50`, calculated locally as
`9 - log10(IC50_nM)` from ChEMBL's standardized numeric IC50 value. A ChEMBL
pChEMBL value is not required. Ki, Kd, EC50, potency, and other measurement
types are not mixed into this property.

## Every build step

1. **Record the source version and time.** The pipeline queries the ChEMBL
   status endpoint and records both the database version and UTC retrieval
   timestamp in `data/processed/build_report.json`.
2. **Verify the target.** It retrieves `/target/CHEMBL231.json` and stops unless
   ChEMBL describes the target as a human single protein. This guards against
   target-name ambiguity and species mixing.
3. **Download binding assays.** It fetches every assay mapped to this target
   with assay type `B` (binding), following API pagination.
4. **Keep direct assays.** Assays are retained only when
   `relationship_type == "D"`, ChEMBL's direct-target relationship flag.
5. **Download IC50 activity rows.** The activity query requests human H1
   binding records with `standard_type=IC50`, an exact `=` relation,
   `standard_flag=1`, `potential_duplicate=0`, a non-null standardized value,
   and standardized units of `nM`.
6. **Apply local validity checks.** Records must belong to a retained direct
   assay, still have endpoint IC50 and exact relation, have no ChEMBL data
   validity comment, and contain a positive numeric standardized IC50 value in
   nM and parseable SMILES.
7. **Standardize structures.** RDKit cleanup is followed by parent-fragment
   selection and canonical isomeric SMILES generation. This removes salts and
   gives mmpdb a consistent structure representation while preserving
   stereochemistry when specified.
8. **Aggregate repeated measurements.** Records are grouped by parent ChEMBL
   molecule ID. Each accepted value is converted with
   `pIC50 = 9 - log10(IC50_nM)`, and median pIC50 becomes the compound
   property. Median is used because it is less sensitive than the mean to
   discrepant literature measurements.
   The number, minimum, and maximum of the retained measurements remain in
   `h1_ic50_compounds.csv` for audit.
9. **Write mmpdb inputs.** `h1_ic50.smi` contains standardized SMILES and IDs.
   `h1_ic50_properties.tsv` contains ID and calculated pIC50, with pIC50 as the
   only and therefore primary property.
10. **Fragment molecules.** `mmpdb fragment` uses the package's default
    rotatable-bond rules. One process is requested for deterministic, modest
    resource use. The `.fragdb` intermediate is ignored by Git because it can
    be regenerated.
11. **Index matched pairs.** `mmpdb index` creates `h1_ic50.mmpdb`, loads the
    calculated pIC50 property, and retains transformations supported by the default
    mmpdb indexing rules. The optional smallest-transformation reduction is not
    used because mmpdb 3.1.4's reduction code is incompatible with bonded dummy
    atoms under RDKit 2026.03; ordinary indexing is unaffected.
12. **Validate outputs.** The pipeline opens both SQLite files and records
    counts of fragmentations, indexed compounds, transformation rules, pairs,
    and rule environments. The marimo notebook also confirms the stored
    property name.

## Why ChEMBL shows roughly 1,000 IC50 compounds

In ChEMBL 37, the broad human H1 binding/IC50 selection contains 1,141 rows
covering 1,095 parent compounds. Most cannot be converted to pIC50: 822 rows
have no numeric value, relation, or units; 60 are right-censored (`>`), and one
is left-censored (`<`). Only 258 rows are exact numeric IC50 measurements. The
API quality and duplicate filters retain 245, and the direct-target assay rule
retains 117 measurements covering 107 parent compounds. Treating absent or
censored values as exact numbers would produce invalid pIC50 properties, so
they are preserved only in ChEMBL's broad headline count and not in this
matched-pair database.

## Output map

- `data/raw/chembl_status.json`: ChEMBL version response.
- `data/raw/h1_target.json`: target metadata used in verification.
- `data/raw/h1_direct_binding_assays.jsonl.gz`: retained direct binding assays.
- `data/raw/h1_ic50_activities.jsonl.gz`: API activity snapshot before local
  checks.
- `data/raw/h1_ic50_accepted_records.jsonl.gz`: accepted, standardized rows.
- `data/processed/h1_ic50_compounds.csv`: one audited row per compound.
- `data/processed/h1_ic50.smi`: mmpdb structure input.
- `data/processed/h1_ic50_properties.tsv`: calculated pIC50 property input.
- `data/processed/h1_ic50.mmpdb`: final matched molecular pair database.
- `data/processed/build_report.json`: provenance and validation counts.

## Rebuild

Run `uv run python scripts/h1_pipeline.py`, or open `notebooks/h1_mmpdb.py` in
marimo and press **Rebuild database from ChEMBL**. Rebuilding replaces only
the generated `.fragdb` and `.mmpdb` files at the exact paths listed above.

## Public sources

- ChEMBL target: <https://www.ebi.ac.uk/chembl/explore/target/CHEMBL231>
- ChEMBL REST API documentation:
  <https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services>
- mmpdb documentation: <https://github.com/rdkit/mmpdb>

ChEMBL is public data distributed under CC BY-SA 3.0. Cite the ChEMBL release
recorded in the report when using this derived database in downstream work.
