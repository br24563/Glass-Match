# Contributing to GlassMatch

GlassMatch is a scientific instrument, so the contribution bar is different from a
typical app: **a number without a source is a defect.** Please read the rules below
before opening a pull request.

## The one non-negotiable rule

> Every manufacturer-derived value must be traceable to a real, citable source.

Accepted: manufacturer catalogs and `.agf` files, manufacturer datasheets, official
technical documents, or authoritative published references (with a URL or citation).

Not accepted: values copied from forums, vendor marketplace listings, AI-generated
numbers, values "typical for this glass type", or anything you cannot attribute. If
you are unsure whether a number is manufacturer-reported or derived, say so in the
notes and label it `data_type=calculated` — guessing is worse than a gap.

Missing data is fine. Fabricated data is not. A glass with three sourced properties
is useful; a glass with fifteen invented ones is actively harmful.

## Development setup

```text
git clone https://github.com/br24563/Glass-Match.git
cd Glass-Match
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m streamlit run app.py
```

Or just double-click `start.bat` on Windows (creates the venv and installs
dependencies on first run).

Run the tests before pushing:

```text
.venv\Scripts\python -m pytest tests -q
```

## Adding a manufacturer (Zemax `.agf` catalogs)

The intended path requires **no Python changes** — you add data, not code.

1. **Download the catalog** from the manufacturer. Do not commit the `.agf` file
   itself; manufacturer catalogs are redistribution-limited. Save it to
   `data/manufacturers/<MANUFACTURER>/` (gitignored) or anywhere outside the repo.
2. **Register the download** by adding an entry to `glassmatch/importers/catalogs.py`
   (`manufacturer`, `download_url`, `hint`, `license_note`). This is the only code
   change, and it is pure configuration.
3. **Import it** either way:
   - *App (recommended)*: run GlassMatch, open the **Import / Export** tab, choose the
     manufacturer, upload the `.agf`, review the flagged-issues table, and download
     the normalized JSON.
   - *Script*: `python scripts/merge_agf.py --source-id <SOURCE_ID> --path <file.agf>`
     (idempotent — re-running replaces only that source's rows).
4. **Add a `sources.csv` row** with `source_id`, `source_name`, `source_url`,
   `access_date`, and a `license` note. State plainly whether the data came from the
   manufacturer's own site or a third-party mirror.
5. **Open a PR** with the CSV diff and fill in the PR checklist.

The importer handles UTF-8 and UTF-16 files, multi-line coefficient records, and
duplicate glass names (status-flag suffixes). It cross-checks each n_d against the
Sellmeier coefficients it parsed and flags mismatches above 0.002.

## Adding individual glasses or properties

Edit `data/normalized/properties.csv` directly:

```text
glass_id,property,value,unit,reference_wavelength,data_type,source_id,notes
SCHOTT-N-BK7,density,2.51,g/cm3,,manufacturer,SCHOTT-DS-2025,June 2025 datasheet
```

- `glass_id` must already exist in `glasses.csv` (format `<MANUFACTURER>-<CODE>`).
- `data_type` is one of `manufacturer`, `calculated`, `interpolated`, `user_imported`.
- Use `reference_wavelength` for anything wavelength-dependent (n_d = 587.6 nm).
- Units follow `glassmatch/database.py` (`PROPERTY_UNITS`); use nm internally and
  µm only where the source reports µm.

Run the app's **Data Sources → Data quality report** afterwards, or
`pytest tests -q`, to catch out-of-range values before pushing.

## Spectral data

`data/normalized/transmission.csv`:

```text
glass_id,wavelength_um,value,value_unit,thickness_mm,data_type,source_id,notes
SCHOTT-N-BK7,0.4,0.912,1,10,manufacturer,SCHOTT-AGF-2025-06,IT record
```

Transmission is stored as a **fraction (0–1)**, with the measurement thickness
recorded explicitly, because internal transmittance is meaningless without it.

If a source lists the same wavelength twice with different values, do **not**
choose one. The importer quarantines every row of that key and reports it in the
flagged-issues table; keep the displaced values in
`data/normalized/transmission_conflicts.csv` so the decision stays auditable.
To re-check the shipped data: `python scripts/clean_transmission.py --dry-run`.

## Code changes

- Matching, database, and spectra layers are importable and testable without
  Streamlit — keep it that way. UI code belongs in `app.py`.
- New properties should flow through the existing schema; do not special-case a
  manufacturer in matching or plotting.
- Add a test for anything you change. `tests/` has 45 tests; keep them green.
- Match the existing style: module docstrings, `from __future__ import annotations`,
  type hints on public functions, comments explaining *why*.

## Licensing of contributed data

By contributing data you confirm it is legally redistributable, or that the PR only
adds a documented download procedure. Include the license or usage terms in the
`sources.csv` row. Do not scrape behind authentication, CAPTCHAs, paywalls, or robots
restrictions; do not bypass access controls.

## Reporting bugs

Use the bug report template. If the bug is about a *value* in the database, name the
glass and the property — a wrong number is the highest-priority bug this project can
have, and we will trace it back to its source.

## Code of conduct

Be precise, be fair, and assume the other person was trying to help. Disagreements
about data get settled by pointing at the source document, not by seniority.