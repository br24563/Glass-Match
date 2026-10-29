# How GlassMatch's data is validated

GlassMatch only draws a dispersion curve, reports an index or ranks a glass on
data that has passed the checks below. Each check is reproducible from the
repository: the scripts named here regenerate the numbers, and the tests named
here pin them in CI.

All indices are the manufacturers' **nominal catalog values** at their stated
reference temperature (20-25 °C). A delivered melt differs from them within
the maker's tolerance class (typically ±2-5×10⁻⁴ in n_d for standard grades);
use melt data for final design.

## 1. Every fit reproduces its catalog n_d and V_d

Each `.agf` CD record is evaluated in the dispersion formula its NM record
names (all 13 Zemax formulas; `glassmatch.spectra.zemax_n`). A fit is
accepted only if it reproduces the catalog n_d within 2×10⁻⁴ **and** V_d
within 0.5. Across the shipped catalogs the worst accepted residuals are
3.8×10⁻⁵ and 0.23; everything else is archived and never evaluated. Every
stored n_d / V_d equals the value in its source file.
*Pinned by* `tests/test_formula_audit.py`.

## 2. Fits agree with the makers' own datasheets at every printed line

The makers' Excel data workbooks tabulate the catalog index at 15-20 spectral
lines from the i line (365 nm) to 2.3 µm, independently of the `.agf`
coefficients. `glassmatch.datasheet_check` evaluates each verified fit at
every line inside its stated range and compares. The workbooks print 5 or 6
decimals, so agreement to a few 10⁻⁶ is the expected result; the largest
differences sit at the UV end of a fit's range, where fits are least
constrained.

<!-- crosscheck:begin -->

Generated 2026-10-28 by `scripts/validate_against_datasheets.py`.

| Datasheet | Maker | Glasses | Lines per glass | Within 2e-05 | Median max \|Δn\| | Worst \|Δn\| |
|---|---|---|---|---|---|---|
| CDGM-XLSX-2026-09 | CDGM | 335 | 17 | 322 | 1.1e-06 | 4.8e-05 |
| HOYA-XLSX-2026-04-01-MIRROR | HOYA | 236 | 17 | 236 | 4.8e-06 | 7.0e-06 |
| OHARA-L-XLSX-2025-03-12 | OHARA | 17 | 20 | 17 | 4.9e-06 | 5.4e-06 |
| OHARA-SPECIAL-XLSX-2025-03-12 | OHARA | 14 | 20 | 14 | 5.0e-06 | 5.5e-06 |
| OHARA-XLSX-2026-04-02 | OHARA | 130 | 20 | 130 | 4.9e-06 | 6.8e-06 |
| SCHOTT-XLSX-2025-11-13 | SCHOTT | 156 | 18 | 140 | 4.9e-06 | 3.8e-05 |

**888 glass/datasheet pairs, 859 (96.7%) within 2e-05 at every line; worst 4.8e-05.**

<!-- crosscheck:end -->

The per-glass residuals are in
[`docs/validation/datasheet_crosscheck.csv`](validation/datasheet_crosscheck.csv)
(residuals only - no manufacturer values). A fixed sample of the catalog
values themselves, a few glasses per workbook plus each workbook's worst case,
is committed as `data/validation/reference_indices.csv`.
*Regenerate with* `python scripts/validate_against_datasheets.py` (needs the
staged workbooks). *Pinned by* `tests/test_datasheet_validation.py`.

HIKARI's fits come from the HIKARI workbook itself and are checked at import
against the same workbook's index at 21 wavelengths (worst 4.8×10⁻⁶) - a
consistency check, not an independent one. SUMITA publishes no index table,
so SUMITA fits rest on check 1 alone.

## 3. IR materials with no catalog n_d

Zemax writes n_d = 1.0 for materials opaque in the visible (Si, Ge, GaAs,
CdTe, ZnSe, ZnS). Their fits are compared with one room-temperature bulk
measurement per material from refractiveindex.info, named in advance in
`glassmatch/reference_check.py`, at ≤ 0.005 over at least half the fit's
range; all eight agree within 0.0002-0.0044.
*Pinned by* `tests/test_formula_audit.py`.

## 4. dn/dT

dn/dT is computed from the `.agf` TD coefficients with the SCHOTT formula
(`glassmatch.spectra.dn_dt_abs`). Against HIKARI's own catalog figures the
values computed from Nikon's 2019 TD coefficients agree for 139 of 141 glasses
(median difference 0.026×10⁻⁶/K); the other two have a mis-printed D0 in the
source file and are not used.
*Pinned by* `tests/test_thermal_and_catalog_data.py`.

## 5. Transmission

Internal transmittance is compared at one sample thickness, converted from
each catalog's listed thickness by Beer-Lambert, and labelled as scaled.
Duplicate samples that disagree are quarantined in
`data/normalized/transmission_conflicts.csv` with both values, never
resolved by picking one.
*Pinned by* `tests/test_transmission_modes.py`,
`tests/test_transmission_conflicts.py`.

## 6. Thermal and mechanical properties

Units are taken from the workbooks' own headers or description sheets, and
the importer refuses a workbook whose unit text changes. Where a workbook
gives Young's modulus, shear modulus and Poisson's ratio, E = 2G(1 + ν) is
checked on every row.
*Pinned by* `tests/test_maker_xlsx.py`.

## Not validated

* LZOS, Corning and the IR / polymer makers come from a third-party mirror
  of unknown date (no current public catalog was found); only check 1
  applies, and the UI labels them.
* refractiveindex.info crystal pages are literature measurements and are
  shown as such, with their citation.
