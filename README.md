# GlassMatch

Open-source optical glass selection, comparison, and material database.
**2,526 glasses · 17 makers · 25 traceable sources** — search, rank, compare,
and inspect provenance for oxide glasses, IR materials, polymers, and moldables.

![GlassMatch matching screenshot](docs/screenshots/matching.png)
![GlassMatch spectral screenshot](docs/screenshots/spectral.png)

> Screenshots are placeholders until captured from a live run
> (`streamlit run app.py` → Matching / Spectral tabs).

## Features

- Requirement-driven matching (wavelength band, n_d, V_d, transmission,
  density, CTE) with transparent Compatibility Scores and user-adjustable weights.
  Maker-scoped, paginated results scale to thousands of glasses.
- **IR mode**: for chalcogenide/IR glasses (no meaningful V_d), matching scores
  n_d + transmission band instead of penalizing the missing Abbe number.
- Provenance-first database: every value carries source, license, and
  data_type (manufacturer / calculated / interpolated / user_imported).
- Interactive Plotly dispersion + transmission plots (calculated curves labelled).
  Non-Sellmeier rows (Nikon polynomials, Herzberger legacy) are archived
  verbatim and **never** evaluated as Sellmeier — the UI says so explicitly.
- Glass detail pages, 2-5 glass comparison, database + source explorers
  (material-class filter, obsolete toggle, per-maker coverage table).
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

## Database architecture

- `manufacturers.csv`, `glasses.csv`, `properties.csv` (long format with
  source_id + data_type), `sources.csv`, `sellmeier.csv` (+`transmission.csv`,
  `equivalents.csv`).
- `material_class` ∈ {oxide_glass, chalcogenide, polymer, moldable},
  `status` ∈ {standard, obsolete}; both default safely on legacy files.
- Dispersion gate: `formula == "Sellmeier-1 (Zemax CD record)"` means plottable;
  anything else is archived verbatim, never evaluated as Sellmeier.
- Add a manufacturer: append rows to `manufacturers.csv`/`sources.csv`,
  then glasses + properties — or run `scripts/merge_agf.py` on a staged `.agf`.
  No matching/UI code changes.
- Add a glass: append one `glasses.csv` row + N `properties.csv` rows.

## Database contents (committed, 2026-09)

| Maker file | Glasses | Notes |
|---|---|---|
| SCHOTT June-2025 `.agf` | 366 | Authoritative, current |
| OHARA May-2026 `.agf` | 433 | Authoritative, current; 188 Herzberger legacy rows archived |
| HOYA / NIKON / HIKARI / SUMITA / CDGM / LZOS / Corning | 1,657 | nzhagen/zemaxglass mirror, vintage unknown — verify before design |
| IR (generic/LightPath/Umicore) | 61 | Chalcogenide + crystal entries; IR mode applies |
| Polymers (Zeon/Arton/Topas/Archer) + RPO moldables | 70 | Polymer/moldable classes |
| **Total** | **2,526** | 672 verified Sellmeier-1 · 64k transmission rows |

Duplicate NM names across mold variants (HOYA E-FL6/FD-series, Nikon E-series)
are disambiguated with status-flag suffixes — zero duplicate `glass_id`s.

## Data sources and licensing

- SCHOTT/OHARA `.agf` files: authoritative, redistribution-limited — bulk files
  stay in untracked `data/staging/`; only normalized rows ship.
- Mirror `.agf` files: `mirror-vintage-unknown; verify vs manufacturer catalog`.
- N-BK7 anchor values: SCHOTT datasheet (verify at schott.com).
- Sellmeier CC0 mirror via refractiveindex.info where noted. No scraping
  behind access controls.

## Data integrity

data_type is always shown: manufacturer-reported vs GlassMatch-calculated
(Sellmeier evaluation, Fresnel transmission estimate) vs interpolated vs
user_imported. Calculated values never pose as manufacturer data.

## Contributing / roadmap

Add rows + source metadata via PR (`scripts/merge_agf.py --only <SOURCE_ID>`
keeps merges idempotent); validation flags out-of-range values.
Done: bulk `.agf` import, non-Sellmeier gating, IR mode, dedup suffixes.
Future: achromatic-doublet finder, Zemax export, cost data, Sellmeier fitting.

## Expansion history

- Ring 1/2 engine: `glassmatch/importers/agf.py` parses user-downloaded Zemax
  `.agf` catalogs (NM/CD/TD/GC/IT/LD/ED records, UTF-16 fallback, multi-line
  polynomial CD, nd-vs-Sellmeier cross-check >0.002 flagged). Unknown records
  flagged, never crash.
- `glassmatch/importers/catalogs.py`: per-manufacturer download config —
  adding a maker = add an entry, not code.
- `data/manufacturers/<MFR>/README.md`: per-maker download instructions.
- 2026-09 merge: 17 staged `.agf` → 2,526 normalized glasses (see table above).


