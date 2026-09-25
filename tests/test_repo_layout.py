"""Repository layout guards.

A `.gitignore` rule once excluded `tests/fixtures/demo.agf` along with the
redistribution-limited manufacturer catalogs, so the fixture was never
committed and every fresh clone - including CI - failed collection with
FileNotFoundError. These tests fail loudly and early if that recurs.
"""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

REQUIRED_FIXTURES = ["demo.agf"]


@pytest.mark.parametrize("name", REQUIRED_FIXTURES)
def test_required_fixture_exists(name):
    path = FIXTURES / name
    assert path.exists(), (
        f"missing test fixture: {path}. Synthetic fixtures must be committed - "
        "check that .gitignore does not exclude tests/fixtures/.")


def test_fixture_is_synthetic_not_a_manufacturer_catalog():
    """Fixtures ship with the tests, so they must not be a real catalog dump.

    demo.agf legitimately carries N-BK7's CC0 Sellmeier coefficients (documented
    in its header) to exercise the nd cross-check. What must never happen is a
    whole manufacturer catalog being committed here, so the guard is on size and
    on the required provenance note rather than on glass names.
    """
    path = FIXTURES / "demo.agf"
    text = path.read_text(encoding="utf-8", errors="replace")
    nm_records = [ln for ln in text.splitlines() if ln.strip().startswith("NM ")]
    assert len(nm_records) <= 5, (
        f"fixture has {len(nm_records)} NM records - that looks like a real "
        "catalog dump, not a test fixture")
    assert "refractiveindex.info" in text, (
        "fixture must document the provenance of any real coefficients it uses")


def test_required_data_files_exist():
    for name in ("manufacturers.csv", "glasses.csv", "properties.csv",
                 "sources.csv", "sellmeier.csv", "transmission.csv"):
        assert (ROOT / "data" / "normalized" / name).exists(), \
            f"missing committed data file: data/normalized/{name}"


def test_no_manufacturer_catalogs_are_committed():
    """Redistribution policy: no real .agf catalog may be tracked.

    Only synthetic fixtures under tests/fixtures/ are allowed.
    """
    try:
        out = subprocess.run(["git", "ls-files", "*.agf", "*.AGF"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = [p for p in out.stdout.split() if p.strip()]
    offenders = [p for p in tracked
                 if not p.replace("\\", "/").startswith("tests/fixtures/")]
    assert not offenders, (
        "manufacturer catalogs must not be committed (redistribution-limited): "
        + ", ".join(offenders))
