# GlassMatch

[![CI](https://github.com/br24563/Glass-Match/actions/workflows/ci.yml/badge.svg)](https://github.com/br24563/Glass-Match/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Open-source optical glass selection, comparison, and material database.
**2,920 materials · 18 source collections · 221 traceable sources** — search,
rank, compare, and inspect provenance for oxide glasses, crystals, IR
materials, polymers, and moldables.

![GlassMatch matching screenshot](docs/screenshots/01_matching.png)
![GlassMatch spectral screenshot](docs/screenshots/02_spectral.png)
![GlassMatch glass detail screenshot](docs/screenshots/03_detail.png)
![GlassMatch equivalency finder screenshot](docs/screenshots/05_equivalency.png)
![GlassMatch data sources screenshot](docs/screenshots/04_sources.png)

> Screenshots captured from a live run (`start.bat`); regenerate with
> `python scripts/capture_screenshots.py` (needs `pip install playwright` and a
> local Microsoft Edge install).

## Features

- Requirement-driven matching (wavelength band, n_d, V_d, transmission,
  density, CTE) with transparent Compatibility Scores and user-adjustable weights.
  Maker-scoped, paginated results scale to thousands of glasses.
- **Transmission modes**: Average / Minimum / Entire range, evaluated against
  manufacturer IT rows (70k samples) with Fresnel fallback labelled as
  calculated; Entire range refuses to score when band coverage < 90%.
  Catalogs list internal transmittance at different thicknesses (SCHOTT
  25 mm, most others 10 mm, some 1-3 mm); every sample is converted to one
  user-chosen sample thickness by Beer-Lambert, T_d = T^(d/d_listed), and
  labelled as scaled, so glasses are compared on the same path length.
  Conflicting duplicate samples are excluded (never pick-a-winner) and disclosed.
- **Thermal and mechanical data**: absolute dn/dT (d line, +20/+40 C) for
  1,819 materials - HIKARI's own figures, or calculated from each catalog's
  TD coefficients with the SCHOTT dn/dT formula - with an optional |dn/dT|
  limit for athermal designs; relative cost and climate/stain/acid/alkali/
  phosphate resistance classes from the .agf OD records; and T_g, thermal
  conductivity, Young's and shear modulus, Poisson's ratio, stress-optic
  coefficient, Knoop hardness, specific heat and powder-method chemical
  resistance from each maker's own Excel data workbook, for 819 glasses
  (table below).
- **Data quality report**: range checks, duplicate detection, missing-source
  checks and orphan source references — flags are listed for review, never
  auto-fixed.
- **IR mode**: for chalcogenide/IR glasses (no meaningful V_d), matching scores
  n_d + transmission band instead of penalizing the missing Abbe number.
- Provenance-first database: every value carries source, license, and
  data_type (manufacturer / calculated / interpolated / user_imported).
- **Cross-manufacturer substitution finder**: computes candidate equivalents
  from n_d, V_d, density, CTE and T_g with adjustable tolerances. Candidates are
  flagged for review and never auto-merged; curated (source-backed) pairs are
  shown separately and are never overwritten.
- Interactive Plotly dispersion + transmission plots (calculated curves labelled).
  Every catalog's coefficients are evaluated in the formula its `.agf` names
  (Schott, Sellmeier 1/3/5, Herzberger, Conrady, Extended 2/3 ... — all 13
  Zemax forms), and a curve is drawn **only** when that reproduces the catalog
  n_d within 2×10⁻⁴ *and* V_d within 0.5 — 2,574 materials, worst residuals
  3.8×10⁻⁵ and 0.23. IR crystals whose catalog has no n_d (Zemax writes 1.0)
  are instead checked against a named room-temperature measurement of the same
  material (Si, Ge, GaAs, CdTe, ZnSe, ZnS). Curves are never drawn outside the
  fit's stated wavelength range. The 19 rows that pass neither check are
  stored verbatim and **never** evaluated, and the UI says so.
- **Crystal materials** — 199 pages covering CaF₂, MgF₂, BaF₂, SrF₂, LiF, LaF₃,
  sapphire, fused silica/quartz, spinel, YAG, ZnSe, ZnS, Ge, Si, CdTe, GaAs and
  Te, from [refractiveindex.info](https://refractiveindex.info) (public domain,
  **CC0 1.0**, so unlike the manufacturer catalogs it ships with the repo). Each
  cites the paper it came from. Crystals have no n_d/V_d, so the detail page
  gives you a **reference-wavelength control** and tells you whether the number
  is a source measurement, an interpolation between samples, or an evaluation
  of a published dispersion fit (all nine refractiveindex.info formulas,
  including the constant term of formulas 1/2) — and says "unavailable"
  rather than extrapolating when the request falls outside the range the
  source states.
- Glass detail pages, 2-5 glass comparison, database + source explorers
  (material-class filter, obsolete toggle driven by each catalog's own status
  field — 1,156 discontinued glasses — per-maker coverage table).
- User CSV + manufacturer `.agf` import with validation; CSV/JSON export
  with provenance preserved.
## Installation

**Easiest (Windows):** double-click `start.bat`. First run creates an isolated
`.venv` and installs dependencies (uses `uv` if available, ~1 s, else pip);
every run after that just opens the app at `http://localhost:8501`.

**Manual:**

```text
git clone <repo-url> GlassMatch
cd GlassMatch
pip install -r requirements.txt
streamlit run app.py
```

Works offline once installed; no servers, keys, or cloud services.

## Running tests

```text
pip install -r requirements-dev.txt
python -m pytest tests -q
```

The matching algorithm and database layer are tested without Streamlit;
`streamlit.testing.v1.AppTest` exercises the full app script end-to-end.

## Example workflow

1. Pick the Visible preset (0.40-0.70 um), set n_d 1.45-1.60 and V_d 55-75
   for a low-dispersion crown search.
2. Weight transmission 35%, V_d 25%, n_d 25%.
3. Scope makers (e.g. SCHOTT + OHARA), page through ranked Compatibility
   Scores — N-BK7-class glasses surface at top.
4. Open Glass Detail to check the SCHOTT source row before designing.
5. For MWIR (3-5 um): pick the MWIR preset — chalcogenide/IR glasses are
   scored on n_d + transmission band (V_d skipped, shown as n/a).

## Matching algorithm

Per-property score is 1.0 inside the required band with linear falloff
outside. Overall = weighted mean over available data x (0.5 + 0.5 x covered
weight). Missing data lowers completeness instead of silently failing,
unless Require available data is on. Weights auto-normalize to 100%.

**IR mode** (`material_class=chalcogenide` or maker INFRARED/LIGHTPATH/UMICORE):
V_d is physically meaningless, so its weight is redistributed to n_d and
transmission and the glass is never penalized for the missing value.

Transmission requirement modes: **Average** = mean of manufacturer samples in
band; **Minimum** = worst sample; **Entire range** = worst sample but only
when samples span ≥90% of the band (otherwise reported missing, not guessed).
Manufacturer IT rows are preferred; a calculated Fresnel estimate is used only
for glasses with no manufacturer rows and is always labelled calculated.

## Database architecture

- `manufacturers.csv`, `glasses.csv`, `properties.csv` (long format with
  source_id + data_type), `sources.csv`, `sellmeier.csv` (+`transmission.csv`,
  `equivalents.csv`).
- `material_class` ∈ {oxide_glass, crystal, chalcogenide, polymer, moldable},
  `status` ∈ {standard, obsolete}; both default safely on legacy files.
- `spectral_nk.csv` holds tabulated optical constants (wavelength, n, k) for
  crystal pages, verbatim with a per-row `source_id`.
- Dispersion rows (`sellmeier.csv`) keep the coefficients verbatim in
  `coefficients` with the equation they belong to in `zemax_formula` or
  `rii_formula`; the `B*`/`C*` columns are filled only for pure Sellmeier
  sums. A row is plottable only if the importer earned it a verified label
  (`Sellmeier-1 (...)`, `Schott (Zemax formula 1, ...)`, ...) by reproducing
  the catalog n_d and V_d, or, for placeholder-n_d IR crystals, by
  `scripts/verify_ir_dispersion.py`. Everything else is stored as
  `Non-dispersable (...) - archived, never evaluated`, with the measured
  discrepancy in the label.
- Add a manufacturer: append rows to `manufacturers.csv`/`sources.csv`,
  then glasses + properties — or run `scripts/merge_agf.py` on a staged `.agf`.
  No matching/UI code changes.
- Add a glass: append one `glasses.csv` row + N `properties.csv` rows.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full workflow, including how to
add a manufacturer without writing any Python. Release history is in
**[CHANGELOG.md](CHANGELOG.md)**.

## Database contents (committed, 2026-09)

| Maker file | Glasses | Notes |
|---|---|---|
| SCHOTT June-2025 `.agf` | 366 | Manufacturer, current (re-checked 2026-10-20: unchanged) |
| OHARA May-2026 `.agf` | 433 | Manufacturer, current |
| HOYA July-2026 `.agf` (incl. obsolete) | 436 | Manufacturer, current; 1 mirror-only legacy glass kept as obsolete |
| CDGM Sept-2026 `.agf` | 375 | Manufacturer, current; 23 mirror-only legacy glasses kept as obsolete |
| SUMITA Aug-2026 `.agf` (incl. discontinued) | 433 | Manufacturer, current |
| HIKARI June-2025 catalog workbook + Nikon 2019 `.agf` | 397 | 155 current HIKARI glasses (with thermal/mechanical data); 235 discontinued HIKARI and 7 Nikon NIFS/NICF from Nikon's 2019 Zemax data |
| LZOS / Corning | 150 | nzhagen/zemaxglass mirror, vintage unknown (no public catalog found) — verify before design |
| IR (generic/LightPath/Umicore) | 61 | Chalcogenide + crystal entries; IR mode applies |
| Polymers (Zeon/Arton/Topas/Archer) + RPO moldables | 70 | Polymer/moldable classes |
| **Total** | **2,920** | 2,756 verified dispersion curves · 33 archived non-dispersable · 131 with no curve · 199 CC0 crystal pages · 70k transmission rows · 135k tabulated n/k samples |

1,244 glasses are marked obsolete, from each catalog's own status field (or,
for HIKARI, absence from the current catalog); the Database explorer hides
them by default. HIKARI glasses are listed once, under HIKARI: Nikon's 2019
file distributes the same line, and the old mirror had most of them twice.

Thermal and mechanical coverage (glasses with a value, from the makers' own
Excel data workbooks; HOYA's data page could not be reached on 2026-10-28):

| Property | SCHOTT | OHARA | CDGM | HIKARI | HOYA |
|---|---|---|---|---|---|
| T_g | 156 | 161 | 347 | 155 | 0 |
| Thermal conductivity | 147 | 161 | 157 | 155 | 0 |
| Young's modulus | 155 | 161 | 336 | 155 | 0 |
| Shear modulus | 0 | 161 | 335 | 155 | 0 |
| Poisson's ratio | 155 | 161 | 327 | 155 | 0 |
| Stress-optic coefficient | 154 | 161 | 296 | 155 | 0 |
| Knoop hardness | 156 | 161 | 345 | 155 | 0 |
| Specific heat | 147 | 0 | 157 | 155 | 0 |
| Water / acid resistance, powder method | 33 / 32 | 161 / 161 | 347 / 347 | 155 / 155 | 0 |

SCHOTT's workbook covers its 159 current preferred and inquiry glasses,
OHARA's three workbooks (S, L and special-order) 161 glasses, CDGM's every
glass in its current catalog. Units are confirmed from each workbook - its
headers, SCHOTT's Description sheet, and E = 2G(1 + nu) on every CDGM and
OHARA row; CDGM's Knoop hardness is stored as printed, in 1e7 Pa.

Duplicate NM names across mold variants (HOYA E-FL6/FD-series, Nikon E-series)
are disambiguated with status-flag suffixes — zero duplicate `glass_id`s.

## Data sources and licensing

- Manufacturer catalogs (SCHOTT, OHARA, HOYA, CDGM, SUMITA `.agf`; HIKARI's
  Excel workbook; SCHOTT's, OHARA's and CDGM's Excel data workbooks; Nikon's
  Zemax data): authoritative, redistribution-limited —
  the files stay in untracked `data/staging/` (`data/staging/official/<maker>/`
  for the 2026-10 downloads); only normalized rows ship. Each `sources.csv`
  row records the download page, publication date and access date.
- Mirror `.agf` files (LZOS, Corning, IR and polymer makers, which publish no
  current catalog): `mirror-vintage-unknown; verify vs manufacturer catalog`.
- Every glass value comes from a parsed catalog record; nothing is
  hand-transcribed. The curated substitution pairs in `equivalents.csv` cite
  the manufacturer catalogs as cross-references only.
- No scraping behind access controls.

**Crystals and tabulated optical constants are a different case.** The 199
crystal pages under `data/spectral/refractiveindex_info/` come from the
[refractiveindex.info](https://refractiveindex.info) database, which its
maintainer placed in the **public domain under CC0 1.0** ("you may copy,
modify, and distribute ... even for commercial purposes, without asking
permission"). Those files are therefore *committed here* — they are the
provenance for every crystal number, and the licence permits it. Each page
records the paper it was taken from, and GlassMatch carries that citation
through to `sources.csv` (e.g. CaF2 n_d <- Malitson, *Appl. Opt.* **2**, 1103
(1963), DOI `10.1364/AO.2.001103`). The underlying papers remain the property of
their authors; GlassMatch redistributes the compiled constants, not the
publications. Refresh with `python scripts/fetch_refractiveindex.py`, which
pins a manifest with a SHA-256 per file.

## Data integrity

data_type is always shown: manufacturer-reported vs GlassMatch-calculated
(Sellmeier evaluation, Fresnel transmission estimate) vs interpolated vs
literature (a value read straight out of a cited table) vs user_imported.
Calculated values never pose as manufacturer data. Where no source covers a
requested wavelength or formula, GlassMatch reports the value as unavailable
rather than extrapolating one.

**Conflicting transmission samples are quarantined, not resolved.** Some source
catalogs list the same wavelength twice with different values - a data-entry
artifact (`1E-6` beside a real 0.99 reading) in some, a genuine disagreement in
others. GlassMatch does not pick a winner. Every such row is removed from
`transmission.csv` at import and recorded in
`data/normalized/transmission_conflicts.csv` with *both* values, the spread and
the source id, and is excluded from band statistics until a maintainer checks
the source catalog. The Data Sources tab reports how many are quarantined.

## Contributing / roadmap

Add rows + source metadata via PR (`scripts/merge_agf.py --only <SOURCE_ID>`
keeps merges idempotent); validation flags out-of-range values.
Done: bulk `.agf` import, non-Sellmeier gating, IR mode, dedup suffixes,
equivalency candidates, transmission conflict quarantine.
Future: achromatic-doublet finder, Zemax export, cost data, Sellmeier fitting.

## Expansion history

- Ring 1/2 engine: `glassmatch/importers/agf.py` parses user-downloaded Zemax
  `.agf` catalogs (NM/CD/TD/GC/IT/LD/ED records, UTF-16 fallback, multi-line
  CD, each fit checked in its own Zemax formula against catalog n_d and V_d).
  Unknown records flagged, never crash.
- `glassmatch/importers/catalogs.py`: per-manufacturer download config —
  adding a maker = add an entry, not code.
- `data/manufacturers/<MFR>/README.md`: per-maker download instructions.
- 2026-09 merge: 17 staged `.agf` → 2,526 normalized glasses (see table above).
- 2026-09 merge: 195 refractiveindex.info pages (CC0 1.0) → crystal materials
  covering 17 compounds, the first non-glass material class.
- 2026-10 audit: dispersion evaluated in each catalog's declared formula
  (710 -> 2,574 curves), placeholder n_d no longer stored as 2.0, the
  refractiveindex.info constant term restored on 19 crystal pages, 4 more
  crystal pages imported, deep-UV/IR transmission samples kept, catalog
  obsolete status honoured, and the one hand-entered glass (CDGM H-ZF52,
  which carried SCHOTT SF6's values) removed.


