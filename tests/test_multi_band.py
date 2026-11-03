"""Several wavelength bands that must all be met (e.g. 400-700 nm and
9-10 um): the combined figure is the worst band, and a band with no data
makes the glass missing rather than passing."""
import subprocess
import sys
from pathlib import Path

import pytest

from glassmatch.transmission import combine_bands


def test_single_band_is_unchanged():
    assert combine_bands([(0.4, 0.7, 91.0, "manufacturer (x)")]) == (91.0, "manufacturer (x)")


def test_worst_band_limits_and_basis_classifies():
    v, b = combine_bands([(0.4, 0.7, 91.0, "manufacturer (x)"),
                          (9.0, 10.0, 60.0, "calculated from tabulated n/k")])
    assert v == 60.0
    assert b.startswith("calculated from tabulated n/k")
    assert "limiting band 9-10 um" in b and "0.4-0.7 um: 91 %" in b


def test_missing_band_makes_glass_missing():
    v, b = combine_bands([(0.4, 0.7, 99.0, "manufacturer (x)"),
                          (9.0, 10.0, None, "missing")])
    assert v is None and b.startswith("missing") and "9-10 um" in b


def test_cli_two_bands(tmp_path):
    import pandas as pd
    root = Path(__file__).resolve().parents[1]
    csv = tmp_path / "out.csv"
    out = subprocess.run(
        [sys.executable, "-m", "glassmatch.cli", "search", "--band", "0.4:0.7",
         "--band", "9:10", "--tmin", "80", "--require-data", "--top", "5",
         "--csv", str(csv)], capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr
    df = pd.read_csv(csv)
    assert {"T_0.4-0.7um", "T_9-10um", "transmission_pct"} <= set(df.columns)
    assert (df["transmission_pct"]
            == df[["T_0.4-0.7um", "T_9-10um"]].min(axis=1)).all()
    assert "INFRARED-KBR" in set(df["glass_id"])


@pytest.mark.parametrize("band", ["0.7:0.4", "0.4"])
def test_cli_bad_band(band):
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-m", "glassmatch.cli", "search",
                          "--band", band], capture_output=True, text=True, cwd=root)
    assert out.returncode != 0


def test_reflection_only_estimate_never_passes():
    """LiF is opaque over 9-10 um; its only figure there is the uncoated
    Fresnel reflection loss (~99 %), which must stay an upper bound."""
    from glassmatch.database import GlassDatabase
    from glassmatch.transmission import band_transmission, upper_bound
    db = GlassDatabase.load()
    tg = {str(g): x for g, x in db.transmission.groupby("glass_id")}
    nk = {str(g): x for g, x in db.spectral_nk.groupby("glass_id")}
    v, b = band_transmission(db, "RII-LIF-LI", 9.0, 10.0, "Average",
                             t_groups=tg, nk_groups=nk, thickness_mm=10.0)
    assert v is None and b.startswith("missing")
    assert upper_bound(b) is not None and upper_bound(b) > 90
