"""IR temperature behaviour: CDGM's measured IR dn/dT, athermal pairs in a
band, and lens analysis / replacement at IR wavelengths."""
import subprocess
import sys
from pathlib import Path

import pytest

from glassmatch import band as B
from glassmatch import lens as L
from glassmatch import thermal as T
from glassmatch.database import load_default_database

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
LWIR = B.PRESETS["LWIR (8 / 10 / 12 um)"]


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def test_cdgm_ir_dndt_imported(db):
    m = db.dn_dt_measured
    h = m[m["glass_id"].str.startswith("CDGM-HWS")]
    assert len(h) == 29 and set(h["basis"]) == {"relative"}
    assert {(lo, hi) for lo, hi in zip(h["t_lo_c"], h["t_hi_c"])} == {(-40, 80), (-20, 80)}
    # HWS9 at 4 um: 181e-6/K (CDGM's sheet), above the old 100 cap.
    assert h[(h.glass_id == "CDGM-HWS9") & (h.wavelength_um == 4.0)]["dn_dt"].iloc[0] == 181


def test_ir_index_at_temperature(db):
    r = T.index_at(db, "CDGM-HWS1", 10000, 60)
    assert r["n"] is not None and "CDGM-XLSX" in r["method"]
    d = T.dn_dt(db, "CDGM-HWS1", 10000, 20, 40, absolute=False)
    assert d["dn_dt"] == pytest.approx(71.0)
    # SCHOTT IRG: dn/dT only at 22 C in the datasheet - not stretched over a span.
    assert T.index_at(db, "SCHOTT-IRG25", 10000, 60)["n"] is None


def test_band_athermal_gamma_and_pairs(db):
    from glassmatch import pairs as P
    g = P.glass_table(db.summary_frame(), P.partial_dispersion_table(db), db)
    t = B.band_glass_table(g, B.band_table(db, LWIR), db, LWIR)
    k = t.dropna(subset=["thermo_optic_air"]).set_index("glass_id")
    assert {"CDGM-HWS1", "CDGM-HWS6"} <= set(k.index)
    row = k.loc["CDGM-HWS1"]
    assert row["thermo_optic_air"] == pytest.approx(71.0 / (row["nd"] - 1) - row["cte"])
    pp = P.find_pairs(k.reset_index(), sort_by="athermal", mount_cte=23.6, min_dv=5)
    assert len(pp) and pp["thermal_residual"].abs().iloc[0] < 1.0


def test_lwir_lens_analysis(db):
    rx = L.read_prescription(db, FIX / "lwir_doublet.json")
    assert L.analyse(db, rx)["reason"]                     # opaque in the visible
    a = L.analyse(db, rx, band=LWIR, t_c=60)
    same = L.analyse(db, rx, primary=10000.0, short=8000.0, long=12000.0, extra=None)
    assert a["efl"] == same["efl"] and a["axial_colour"] == same["axial_colour"]
    assert a["extra_line_focus"] is None
    assert a["thermal"]["reason"] is None and "CDGM-XLSX" in a["thermal"]["methods"][0]


def test_lwir_replacement(db):
    rx = L.read_prescription(db, FIX / "lwir_doublet.json")
    base, df = L.replacement_candidates(db, rx, "CDGM-HWS6", band=LWIR, tol_nd=0.3)
    assert len(df) and "focus_change_8um_mm" in df.columns
    # No cryogenic crystal pages, no single rays of birefringent crystals.
    assert not df["glass_id"].str.contains("-20K|-80K|-5K|-[OE]$", regex=True).any()
    with pytest.raises(L.PrescriptionError, match="cannot be traced"):
        L.replacement_candidates(db, L.read_prescription(db, FIX / "doublet.json"),
                                 "SCHOTT-N-SF5", band=LWIR)


def test_cli_design_band(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-m", "glassmatch.cli", *a],  # noqa: E731
                                    capture_output=True, text=True, cwd=ROOT)
    out = run("lens", str(FIX / "lwir_doublet.json"), "--design-band", "LWIR", "-T", "60")
    assert out.returncode == 0 and "8-12 um" in out.stdout and "focus shift" in out.stdout
    out = run("lens", str(FIX / "lwir_doublet.json"))
    assert out.returncode == 1 and "--design-band" in out.stdout
    out = run("lens", str(FIX / "lwir_doublet.json"), "--design-band", "8000:10000:12000")
    assert out.returncode == 0
    out = run("lens", str(FIX / "lwir_doublet.json"), "--design-band", "12000:10000:8000")
    assert out.returncode != 0
