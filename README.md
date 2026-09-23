# GlassMatch

Open-source optical glass selection, comparison, and material database.

## Features

- Requirement-driven matching (wavelength band, n_d, V_d, transmission,
  density, CTE) with transparent Compatibility Scores and user-adjustable weights.
- Provenance-first database: every value carries source, license, and
  data_type (manufacturer / calculated / interpolated / user_imported).
- Interactive Plotly dispersion + transmission plots (calculated curves labelled).
- Glass detail pages, 2-5 glass comparison, database + source explorers.
## Installation

```text
git clone <repo-url> GlassMatch
cd GlassMatch
pip install -r requirements.txt
streamlit run app.py
```

Works offline once installed; no servers, keys, or cloud services.

## Example workflow

1. Pick the Visible preset (0.40-0.70 um), set n_d 1.45-1.60 and V_d 55-75
   for a low-dispersion crown search.
2. Weight transmission 35%, V_d 25%, n_d 25%.
## Matching algorithm

Per-property score is 1.0 inside the required band with linear falloff
outside. Overall = weighted mean over available data x (0.5 + 0.5 x covered
weight). Missing data lowers completeness instead of silently failing,
unless Require available data is on. Weights auto-normalize to 100%.

## Database architecture

- `manufacturers.csv`, `glasses.csv`, `properties.csv` (long format with
  source_id + data_type), `sources.csv`, `sellmeier.csv`.
- Add a manufacturer: append rows to `manufacturers.csv`/`sources.csv`,
  then glasses + properties. No matching/UI code changes.
- Add a glass: append one `glasses.csv` row + N `properties.csv` rows.

## Data sources and licensing

- N-BK7 anchor values: SCHOTT datasheet (redistribution-prohibited; verify
  at schott.com). Other catalog nd/Vd: transcribed reference values from
  SCHOTT/OHARA/HOYA/CDGM/SUMITA catalogs - re-verify before detailed design.
- Sellmeier coefficients: CC0 mirror via refractiveindex.info (originals:
  manufacturer Zemax catalogs). No scraping behind access controls.

## Data integrity

data_type is always shown: manufacturer-reported vs GlassMatch-calculated
(Sellmeier evaluation, Fresnel transmission estimate) vs interpolated vs
user_imported. Calculated values never pose as manufacturer data.

## Contributing / roadmap

Add rows + source metadata via PR; validation flags out-of-range values.
Future: doublets, Zemax export, CTE matching, cost data, Sellmeier fitting.

## Expansion to every optical material (Ring 1/2 engine: DONE)

- `glassmatch/importers/agf.py`: parses user-downloaded Zemax `.agf` catalogs
  (NM/CD/TD/GC/IT records) into normalized frames with an nd-vs-Sellmeier
  cross-check (>0.002 flagged). Unknown records flagged, never crash.
- `glassmatch/importers/catalogs.py`: per-manufacturer download config —
  adding a maker (e.g. HIKARI, LZOS entries already present) = add an entry,
  not code. `.agf` files stay on the user's machine (redistribution-limited);
  only the parser ships with GlassMatch.
- `data/manufacturers/<MFR>/README.md`: per-maker download instructions.
- New additive schema (backward-compatible): `transmission.csv`,
  `equivalents.csv` (near-equivalents with "verify melt data" notes),
  `material_class`/`status` columns defaulting to oxide_glass/standard.
- UI: Import/Export tab accepts `.agf` uploads and exports normalized JSON;
  Database Explorer has material-class filter, obsolete toggle, and a
  per-manufacturer coverage table; Glass Detail shows near-equivalents.
- Rings ahead: full SCHOTT/OHARA backfill via this importer, then
  crystals/IR (CaF2, Ge, Si, ZnSe, chalcogenides), then polymers/moldables.



