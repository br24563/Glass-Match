# Changelog

All notable changes to GlassMatch. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); data-only releases bump
the patch version, schema/format changes bump the minor version.

## [Unreleased]

### Added
- **`validate_spectral_nk_frame()`** — `spectral_nk.csv` was the one data file
  with no validator at all: `validate_property_frame`,
  `validate_glass_frame` and `validate_transmission_frame` all existed, but
  `data/normalized/spectral_nk.csv` (135,347 rows) was never checked. It now
  reports non-numeric or out-of-range n/k, extinction coefficients below zero
  (20 rows, both from `RII-AL2O3-QUERRY` variants of Querry 1985), out-of-range
  wavelengths, missing `source_id`, and duplicate/conflicting samples at one
  wavelength. Per the module's rule it flags only: nothing is merged, dropped
  or corrected. Complementary rows — n held in one row, k in another — are
  legitimate for that table and are *not* reported as duplicates.

### Changed
- **README's database table no longer over-counts (1,657 → 1,596).** The
  mirror row named seven makers that total 1,596 in `glasses.csv`, not
  1,657: the 61-glass IR bucket was counted twice (once there, once in its
  own row), so the rows summed to 2,782 while the Total row said 2,721.
  Every other claim in that row was checked and is correct (2,721
  glasses/ids, 18 makers, 220 sources, 710 verified curves, 1,872 archived,
  139 curve-less, 195 crystal pages, 64k transmission rows, 135k n/k
  samples). A guard in `tests/test_repo_layout.py` now pins each row to the
  `manufacturer_id`s it names and the Total row's inline claims to the
  shipped CSVs, so the counts cannot drift again.
- **`ruff` is now a declared dev dependency and the repo carries its config.**
  `ruff>=0.6.0` was added to `requirements-dev.txt`; `ruff.toml` selects the
  rules that catch real defects (`E4`/`E7`/`E9`, Pyflakes `F`, and `BLE`
  blind-except) plus the families the codebase already documents inline with
  `# noqa: ... - reason`, and ignores `E402` in `scripts/` where `sys.path`
  must be bootstrapped before the package can be imported. With that config
  `ruff check .` passes; the fix list was 8 unused imports, 1 unused
  variable, 1 ambiguous name (`l`), one `== False` comparison, the `F821` /
  `F811` defects below, and a now-sorted `__all__` (`curated_equivalents`
  was exported but missing from it). The stylistic families (`I001` import
  order, `RUF059` unused unpacked variables, ...) are deliberately **not**
  enabled: they would rewrite most files without changing behaviour, which
  should be its own reviewable decision rather than a side effect of adding
  a linter.
- **The transmission precedence chain moved out of `app.py` into
  `glassmatch/transmission.py`.** `n_at()`, `transmission_estimate()` and
  `band_transmission()` were module-level functions in the Streamlit script, so
  testing them meant importing `app.py` — which executes the whole UI and loads
  the full database (measured: 202 s) for one assertion. The chain now takes
  `db`, `t_groups`, `nk_groups` and `thickness_mm` as arguments instead of
  reading globals; `app.py` keeps a four-line adapter that binds them to what
  the sidebar is holding, so the UI behaviour is unchanged. The contract was
  characterized *before* the move by extracting the three functions from the
  shipped `app.py` with `ast` (22/22 checks against the real source text, not a
  copy) and is pinned afterwards by `tests/test_transmission_precedence.py`
  (11 tests, 5.8 s). The precedence itself is unchanged: manufacturer rows
  first; manufacturer rows that exist but cannot answer the requested mode
  report *missing* rather than falling through to an estimate; tabulated n/k
  second; uncoated Fresnel last.

### Fixed
- **Removed unreachable code in `glassmatch/importers/refractiveindex_yaml.py`.**
  Five lines after the importer's final `return` referenced undefined names
  (`coeffs`, `n`, `lam_um`, `first`) — dead, but exactly the kind of leftover
  that becomes a `NameError` the moment someone edits above it. Found by ruff
  (`F821`).
- **Removed a duplicate test definition in `tests/test_repo_layout.py`.**
  `test_the_guard_detects_a_missing_declaration` was defined twice in the
  same module, so only the second ever ran and the first was silently
  discarded, Python keeping the later binding. The two bodies were identical
  in assertions; the duplicate is gone (`F811`).
- **`glassmatch/spectra.py` section headers now describe the code under
  them.** The module's only banner promised "Manufacturer transmission rows"
  directly above `transmission_from_nk()`/`band_stats_nk()` — which read
  `spectral_nk.csv`, not `transmission.csv`. Each of the four sections
  (Sellmeier dispersion, Fresnel estimate, calculated-from-n/k, manufacturer
  rows) now carries a header saying what it actually computes.

- **`GlassDatabase.n_at()` no longer crashes whenever a crystal has no stored
  reference row at the requested wavelength.** The n/k interpolation branch
  built its points list with `list(zip(wavelengths, n_values, None))`; zipping
  with `None` raises `TypeError: 'NoneType' object is not iterable` before any
  interpolation happens, and `_interp` expects `(wavelength, n)` pairs and reads
  column 1. Because `app.py` called `n_at` from inside the candidate-matching
  loop and swallowed the error, an off-grid wavelength silently turned every
  chalcogenide crystal into a `n = unavailable` candidate: in the shipped data
  124 of the 141 tabulated-nk materials raised on *every* off-grid request,
  including the default d-line, and were scored as having no index at all
  rather than an interpolated one. `_interp` now returns the `(wavelength, n)`
  rows it is documented to take, so the value comes back labelled
  `"interpolated"`, and requests outside the tabulated window still return
  `(None, "unavailable")` instead of an invented number. Guarded by
  `tests/test_n_at_interpolation.py`, which pins an in-range value against a
  hand-computed linear interpolation, sweeps every material with tabulated n/k
  through `n_at` and asserts it never raises, and drives the matching table and
  the Glass Detail tab through `AppTest` at 700 nm to prove the UI path really
  consumes the fix. The first draft of the sweep passed against the unfixed
  code, because it only looked at the *label* — which `except TypeError` turns
  into `"unavailable"` — so it now asserts `n is not None` as well.
- **The spectral n/k index no longer drops samples when n and k are stored as
  separate rows at the same wavelength.** `_spectral_nk_index()` built a dict
  keyed on wavelength, so the second row at a wavelength overwrote the first:
  on `RII-SI-GREEN-1995` (a reference page that publishes n and k as two
  tables) 76 of 121 n-samples vanished, and the material looked tabulated only
  from 1.01 µm to 1.45 µm when it actually spans 0.25 µm to 1.45 µm. Both rows
  are now merged into one sample. Where two rows carry *different* values for
  the same quantity at the same wavelength — `RII-AL2O3-QUERRY` has two such
  samples, e.g. n = 5.5394 and 5.5073 at 2.9499 µm — an index can only serve
  one of them, so the first row wins **and the disagreement is reported**
  rather than absorbed: `validate_spectral_nk_frame()` is new in
  `glassmatch.validation`, and the Data quality report now has a
  "Spectral n/k flags" column. Guarded by `tests/test_spectral_nk_index.py`
  (8 tests, all of which fail against the previous index) and by
  `tests/test_validation.py`, which pins the exact set of conflicting samples
  so a re-import cannot quietly add another.

## [0.6.2] - 2026-09-28

### Fixed
- **`PyYAML` is now declared in `requirements.txt`.** It was never in the
  requirements, and it is not only an importer-time dependency:
  `GlassDatabase.n_at()` imports `refractiveindex_yaml` *inside the function* to
  interpolate crystal n, so a fresh clone raised `ModuleNotFoundError: No module
  named 'yaml'` the moment a user opened a crystal glass and asked for its index
  at a wavelength. The gap was invisible in development because the local venv
  had acquired PyYAML as a side effect of the screenshot-capture tooling -
  `pip show pyyaml` reported `Required-by:` (empty), i.e. a stray top-level
  install. CI caught it; a clean `git clone` + `pip install -r requirements.txt`
  reproduces it exactly.

### Added
- **Dependency guard** (`tests/test_repo_layout.py`): AST-walks the repository,
  builds the transitive import graph reachable from `app.py` — including
  function-local imports, which is how PyYAML hid — and asserts every
  third-party module reached is declared in `requirements*.txt`. The analysis
  is itself tested, because the first version of it could not fail: it skipped
  every token containing `=` (discarding all pinned requirements) and matched
  comment prose, since a bare `-` normalises to `""` and `""` is a substring of
  every string.

## [0.6.1] - 2026-09-28

### Added
- **`formula 2` dispersion fits are now evaluated** (16 more materials, 16 more
  crystal pages, 179 -> 195). Like `formula 1` the coefficient list is
  interleaved, but each C is already in um^2 and must **not** be squared.
  Pinned against N-BK7's published spectral-line indices, where squaring
  returns 1.50723 at the d-line instead of 1.51680.
- **`GlassDatabase.n_at()` no longer extrapolates a fit past the range its
  source declares.** A refractiveindex page states its own `wavelength_range`
  and the `.agf` catalogs carry their LD wavelength limits; a request outside
  that window now returns "unavailable". Concretely: Malitson's CaF2 fit
  answers 9.7 um (its stated limit) and declines 10 um, where the formula
  would otherwise have produced a perfectly smooth, entirely invented 1.2996.

### Changed
- `tests/test_refractiveindex.py` gains a module-scoped `db` fixture, matching
  `tests/test_crystals.py`, so the 2,705-material database is loaded once per
  module instead of once per test.

### Fixed
- The `0.6.0` changelog entry listed `formula 2` as unimplemented; it is not.

## [0.6.0] - 2026-09-27

### Added
- **Crystal materials** (179 pages, 17 compounds) via the refractiveindex.info
  database, which is public domain under **CC0 1.0** and therefore - unlike the
  manufacturer `.agf` catalogs - committed to the repository with the
  normalized rows derived from it. Covers the transmissive crystals and
  semiconductors that UV/mid-IR/far-IR systems are actually built from and
  that the glass catalogs omit entirely: CaF2, MgF2, BaF2, SrF2, LiF, LaF3,
  sapphire (Al2O3), fused silica / quartz (SiO2), spinel (MgAl2O4), YAG, ZnSe,
  ZnS, Ge, Si, CdTe, GaAs, Te.
- `data/normalized/spectral_nk.csv` - 135,347 tabulated optical-constant samples
  (wavelength, n, k) stored verbatim with per-row source. The largest table in
  the database.
- `n_at_reference` properties at the standard lines (0.4861 / 0.5876 / 0.6563 /
  1 / 2 / 3 / 4 / 5 / 8 / 10 / 12 um), each labelled `calculated` when it came
  from a dispersion fit and `interpolated` when it came from a table.
- `GlassDatabase.n_at(glass_id, wavelength_nm)` and `spectral_nk_for()`.
  Crystals have no n_d/V_d, so the Glass Detail page now offers a reference
  wavelength control and reports the basis of the number; where no source
  covers the wavelength it says so and extrapolates nothing.
- Spectral tab plots tabulated n(λ) verbatim for crystals, labelled as source
  measurements rather than fits.
- `scripts/fetch_refractiveindex.py` (pinned manifest with SHA-256 per file)
  and `scripts/merge_refractiveindex.py --dry-run`.
- 19 new tests.

### Fixed
- **A merge helper destroyed 19,904 property values.** Filtering with
  `old[~old[list_of_cols].astype(str).isin(keys)]` builds a boolean *DataFrame*,
  and `frame[boolean_frame]` selects **columns**, not rows. The result had no
  columns, so concatenating it left the correct row count with every value
  null. Caught by the existing provenance tests, recovered from git, and now
  covered by `test_upsert_preserves_existing_rows`.
- **Operator-precedence bug in the new `n_at` lookup.** `&` binds tighter than
  `<` in Python, so `a & b & (c - w).abs() < tol` parsed as
  `(a & b & (c - w).abs()) < tol` - comparing a boolean Series against a float -
  and matched 21,264 of 21,272 rows instead of one, returning NaN indices.
  Clauses are now parenthesised explicitly and `test_n_at_returns_exactly_one_
  reference_row` guards it.

### Notes
- The upstream `formula 1` coefficient layout is **`[T, B1, C1, B2, C2, ...]` -
  interleaved, with each C a resonance *wavelength* that must be squared.**
  Reading it as grouped B's then C's returns a smooth, plausible-looking curve
  that is simply not the material (CaF2 came out at 1.258 instead of 1.434).
  Verified against the published Malitson constants: the squared C values are
  0.00252643 / 0.01007833 / 1200.55597 and the fit returns n(587.6 nm) =
  1.43385 against a published 1.43376. Pinned by
  `test_rii_formula_is_interleaved_and_squares_c`.
- `tabulated n2` is **non-linear** index (~1e-20), not n squared; 88 such blocks
  are skipped rather than misread. `formula 4/5/7` (30 blocks) are not
  implemented - the equations are not in the data files, and guessing them
  would be fabrication, so those materials report no index rather than a
  wrong one.
- Every crystal row cites the specific paper it came from (e.g. CaF2
  n_d = 1.43385 <- Malitson, *Appl. Opt.* 2, 1103 (1963), DOI
  10.1364/AO.2.001103), carried through `sources.csv`.

## [0.5.0] - 2026-09-27

### Added
- **N-term Sellmeier support.** `sellmeier.csv` now carries `B1..B5` /
  `C1_um2..C5_um2` and `n_terms`. Previously only the first three (B, C) pairs
  were stored, so a genuine 4-term fit (NIKON NIFS-V) was silently truncated
  into a wrong 3-term curve. 2-, 3-, 4- and 5-term fits are all evaluated now.
- Manufacturer `GC` comments and any coefficients beyond the stored term limit
  are folded into the glass `description` instead of being collected and thrown
  away — **1,037 glasses regained their catalog comment**.
- `tests/test_dispersion_terms.py` (10 tests) covering term storage, the n_d
  gate, negative-C fits, and that surplus coefficients are recorded.

### Changed
- The dispersability gate is now stated in terms of what it measures: a `CD`
  row is dispersable **iff it reproduces the catalog n_d at 587.6 nm to within
  0.002**. Rows that fail are labelled
  `Non-dispersable (...) - archived, never evaluated` with the measured
  discrepancy in the label. 653 of 2,526 glasses are dispersable.
- An intermediate revision of this work added a second gate rejecting any term
  with `B <= 0` or `C <= 0`, on the theory that Sellmeier resonance terms are
  positive. **That was wrong and was reverted**: OHARA ships genuine 3-term
  fits with a negative C (S-BSL7 has `C2 = -1.18e-2 um^2`) that reproduce n_d to
  1e-5. The rule silently stripped dispersion from S-BSL7, S-FPL51/52/55,
  S-LAL14/18, S-PHM52/53 and the entire IR and polymer sets. The sign pattern is
  now recorded as an observation, never used as a verdict.

### Notes
- 1,853 glasses carry `CD` rows in a series/polynomial form rather than a
  Sellmeier fit. They are stored verbatim and never evaluated. Identifying those
  forms would need vendor formula documentation; guessing one would be
  fabrication, so GlassMatch reports them as unavailable instead.
- Seven IR materials (AgCl, CdTe, Silicon, ZbLA, ZbLAN, ZnSe, LightPath
  ECO550-E) have valid Sellmeier coefficients but a placeholder `n_d = 2.0` in
  their catalog, so the gate correctly refuses them. Their curves are available
  in the source catalogs.

## [0.4.0] - 2026-09-27

### Fixed
- **Density was being discarded for ~700 glasses that publish it.** The `.agf`
  `ED` record carries CTE(-30/+70), CTE(20/+300), density and dPgF, and the
  importer gated *density* behind the two CTE fields:

  ```python
  if 0 < nums[0] < 30 and 0 < nums[1] < 30 and 1.5 <= nums[2] <= 9.0:
      # stored cte AND density together
  ```

  A vendor that leaves a CTE slot at `0.0` (meaning "not published") therefore
  lost its density as well. CDGM (`ED 0.000000 8.200000 2.300000 ...`), HIKARI
  and NIKON (`... 0.000000 4.970000 ...`) all lost valid measurements this way,
  while their *other* CTE slot was often populated - which is why density and
  CTE coverage had been suspiciously identical at 989 glasses each. Each field
  is now gated on its own, so a missing CTE is reported missing instead of
  costing an unrelated measurement.
- **Density plausibility is now judged per material class.** A single global
  range was wrong in both directions: it rejected real polymer densities
  (TOPAS 1.02, ZEON 0.95, ARTOn 1.08) as "not glass", while the importer
  allowed up to 9.0 where the validator stopped at 8.0, so a value could be
  imported and then flagged. `DENSITY_RANGES_BY_CLASS` in `validation.py` is
  the single source of truth shared by importer and validator.
- **Removed dead, mislabelled TD parser.** `_td_block` mapped the Zemax `TD`
  record to `cte`/`tg`/`k_thermal`, which is wrong — `TD` is a thermal dn/dT
  polynomial, and both its CTE labels pointed at the *same* `cte` key, so it
  could have written two CTE rows for one glass. It was never called: the live
  dispatch path already records `TD` as "not parsed". Deleted rather than
  repaired, since inventing a mapping for an unverified polynomial is exactly
  what this project must not do.

### Added
- **`cte_20_300` property** (1,174 glasses, 46.5%). CTE(20/+300 C) is a
  distinct quantity from CTE(-30/+70 C) and is now stored separately rather
  than dropped or collapsed into `cte`. Vendors publish one or the other, not
  both, which is why coverage differs.
- **Orphan `glass_id` check** in the Data Quality report. Property rows
  pointing at a glass absent from `glasses.csv` are invisible in the UI — no
  glass page exists to surface them — so they are now counted and listed
  alongside the existing orphan-`source_id` check. Verified 0 today.
- `tests/test_agf_ed_fields.py` (14 tests) locks in the per-field gating: the
  exact CDGM/HIKARI/NIKON record shapes, per-class density acceptance, and that
  a glass never gets two `cte` rows.

### Changed
- **Data coverage after re-importing all 17 catalogs:**

  | property | before | after | coverage |
  |---|---|---|---|
  | density | 989 | **2,261** | 39.2% → 89.5% |
  | cte | 989 | **2,068** | 39.2% → 81.9% |
  | cte_20_300 | — | 1,174 | 46.5% |

- **Equivalency candidates are better founded.** 715 glasses (NIKON, HIKARI,
  CDGM, LZOS) previously had no density or CTE to compare, so pairs qualified on
  n_d/V_d alone. Density is now actually tested for them: 2,287 candidate
  pairs share all four properties, and N-BK7's top matches (OHARA BSL7Y,
  HIKARI J-BK7, NIKON J-BK7, CDGM H-K9L) now carry real Δdensity/ΔCTE
  deltas instead of blanks. Total pairs move 7,232 → 5,828: fewer, but every
  one is supported by more evidence.
- All data-quality checks still report 0 flags, including the new orphan-glass
  check and the widened density rule.

## [0.3.3] - 2026-09-25

### Fixed
- **Displayed transmission carried binary-float noise.** The Glass Detail
  caption rendered `98.49999999999999%`, because a band mean of binary floats
  was interpolated straight into an f-string. Percentages are now rounded to
  one decimal where they are produced, so the results table, the detail caption
  and the CSV/JSON exports can no longer disagree. Covered by
  `tests/test_display_rounding.py`, which first reproduces the noise and then
  asserts the rounded value, checks that provenance labels are unaffected, and
  checks that a mode which cannot be satisfied still reports missing rather
  than a rounded zero.

### Changed
- **Transmission quality report: 114 flags to 0.** All were byte-identical
  duplicate rows (same glass, wavelength, thickness *and* value), so collapsing
  them loses no information. Deduplication now happens in the importer and is
  recorded per source in `data/normalized/transmission_dedup.csv`. The two
  mechanisms stay deliberately separate: dedupe removes rows that say the
  *same* thing twice, while conflict quarantine keeps rows that *disagree* and
  records the disagreement for review.
- Screenshots regenerated against the current UI, including a fifth shot of the
  equivalency finder. `scripts/capture_screenshots.py` gained per-shot scroll
  anchors and a taller viewport, so each frame shows real ranked results rather
  than a section header. Reviewing those frames is what exposed the float-noise
  bug above.

### Added
- `.gitattributes` normalising line endings in the repository (LF) while
  checking out `.bat` launchers as CRLF, so Windows/macOS/Linux checkouts do not
  produce whole-file diffs or disagree about line endings.

## [0.3.2] - 2026-09-25

### Fixed
- **CI was failing on every run** (`Interrupted: 12 errors during collection`,
  exit code 2) while passing on Windows. Two independent causes, both fixed:
  1. `tests/fixtures/demo.agf` was never committed: a blanket `*.agf` rule in
     `.gitignore`, added to keep redistribution-limited manufacturer catalogs
     out of the repo, also excluded the synthetic test fixture the suite
     depends on. The rule is now scoped to `data/manufacturers/**`, and the
     fixture is tracked.
  2. `import glassmatch` only resolved when the invocation directory happened
     to be the repo root. The `pytest` console script does not add the current
     directory to `sys.path` (unlike `python -m pytest`), so on Linux CI every
     test module failed to import. `pytest.ini` now pins rootdir and sets
     `pythonpath = .`, and CI runs `python -m pytest`.
- Smoke-test timeout raised 180 s -> 300 s to match the app's real startup cost
  on a cold runner cache.

### Added
- `tests/test_repo_layout.py`: guards against this class of failure - asserts
  required fixtures and committed data files exist, checks the fixture is a
  small synthetic catalog with documented provenance, and fails if any
  manufacturer catalog is tracked outside `tests/fixtures/`.
- CI step enforcing the redistribution policy: no `.agf` outside
  `tests/fixtures/` may be committed.

## [0.3.1] - 2026-09-25

### Added
- `find_transmission_conflicts()` / `split_transmission_conflicts()` in
  `glassmatch/validation.py`: the single source of truth for detecting samples
  where one (glass, wavelength, thickness) key carries more than one value.
- `data/normalized/transmission_conflicts.csv`: quarantine ledger holding all
  60 conflicting keys with **both** values, the spread, the source id and the
  reason. No value is chosen or discarded.
- `scripts/clean_transmission.py` (with `--dry-run`) migrates the shipped data.
- Data Sources tab: "Quarantined transmission samples" metric and table. The
  report also re-derives conflicts from the live table, so a user import that
  reintroduces one can never hide behind a clean ledger.

### Changed
- The `.agf` importer now quarantines conflicting samples at import instead of
  writing them to the database, and emits an issue per quarantined key.
- `transmission.csv`: 64,033 -> 63,913 rows. Transmission quality flags in the
  UI: 234 -> 114.

### Fixed
- Conflict counting renamed its aggregate before the key merge; it previously
  collided with the value column and raised `KeyError: '_v'`.
- The quarantine mask uses tuple keys instead of a merge/indicator round-trip,
  which broke on frames with a duplicated index.

## [0.3.0] - 2026-09-25

### Added
- `glassmatch/equivalency.py`: cross-manufacturer substitution finder. Computes
  candidate pairs from n_d, V_d, density, CTE and T_g, with a k-d tree over
  gate-scaled (n_d, V_d) coordinates so the search stays local as the catalog
  grows. ~7,200 candidate pairs across the committed 2,526-glass database.
- Database explorer: "Equivalency candidates" section with live tolerance
  sliders (|Δn_d|, |ΔV_d|, |Δdensity|), pair counts, CSV export, and a filter
  for pairs already present in `equivalents.csv`.
- Glass detail: "Cross-manufacturer substitutions" showing curated pairs
  (source-backed) and computed candidates side by side, each individually
  labelled.

### Integrity
- Candidates are **never merged** into the database and are always labelled
  `unverified`. Curated pairs in `equivalents.csv` are tagged `curated` and are
  never overwritten or mutated by the engine. Every candidate row carries the
  deltas and the count of properties actually compared.

### Fixed
- Pair de-duplication now normalizes pair orientation instead of filtering on
  `glass_id_a < glass_id_b`, which silently discarded every pair whose catalog
  order disagreed with alphabetical order (N-BK7 had 20 qualifying candidates
  and showed none).
- The per-glass candidate cap is rank-based rather than slot-count based, so a
  crowded glass can no longer consume every slot and starve quieter glasses of
  their best match.
- 19 new tests covering gating, orientation, delta signs, missing data,
  determinism, cap behaviour and curated/candidate separation.

## [0.2.0] - 2026-09-24

### Added
- GitHub Actions CI: pytest on Python 3.11 + 3.12, plus an app-import smoke test
  (`AppTest`) that boots `app.py` and asserts zero exceptions.
- Issue templates (bug report, data contribution) and a PR template with a data
  integrity checklist.
- `CHANGELOG.md` and a version string in the app header
  (`GlassMatch v0.2.0 | N glasses | N manufacturers | N sources`).
- `CONTRIBUTING.md`: the full add-a-manufacturer / add-a-glass workflow.

### Fixed
- `start.bat`: a half-built `.venv` (corrupted pip, e.g. after a OneDrive sync
  interrupted creation) caused an unrecoverable "dependency install failed". The
  launcher now health-checks pip and recreates the environment automatically.
- `start.bat`: prefer Python 3.12/3.11 over the 3.x fallback (which resolved to
  3.14, not yet supported by Streamlit), and pass `--seed` to `uv venv` so
  uv-created environments actually contain pip.

## [0.1.0] - 2026-09-23

Initial public release.

### Data
- 2,526 glasses across 17 manufacturers, 25 traceable sources.
- SCHOTT `.agf` bulk import (June 2025 catalog) and OHARA (May 2026 catalog)
  from official manufacturer downloads; the remaining catalogs from a
  third-party Zemax mirror, individually labelled as mirror data of
  unverified vintage.
- 64k transmission samples, Sellmeier/Buchdahl coefficient archive, user-import
  template.

### Application
- Streamlit UI: matching, glass detail with provenance, spectral analysis,
  comparison, database explorer, data sources + quality report, import/export.
- Transparent, weight-normalized compatibility scoring with per-property
  sub-scores and explicit missing-data handling.
- Mode-aware transmission (average / minimum / entire range) evaluated against
  manufacturer internal-transmittance rows, with calculated Fresnel fallback.
- IR material mode: Abbe weighting redistributed for materials where V_d is
  not meaningful.
- Non-Sellmeier gating: only verified Sellmeier-1 rows are ever evaluated into
  dispersion curves; polynomial and legacy forms are archived, never guessed.
- Data quality report: range, duplicate, transmission-conflict and
  orphan-source checks surfaced in the UI (flagged, never silently corrected).

### Tooling
- `.agf` importer (UTF-8/UTF-16, multi-line polynomial records, nd-vs-Sellmeier
  cross-check), generic CSV importer, `scripts/merge_agf.py` (idempotent),
  `scripts/capture_screenshots.py`.
- 45 automated tests.
