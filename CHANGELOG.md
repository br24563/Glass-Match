# Changelog

All notable changes to GlassMatch. This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); data-only releases bump
the patch version, schema/format changes bump the minor version.

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