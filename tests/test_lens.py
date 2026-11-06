"""Paraxial engine checked against closed-form optics, the four readers
against each other, and glass replacement on an illustrative doublet."""
import math
import subprocess
import sys
from pathlib import Path

import pytest

from glassmatch import lens as L
from glassmatch import thermal
from glassmatch.database import GlassDatabase

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def db():
    return GlassDatabase.load()


def _n(db, g, k):
    return db.n_at(g, L.LINES_NM[k])[0]


def test_thick_singlet_lensmaker(db):
    R1, R2, t = 50.0, -80.0, 6.0
    rx = L.from_dict(db, {"surfaces": [
        {"radius": R1, "thickness": t, "glass": "SCHOTT-N-BK7"},
        {"radius": R2, "thickness": 90}]})
    n = _n(db, "SCHOTT-N-BK7", "d")
    c1, c2 = 1 / R1, 1 / R2
    f = 1 / ((n - 1) * (c1 - c2 + (n - 1) * t * c1 * c2 / n))
    a = L.analyse(db, rx)
    assert a["efl"] == pytest.approx(f, rel=1e-12)
    assert a["bfl"] == pytest.approx(f * (1 - (n - 1) * t * c1 / n), rel=1e-12)
    assert a["petzval_sum"] == pytest.approx((c1 - c2) * (n - 1) / n, rel=1e-12)


def _thin_achromat(db, F=100.0, ids=("SCHOTT-N-BK7", "SCHOTT-N-F2")):
    nn = {g: {k: _n(db, g, k) for k in "dFCg"} for g in ids}
    V = {g: (nn[g]["d"] - 1) / (nn[g]["F"] - nn[g]["C"]) for g in ids}
    p1 = V[ids[0]] / (V[ids[0]] - V[ids[1]]) / F
    p2 = -V[ids[1]] / (V[ids[0]] - V[ids[1]]) / F
    k1 = p1 / (nn[ids[0]]["d"] - 1)
    c1, c2 = k1 / 2, -k1 / 2
    c3 = c2 - p2 / (nn[ids[1]]["d"] - 1)
    rx = L.from_dict(db, {"surfaces": [
        {"radius": 1 / c1, "thickness": 0, "glass": ids[0]},
        {"radius": 1 / c2, "thickness": 0, "glass": ids[1]},
        {"radius": 1 / c3, "thickness": 95}]})

    def focus(k):
        return 1 / (p1 * (nn[ids[0]][k] - 1) / (nn[ids[0]]["d"] - 1)
                    + p2 * (nn[ids[1]][k] - 1) / (nn[ids[1]]["d"] - 1))
    return rx, focus


def test_thin_achromat(db):
    rx, focus = _thin_achromat(db)
    a = L.analyse(db, rx)
    assert a["efl"] == pytest.approx(100.0, rel=1e-12)
    assert abs(a["axial_colour"]) < 1e-10
    assert a["secondary_spectrum"] == pytest.approx(
        focus("d") - (focus("F") + focus("C")) / 2, abs=1e-10)
    assert a["extra_line_focus"] == pytest.approx(focus("g") - focus("d"), abs=1e-10)


def test_thin_singlet_thermal(db):
    """Thin lens: f(T) = f0 (1 + alpha dT) (n - 1) / (n - 1 + dn)."""
    g = "SCHOTT-N-BK7"
    rx = L.from_dict(db, {"surfaces": [
        {"radius": 100.0, "thickness": 0, "glass": g},
        {"radius": -100.0, "thickness": 100}]})
    t, mount = 60.0, 23.6
    n = _n(db, g, "d")
    dn = thermal.dn_dt(db, g, L.LINES_NM["d"], 20, t, absolute=False)["dn_dt"] * 1e-6 * 40
    alpha = db.property_value(g, "cte") * 1e-6
    f0 = L.analyse(db, rx)["efl"]
    f_t = f0 * (1 + alpha * 40) * (n - 1) / (n - 1 + dn)
    th = L.thermal_shift(db, rx, t, mount)
    assert th["efl_change"] == pytest.approx(f_t - f0, rel=1e-9)
    assert th["focus_shift"] == pytest.approx(f_t - f0 * (1 + mount * 1e-6 * 40),
                                              rel=1e-9)


@pytest.mark.parametrize("name", ["doublet.json", "doublet.seq",
                                  "doublet_curv.seq", "doublet.zmx"])
def test_readers_agree(db, name):
    ref = L.analyse(db, L.read_prescription(db, FIX / "doublet.json"), t_c=60)
    rx = L.read_prescription(db, FIX / name)
    assert [s.material for s in rx.surfaces] == ["SCHOTT-N-BK7", "SCHOTT-N-SF5", None]
    a = L.analyse(db, rx, t_c=60)
    for k in ("efl", "bfl", "axial_colour", "secondary_spectrum"):
        assert a[k] == pytest.approx(ref[k], rel=1e-9)
    assert a["thermal"]["focus_shift"] == pytest.approx(
        ref["thermal"]["focus_shift"], rel=1e-9)


def test_zmx_is_utf16_as_opticstudio_writes_it():
    assert (FIX / "doublet.zmx").read_bytes()[:2] == b"\xff\xfe"


@pytest.mark.parametrize("text,msg", [
    ("SURF 0\n DISZ INFINITY\nSURF 1\n TYPE COORDBRK\nSURF 2\n", "COORDBRK"),
    ("SURF 0\n DISZ INFINITY\nSURF 1\n CURV 0.01\n GLAS MIRROR\nSURF 2\n", "mirror"),
    ("SURF 0\n DISZ INFINITY\nSURF 1\n CURV 0.01\n GLAS ___BLANK 1 0 1.5 50\n"
     " DISZ 5\nSURF 2\n CURV 0\nSURF 3\n", "model glass"),
])
def test_zmx_refusals(db, text, msg):
    with pytest.raises(L.PrescriptionError, match=msg):
        L.read_zmx(db, text)


def test_last_surface_must_be_air(db):
    with pytest.raises(L.PrescriptionError, match="air"):
        L.from_dict(db, {"surfaces": [{"radius": 50, "thickness": 5,
                                       "glass": "SCHOTT-N-BK7"}]})


def test_glass_name_resolution(db):
    assert L.resolve_glass(db, "NBK7_SCHOTT") == "SCHOTT-N-BK7"
    assert L.resolve_glass(db, "S-BSL7.OHARA") == "OHARA-S-BSL7"
    with pytest.raises(L.PrescriptionError, match="not in the database"):
        L.resolve_glass(db, "NO-SUCH-GLASS")


def test_replacement_ranking(db):
    rx = L.read_prescription(db, FIX / "doublet.json")
    base, df = L.replacement_candidates(db, rx, "SCHOTT-N-SF5", t_c=60)
    assert not df.empty and "SCHOTT-N-SF5" not in set(df["glass_id"])
    assert df["colour_change_mm"].is_monotonic_increasing
    assert (df["efl_change_pct"].abs() <= 1.0).all()
    assert set(df["status"]) <= {"preferred", "standard", "special", "melt",
                                 "inquiry"}
    # The direct SF5 equivalents lead.
    assert {"HOYA-E-FD5", "CDGM-H-ZF2"} <= set(df["glass_id"].head(5))
    # A glass with no TD record still gets a thermal figure from its
    # maker's measured dn/dT table.
    hik = df[df["glass_id"] == "HIKARI-J-SF5"]
    assert not hik.empty and hik["thermal_shift_change_mm"].notna().all()


def test_resolve_keeps_efl(db):
    rx = L.read_prescription(db, FIX / "doublet.json")
    base, df = L.replacement_candidates(db, rx, "SCHOTT-N-SF5",
                                        resolve_surface=2, tol_vd=10)
    assert (df["efl_change_pct"].abs() < 1e-8).all()


def test_cli_lens_and_replace():
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-m", "glassmatch.cli", "lens",
                          str(FIX / "doublet.zmx"), "-T", "60"],
                         capture_output=True, text=True, cwd=root, check=True)
    assert "EFL 99.9" in out.stdout and "paraxial" in out.stdout
    out = subprocess.run([sys.executable, "-m", "glassmatch.cli", "replace",
                          str(FIX / "doublet.seq"), "N-SF5", "--maker",
                          "SCHOTT", "--resolve-surface", "3", "--csv"],
                         capture_output=True, text=True, cwd=root, check=True)
    assert "HOYA-E-FD5" in out.stdout


def test_cte_extrapolation_refused_by_default(db):
    rx = L.read_prescription(db, FIX / "doublet.json")
    th = L.thermal_shift(db, rx, -40.0)
    assert th["reason"] and "-30/+70" in th["reason"] and "focus_shift" not in th
    th = L.thermal_shift(db, rx, -40.0, allow_cte_extrapolation=True)
    assert th["reason"] is None and math.isfinite(th["focus_shift"])
    assert any(n.startswith("EXTRAPOLATED") for n in th["notes"])
    # Inside the range nothing changes and nothing is noted.
    th = L.thermal_shift(db, rx, 60.0)
    assert th["reason"] is None and not th["notes"]


def test_cli_cte_flag():
    root = Path(__file__).resolve().parents[1]
    base = [sys.executable, "-m", "glassmatch.cli", "lens", str(FIX / "doublet.zmx"), "-T", "-40"]
    out = subprocess.run(base, capture_output=True, text=True, cwd=root, check=True)
    assert "thermal: unavailable" in out.stdout
    out = subprocess.run(base + ["--allow-cte-extrapolation"], capture_output=True,
                         text=True, cwd=root, check=True)
    assert "focus shift" in out.stdout and "EXTRAPOLATED" in out.stdout
