# Changelog

All notable changes to GlassMatch. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); data-only releases bump
the patch version, schema/format changes bump the minor version.

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