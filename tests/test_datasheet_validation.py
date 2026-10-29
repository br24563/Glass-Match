"""Tests: dispersion fits agree with the makers' own datasheets.

The workbooks are not in the repository (redistribution-limited), so CI checks
the committed sample in data/validation/reference_indices.csv - catalog index
values at every printed line for a fixed set of glasses per workbook, including
each workbook's worst case - and the committed per-glass report. Regenerate
both with scripts/validate_against_datasheets.py.
"""
from pathlib import Path

import pandas as pd
import pytest

from glassmatch.database import load_default_database
from glassmatch.datasheet_check import AGREE_TOL, line_wavelength
from glassmatch.spectra import n_from_row

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "validation" / "reference_indices.csv"
REPORT = ROOT / "docs" / "validation" / "datasheet_crosscheck.csv"
# Worst residual in the shipped data is 4.8e-5, at the UV end of a fit.
WORST_TOL = 5e-5


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def test_line_labels_map_to_wavelengths():
    assert line_wavelength("nd") == pytest.approx(0.5875618)
    assert line_wavelength("nD") == pytest.approx(0.589294)   # case matters
    assert line_wavelength("nF'") == pytest.approx(0.479992)
    assert line_wavelength("nHe-Ne") == pytest.approx(0.632816)
    assert line_wavelength("n1529.58") == pytest.approx(1.52958)
    assert line_wavelength("n2325") == pytest.approx(2.32542)   # OHARA's short form
    assert line_wavelength("ｎｇ") == pytest.approx(0.435835)    # full-width (HOYA)
    for not_a_line in ("nF-nC", "nF - nC", "νd", "Glass", None, "n"):
        assert line_wavelength(not_a_line) is None


def test_sample_covers_every_checked_maker():
    s = pd.read_csv(SAMPLE)
    assert {"SCHOTT", "OHARA", "HOYA", "CDGM"} <= set(
        s["glass_id"].str.split("-").str[0])
    assert len(s) > 500


def test_fits_reproduce_the_datasheet_sample(db):
    s = pd.read_csv(SAMPLE)
    worst = 0.0
    for gid, grp in s.groupby("glass_id"):
        fit = db.sellmeier_for(gid, sellmeier_only=True)
        assert fit is not None, f"{gid}: no verified fit"
        for wl, n in zip(grp["wavelength_um"], grp["n_catalog"]):
            d = abs(n_from_row(fit, float(wl)) - float(n))
            worst = max(worst, d)
            assert d <= WORST_TOL, f"{gid} at {wl} um: |dn| = {d:.2e}"
    assert worst > 0          # the sample is real data, not the fit itself


def test_committed_report_meets_the_documented_numbers():
    r = pd.read_csv(REPORT)
    assert len(r) > 800
    assert r["max_abs_dn"].max() <= WORST_TOL
    assert (r["max_abs_dn"] <= AGREE_TOL).mean() > 0.95
    assert (r["lines_checked"] >= 10).mean() > 0.9   # not just n_d
