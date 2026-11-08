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
stored n_d / V_d equals the value in its source file, with one documented
exception: where the maker's own data workbook contradicts its `.agf` and the
glass's dispersion fit independently reproduces the workbook value, the
`.agf` value is a typo and the workbook's is stored (with the `.agf` value in
the notes). Three glasses: CDGM H-TK9 (`.agf` 1.587166 / 75.90, workbook and
fit 1.62075 / 60.3), HOYA MC-TAF115 (1.777047 vs 1.77047) and HOYA MC-FAD61
(1.65494 vs 1.65451). Rounding-level V_d differences are never touched.
*Pinned by* `tests/test_formula_audit.py`, `tests/test_property_columns.py`.

## 2. Fits agree with the makers' own datasheets at every printed line

The makers' Excel data workbooks tabulate the catalog index at 15-20 spectral
lines from the i line (365 nm) to 2.3 µm, independently of the `.agf`
coefficients. `glassmatch.datasheet_check` evaluates each verified fit at
every line inside its stated range and compares. The workbooks print 5 or 6
decimals, so agreement to a few 10⁻⁶ is the expected result; the largest
differences sit at the UV end of a fit's range, where fits are least
constrained.

<!-- crosscheck:begin -->

Generated 2026-11-02 by `scripts/validate_against_datasheets.py`.

| Datasheet | Maker | Glasses | Lines per glass | Within 2e-05 | Median max \|Δn\| | Worst \|Δn\| |
|---|---|---|---|---|---|---|
| CDGM-XLSX-2026-09 | CDGM | 336 | 17 | 323 | 1.1e-06 | 4.8e-05 |
| HOYA-XLSX-2026-04-01-MIRROR | HOYA | 238 | 17 | 238 | 4.8e-06 | 7.0e-06 |
| OHARA-L-XLSX-2025-03-12 | OHARA | 17 | 20 | 17 | 4.9e-06 | 5.4e-06 |
| OHARA-SPECIAL-XLSX-2025-03-12 | OHARA | 14 | 20 | 14 | 5.0e-06 | 5.5e-06 |
| OHARA-XLSX-2026-04-02 | OHARA | 130 | 20 | 130 | 4.9e-06 | 6.8e-06 |
| SCHOTT-XLSX-2025-11-13 | SCHOTT | 156 | 18 | 140 | 4.9e-06 | 3.8e-05 |

**891 glass/datasheet pairs, 862 (96.7%) within 2e-05 at every line; worst 4.8e-05.**

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

SCHOTT's data workbook also tabulates absolute dn/dT at the e and g lines and
1060 nm (+20/+40 °C). Computed from the same glasses' `.agf` TD coefficients,
all 461 values agree within 0.1×10⁻⁶/K (median 0.03; SCHOTT prints one
decimal).
*Pinned by* `tests/test_property_columns.py`.

## 5. Transmission

Internal transmittance is compared at one sample thickness, converted from
each catalog's listed thickness by Beer-Lambert, and labelled as scaled.
Duplicate samples that disagree are quarantined in
`data/normalized/transmission_conflicts.csv` with both values, never
resolved by picking one.

**Placeholder blocks are not data.** A Zemax catalog with no transmittance for
a glass still writes an IT block whose every sample is exactly 1.0 (14 default
wavelengths 0.334-1.06 um at 25 mm, or 0.29 um upwards at 10 mm in Nikon's
file). Read as measurements they claimed 100 % internal transmittance - for
germanium and silicon at 0.4 um. Such blocks are dropped at import and
reported: 293 glasses (148 HOYA, 61 OHARA, 44 INFRARED mirror, 20 HIKARI,
14 Corning, 3 LightPath, 2 RPO, SCHOTT B270), 48 of them not obsolete, now show
transmission as missing. Blocks that mix 1.0 with other values are measured
data and kept. *Pinned by* `tests/test_agf.py`.

A glass with no measured transmittance and no tabulated n/k has only the
uncoated Fresnel reflection loss from its dispersion fit. That ignores
absorption, so it is an upper bound, not a transmittance - over 9-10 µm it
gave LiF 99 % and CaF₂ 96 %, both absorbing there - and it is never used as
a transmission value: the glass is missing, with the bound in its basis
(60 glasses over 400-700 nm, 22 over 9-10 µm).
*Pinned by* `tests/test_transmission_modes.py`,
`tests/test_transmission_conflicts.py`.

## 6. Thermal and mechanical properties

Units are taken from the workbooks' own headers or description sheets, and
the importer refuses a workbook whose unit text changes. Where a workbook
gives Young's modulus, shear modulus and Poisson's ratio, E = 2G(1 + ν) is
checked on every row.
*Pinned by* `tests/test_maker_xlsx.py`.

## 7. Derived figures

Columns marked "(calculated)" (`glassmatch/derived.py`) are computed from the
data above, never extrapolated: dispersion figures only inside a fit's stated
range, transmission figures only between listed samples. Checks:

* **UV edge.** The wavelength where internal transmittance reaches 80 % and
  5 % at 10 mm, interpolated from the IT samples, against the makers'
  published *internal* colour codes (HOYA λτ80/λτ5, OHARA λ0.80/λ0.05, HIKARI
  internal CC): 518 glasses, median difference 0.3 nm, 99 % within 5 nm.
  (Most published colour codes - λ80/λ5 - are total transmittance including
  surface reflection, a different quantity, and are stored separately.)
* **Line indices and partial dispersion.** N-BK7: n_e 1.51872, V_e 63.96,
  P_g,F 0.5349, ΔP_g,F −0.0009 - SCHOTT's catalog values.
* **Group-velocity dispersion.** At 800 nm: N-BK7 44.65 fs²/mm, group index
  1.5266; fused silica 36.16 fs²/mm - the standard reference values.
* **Thermo-mechanical figures** (athermal γ = (dn/dT)/(n−1) − α in air with
  relative and in vacuum with absolute dn/dT, thermal-shock
  FOM k(1−ν)/(αE), specific stiffness E/ρ) are arithmetic on stored values;
  their tests check the formulas against hand-computed N-BK7 figures.

*Pinned by* `tests/test_property_columns.py`.

## 8. n(λ, T, p): the dn/dT model against the makers' measured tables

Every maker with a data workbook also tabulates the dn/dT it measured, per
line and per 20 K interval: 116,639 values for 1,031 glasses
(`dn_dt_measured.csv`, `scripts/merge_dndt.py`; SCHOTT, HOYA and HIKARI
relative and absolute, OHARA and CDGM relative). `scripts/validate_dndt.py`
evaluates the SCHOTT dn/dT model from each glass's own TD record over the
same interval - absolute, or relative to air via the Edlén air index - and
compares, for every value inside the model's stated validity (−100 … +140 °C,
365 … 1014 nm). The makers print one decimal, so ±0.05×10⁻⁶/K is agreement
to the printed precision.

| Source | basis | glasses | values | within 0.05 | within 0.2 | median | p95 | max |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| SCHOTT 2025-11-13 | absolute | 154 | 921 | 99.2 % | 99.8 % | 0.025 | 0.048 | 1.47 |
| SCHOTT 2025-11-13 | relative | 154 | 921 | 99.2 % | 100 % | 0.026 | 0.048 | 0.06 |
| OHARA 2026-04-02 (S) | relative | 130 | 14,300 | 74.2 % | 100 % | 0.029 | 0.080 | 0.16 |
| OHARA 2025-03-12 (L) | relative | 17 | 1,870 | 74.7 % | 100 % | 0.030 | 0.080 | 0.12 |
| OHARA 2025-03-12 (special) | relative | 14 | 588 | 81.5 % | 100 % | 0.027 | 0.075 | 0.16 |
| HOYA 2026-04-01 | absolute | 236 | 14,436 | 91.2 % | 95.3 % | 0.027 | 0.182 | 2.97 |
| HOYA 2026-04-01 | relative | 236 | 14,436 | 87.7 % | 95.3 % | 0.027 | 0.173 | 3.05 |
| CDGM 2026-09 | relative | 318 | 17,112 | 39.0 % | 90.6 % | 0.067 | 0.264 | 3.90 |

(differences in 10⁻⁶/K.) That SCHOTT's own tables are reproduced to the
printed digit, in both bases, checks the implementation of the model and of
the air index together. HIKARI's measured glasses have no TD record in the
current workbook, so there is nothing to compare; HIKARI tabulates both bases,
and converting one into the other with the air model reproduces it
(`tests/test_thermal.py`).

The large differences are real disagreements between a maker's TD
coefficients and its own table, concentrated in a few glasses (CDGM ZF50,
ZF10 and F13 below −20 °C; HOYA NBFD13 at the h line above 80 °C). GlassMatch
does not choose between them silently: n(λ, T) uses the model inside its
validity and adds a note whenever the maker's table over the same span
differs by more than 0.5×10⁻⁶/K.

How n(λ, T, p) is formed and what it refuses is in `glassmatch/thermal.py`:
the catalog index (relative, at the TD record's T0) → absolute via the air
index → the model's Δn, or the maker's table summed over its intervals when
the model is out of range (e.g. OHARA at 1550 nm) → relative to air at T and
p. Nothing is extrapolated: no index below −100 °C (cryogenic data is not
in the database), none at a wavelength neither source covers, and no absolute
n(T) for the 162 measured-only glasses whose catalogs do not state their
reference temperature (their dn/dT, and so their thermal focus shift, is
given).
*Pinned by* `tests/test_thermal.py`, `tests/test_dndt_import.py`.

### Crystals measured at several temperatures (cryogenic use)

Some literature pages are one author's measurement of a crystal at several
stated temperatures: Si (Franta 10-500 K, Li 100-750 K), Ge (Li 100-550 K),
CdTe (DeBell 20-300 K), BaF2 / CaF2 / SrF2 (Bosomworth 5-300 K) and others. For
a page of such a series, n(lambda, T) is the measured index at a measured
temperature and linear in T between the two bracketing measurements - never
beyond the coldest or warmest one, and never from thin-film series. The
index is as the source publishes it (cryostat measurements are normally in
vacuum; the basis is not converted). Checks (`tests/test_cryo.py`): Ge at
10 um gives dn/dT ~4.06e-4/K near room temperature (literature ~3.96e-4/K);
silicon's dn/dT falls on cooling, 1.30e-4/K at -100/-50 C against ~1.6e-4/K at
room temperature. This is the only cryogenic data GlassMatch holds; catalog
glasses still stop at -100 C (the dn/dT model's stated range).

## 9. Paraxial lens engine

`glassmatch/lens.py` traces a y-nu marginal ray. It is checked against closed
forms, not against itself (`tests/test_lens.py`):

* thick singlet: EFL, BFL and Petzval sum equal the lensmaker's equation to
  1e-12 (relative);
* thin cemented achromat designed from the catalog V_d: EFL exactly as
  designed, F−C focus difference below 1e-10 mm, and the d- and g-line
  secondary spectrum equal to the exact thin-lens values (the first-order
  formula −f (P₁−P₂)/(V₁−V₂) agrees to 3×10⁻⁵ mm);
* thin singlet heated 20 → 60 °C: EFL change and focus shift against the
  mount equal f(T) = f₀(1+αΔT)(n−1)/(n−1+Δn);
* the same design read from JSON, Zemax .zmx (UTF-16) and CODE V .seq in
  radius and curvature modes gives identical results.

Replacement (`tests/test_lens_replace.py`):

* element-power mode holds the replaced element's own paraxial power to
  1e-12 (relative); for an element in air its shape factor
  (c₁ + c₂)/(c₁ − c₂) is unchanged to 1e-12, and for a cemented element the
  shared surface is untouched; an element cemented on both sides is left
  as it is and says why;
* on the illustrative triplet, element mode disturbs the downstream ray
  heights no more than keeping the curvatures for >90 % of candidates;
* writing a modified design back into its .zmx (UTF-16) or .seq (radius and
  curvature modes) changes exactly the glass line, the re-solved curvature
  line and, for a new catalog, the GCAT line; reading it back gives the
  same EFL, BFL and colour to 1e-12.

It is a **first-order screen**: no aberrations beyond first order, no
tolerancing. Replacement rankings say so wherever they are shown.

## 11. IR bands: dispersion and the data behind it

**V and P for any band** (`glassmatch/band.py`): for a triad (short, mid,
long), V = (n_mid − 1)/(n_short − n_long) and P = (n_mid − n_long)/(n_short −
n_long), from verified fits or tabulated n inside their stated range. The
visible triad (F, d, C) reproduces catalog V_d to a median 4×10⁻⁷ over 2,683
glasses. In the LWIR (8/10/12 µm): ZnSe 57.8, ZnS 22.9, GaAs 103–106, Ge
785–1007 and Si ~1900, the usual published values. Left out rather than
guessed:

* thin-film pages (their constants are not the bulk material's);
* n ≤ 1 or n not falling across the triad - an absorption band (sapphire's
  reststrahlen band at 8–12 µm gave n = 0.89 and a negative V);
* tabulated n too coarse for the band: the difference n_short − n_long must
  span ≥ 100 steps of the table's printed precision and ≥ 1×10⁻⁴ - a silicon
  page printed to four decimals gave P = 5/12 exactly, and one noisy page
  V = 527,260.

**Chalcogenide fits verified against the maker** (`scripts/verify_ir_dispersion.py`):
CDGM's HWS glasses have no catalog n_d, so their Herzberger fits were archived.
CDGM's data workbook tabulates their n at 2–14 µm (sheet "infrared glass",
four decimals). All 11 fits reproduce every tabulated value within 2×10⁻⁴
(worst 1.6×10⁻⁴) and are now verified, valid over the tabulated span only.
Independently, CDGM's printed ν10.6 = (n10.6 − 1)/(n8 − n12.5) is reproduced
by the band V over the same triad within 0.3–1 % (HWS2 86.65 vs 86.65, HWS6
138.74 vs 138.77) - the spread a 2×10⁻⁴ index tolerance implies over a
denominator of ~0.017.

**SCHOTT IRG glasses** (official `SCHOTT_IRG_ZEMAX_July_2018.AGF`, the file
SCHOTT's IR downloads page links): IRG 22-27 with internal transmittance at
10 mm (178 samples). The .agf gives no catalog n_d, so its fits are checked
against the refractive-index tables of SCHOTT's IRG datasheets (n at 22 C,
0.6-12 um, four decimals; extracted by `scripts/extract_schott_irg.py` to
`data/validation/schott_irg_datasheets.csv`). IRG 22, 24 and 25 reproduce
every tabulated value within 2e-4 (worst 1.9e-4) and are verified. IRG 26
misses by 2.1e-4 and IRG 27 by 3e-3 - the IRG 27 datasheet is the September
2018 edition, newer than the July 2018 .agf - so both stay archived; IRG 23
has no datasheet. Their transmission data are used either way. The .agf's TD
constants reproduce the datasheets' dn/dT at 22 C within 0.07e-6/K (IRG 22:
0.63e-6/K).

**IR temperature behaviour.** CDGM's IR sheet tabulates relative dn/dT of the
HWS glasses as means over -40...80 C (or -20...80 C) at 4/5, 8 and 12/14 um -
29 values, now in `dn_dt_measured.csv` (the importer's sanity cap was raised
from 100 to 1000e-6/K: HWS9 is 181, germanium ~400). They give the HWS glasses
n(lambda, T), dn/dT and thermal focus shift at IR wavelengths, interpolated
linearly between the tabulated lines and never outside the interval. SCHOTT's
IRG datasheets give dn/dT only at 22 C - a point, not an interval - so the IRG
glasses still give no n(T) at IR wavelengths rather than stretch it over a span.
In band mode the pair finder's gamma uses that band-centre dn/dT and the
catalog CTE; materials missing either are left out of the athermal ranking.

**Lens analysis in any band.** The paraxial engine traces at a design band's
wavelengths (e.g. 8 / 10 / 12 um: primary 10 um, axial colour 8-12 um) as well
as at the visible F / d / C / g lines; `tests/test_ir_thermal.py` checks the
band trace equals the explicit-wavelength trace. Replacement candidates in a
band are windowed on that band's n and V (V relative, +-25 % by default) and
leave out cryogenic crystal pages and single rays of birefringent crystals.

**Pairs in a band**: the pair finder in band mode never pairs two pages of
one crystal (other author, temperature or ray), leaves out o-/e-ray pages,
and by default keeps only room-temperature measurements and materials meeting
the sidebar transmission requirement.

**Absorption from literature k needs the precision to show it.** A
transmission figure computed from tabulated k is given only when the table's
printed precision resolves the absorption over the chosen thickness: half a
step of the last printed digit may change the transmission by at most 10 %.
KCl's Querry page prints k = 0.005 at 10 µm - a reflectance measurement's
floor, implying an opaque 10 mm blank of a crystal that transmits to 20 µm;
the rule refuses it (and NaCl / CsI / CsBr from the same report, whose
"k = 0.000" cannot show transparency either). Model-generated k (oscillator
fits, many digits) is not caught by a precision test and stays labelled as
literature; in transparent windows such k is often far too high (BaF₂
"Kaiser" gives 0.2 % at 8–12 µm), so manufacturer transmission curves remain
the data to judge a window by.

**Added 2026-11-06** (refractiveindex.info, CC0): KBr, KCl, NaCl, CsBr, CsI,
AgCl, AgBr, diamond (CVD and natural pages only - the book's graphite,
graphene and nanotube pages are excluded), GaP, InP, As₂S₃ glass (not the
crystalline mineral), MgO, Y₂O₃ - 33 pages, mostly index data. Also fixed: the
Al₂O₃ "Querry" page is an "oxidized Al mirror" (a surface layer), now
classified as a film rather than as bulk sapphire.

**Still missing**: resolvable absorption data at 8–12 µm for the crystals
Ge, ZnSe, ZnS, CdTe and the alkali halides (the chalcogenide glasses now have
manufacturer curves from CDGM and SCHOTT). Their index data are verified, but a transmission
search in the LWIR shows them only from the unverified IR mirror
(*Include unverified mirrors*), so with defaults it returns the CDGM
chalcogenides (manufacturer curves), As₂S₃ glass, Si, GaAs and CVD diamond
(literature k).

## 10. Principle audit (2026-11-06)

Every computed value was swept for hidden extrapolation, mixed bases and
unlabelled calculation. Found and fixed:

| Finding | Effect before | Now |
|---|---|---|
| Athermal γ used **absolute** dn/dT | A lens in air needs relative dn/dT; γ was ~2–3×10⁻⁶/K off, the size of the residuals the pair finder ranks | `athermal_gamma_air` (relative, the default) and `athermal_gamma_vacuum`; pair finder has an air / vacuum choice. Relative d-line dn/dT is converted from the absolute value with the Edlén air index (reproduces HIKARI's own relative figures, e.g. J-BAK1 3.07 vs 3.1) |
| Thermal focus extrapolated the −30/+70 °C catalog CTE linearly | Mount / glass expansion outside the measured range, only noted | Refused by default; `--allow-cte-extrapolation` / app checkbox gives an estimate marked EXTRAPOLATED |
| Band statistics from samples that don't span the band | One sample at 1.06 µm was "the average over 0.7–1.4 µm" (436 glasses; 127 more under 50 % span) | Average and Minimum need ≥ 2 samples spanning ≥ 50 % of the band, else missing with the reason; the label states the span |
| Tabulated-n/k "Entire range" with too little coverage returned the **mean** | A claim about the whole band from partial data | Refused, as the manufacturer branch already did |
| Range filters on maker-specific classes (chemical resistance, abrasion, grindability) across makers | Different tests and scales compared as one number | A filter on these names one maker and keeps only that maker's glasses (`--where acid_resistance@OHARA=1:2`) |
| Crystal pages named by author ("Malitson", "Li-100K") | Material not visible; a 5 K or 186 °C measurement, a thin film, or one ray of a birefringent crystal looked like an ordinary room-temperature material | Material first, then author, o-/e-ray, measurement temperature and film (`Al2O3 (Malitson, o-ray)`, `Si (Li, 100 K)`); `optic_axis` column; birefringent rows are explained in the app |
| Derived-data cache keyed to data and package version only | A calculation fix kept serving tables the old code had computed until the next release | The key includes a content hash of the code |

Conventions, stated so they can be checked:

* **dn/dT tables** are interval means (SCHOTT says so; our model reproduces
  its tables that way). Summing mean × width is exact over whole intervals;
  only a span that starts or ends inside an interval is approximated (the
  interval's mean is used for the part). Between tabulated lines dn/dT is
  interpolated linearly in wavelength; never beyond the outermost lines.
* **Catalog CTEs** are all Zemax .agf ED values, defined as the −30/+70 °C
  mean. IR makers' ED values cannot be checked against a second source.
* **Thermal focus** assumes glass, mount and air at one uniform temperature.
* **Transmission "Average"** is the mean of the samples in the band (sample-
  weighted, not wavelength-weighted); with irregular spacing it leans toward
  the densely sampled part. The label gives the number of samples and span.

Open, not changed here: temperature-specific crystal pages are still separate
materials (their temperature is now in the name); using them in n(λ, T) is
cryogenic work for a later phase.

## Not validated

* LZOS, Corning and the IR / polymer makers come from a third-party mirror
  of unknown date (no current public catalog was found); only check 1
  applies, and the UI labels them.
* refractiveindex.info crystal pages are literature measurements and are
  shown as such, with their citation. Nonlinear-index (n2) measurements are
  shown verbatim, one per paper, never averaged: n2 depends on pulse duration
  and method.
* Abrasion, grindability and chemical-resistance classes are each maker's own
  scale; GlassMatch shows them per glass and does not compare them across
  makers.
