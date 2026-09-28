# Changelog

All notable changes to GlassMatch. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); data-only releases bump
the patch version, schema/format changes bump the minor version.

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