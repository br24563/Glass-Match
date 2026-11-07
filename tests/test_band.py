"""Band dispersion (V and P for any wavelength triad) and the IR data it
rests on."""
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from glassmatch import band as B
from glassmatch.database import load_default_database

ROOT = Path(__file__).resolve().parents[1]
LWIR = B.PRESETS["LWIR (8 / 10 / 12 um)"]


@pytest.fixture(scope="module")
def db():
    return load_default_database()


@pytest.fixture(scope="module")
def lwir(db):
    return B.band_table(db, LWIR).set_index("glass_id")


def test_visible_triad_reproduces_abbe_number(db):
    f = B.band_figures(db, "SCHOTT-N-BK7", B.PRESETS["Visible (F, d, C)"])
    assert f["v_band"] == pytest.approx(64.17, abs=0.01)


def test_lwir_values_match_the_literature(lwir):
    # ZnSe ~58, ZnS ~23, Ge ~800-1000 in the LWIR (8/10/12 um).
    assert lwir.loc["RII-ZNSE-CONNOLLY", "v_band"] == pytest.approx(57.8, abs=1.5)
    assert lwir.loc["RII-ZNS-DEBENHAM", "v_band"] == pytest.approx(22.9, abs=1.0)
    assert 700 < lwir.loc["RII-GE-ICENOGLE", "v_band"] < 1100


def test_lwir_excludes_what_cannot_be_trusted(db, lwir):
    films = {g for g in db.glasses["glass_id"] if "FILM" in g or g.endswith("NM")}
    assert not films & set(lwir.index)                          # thin films
    assert (lwir["n_long"] > 1).all()                           # reststrahlen
    assert (lwir["n_short"] > lwir["n_mid"]).all() and (lwir["n_mid"] > lwir["n_long"]).all()
    assert "RII-SI-SHKONDIN" not in lwir.index                  # noise
    assert "RII-SI-LI-100K" not in lwir.index                   # 4-decimal table


def test_chalcogenides_verified_against_cdgm_tables(db, lwir):
    s = pd.read_csv(ROOT / "data" / "normalized" / "sellmeier.csv", dtype=str,
                    keep_default_na=False).set_index("glass_id")
    for g in ("CDGM-HWS1", "CDGM-HWS2", "CDGM-HWS6"):
        assert s.loc[g, "formula"].startswith("Herzberger")
        assert s.loc[g, "wavelength_um"] == "2-14"
        assert "Maker table check" in s.loc[g, "notes"]
        assert g in lwir.index
    # CDGM's own nu(10.6) = (n10.6 - 1)/(n8 - n12.5) for HWS2 is 86.65.
    f = B.band_figures(db, "CDGM-HWS2", (8000, 10600, 12500))
    assert f["v_band"] == pytest.approx(86.65, rel=0.003)


def test_measurement_temperature_and_material():
    assert B.measurement_temperature_c("Si (Li, 100 K)") == pytest.approx(-173.15)
    assert B.measurement_temperature_c("MgF2 (Zheng, e-ray, 186 °C)") == 186.0
    assert B.measurement_temperature_c("CaF2 (Daimon-20)") is None
    assert B.at_room_temperature("Si (Franta, 20 °C)")
    assert not B.at_room_temperature("Si (Li, 100 K)")


def test_material_keys_group_crystal_pages(db):
    k = B.material_keys(db)
    assert k["RII-SI-FRANTA-20C"] == k["RII-SI-LI-100K"]
    assert k["SCHOTT-N-BK7"] != k["SCHOTT-N-F2"]


def test_band_glass_table(db, lwir):
    from glassmatch import pairs as P
    g = P.glass_table(db.summary_frame(), P.partial_dispersion_table(db), db)
    t = B.band_glass_table(g, lwir.reset_index())
    assert set(t["glass_id"]) == set(lwir.index)
    assert t["thermo_optic"].isna().all()
    row = t.set_index("glass_id").loc["RII-ZNSE-CONNOLLY"]
    assert row["vd"] == lwir.loc["RII-ZNSE-CONNOLLY", "v_band"]


def test_cli_band_and_band_data(tmp_path):
    out = subprocess.run([sys.executable, "-m", "glassmatch.cli", "band",
                          "--preset", "LWIR", "--csv", str(tmp_path / "b.csv")],
                         capture_output=True, text=True, cwd=ROOT, check=True)
    assert "8/10/12 um" in out.stdout
    b = pd.read_csv(tmp_path / "b.csv")
    assert "CDGM-HWS6" in set(b["glass_id"]) and b["glass"].map(B.at_room_temperature).all()
    r = tmp_path / "r.csv"
    subprocess.run([sys.executable, "-m", "glassmatch.cli", "search", "--band",
                    "8:12", "--require-band-data", "--top", "5000", "--csv", str(r)],
                   capture_output=True, text=True, cwd=ROOT, check=True)
    rr = pd.read_csv(r)
    assert rr["transmission_pct"].notna().all() and len(rr) < 100
