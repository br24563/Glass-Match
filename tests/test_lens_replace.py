"""Phase 3 replacement tools: element-power mode, round-trip export into the
original file, CODE V private catalog, and the audit command."""
import difflib
import subprocess
import sys
from pathlib import Path

import pytest

from glassmatch import lens as L
from glassmatch.database import load_default_database

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def _n(db, rx):
    return L.indices(db, rx, L.LINES_NM["d"])[0]


def test_singlet_in_air_keeps_power_and_shape(db):
    rx = L.from_dict(db, {"surfaces": [
        {"radius": 50, "thickness": 5, "glass": "SCHOTT-N-BK7"},
        {"radius": -80, "thickness": 90}]})
    new, note = L.replace_glass(db, rx, "SCHOTT-N-BK7", "OHARA-S-BAL41")
    assert "shape kept" in note
    assert L.element_power(new, _n(db, new), 0) == pytest.approx(
        L.element_power(rx, _n(db, rx), 0), rel=1e-12)
    c, c2 = [s.curvature for s in rx.surfaces], [s.curvature for s in new.surfaces]
    assert (c2[0] + c2[1]) / (c2[0] - c2[1]) == pytest.approx(
        (c[0] + c[1]) / (c[0] - c[1]), rel=1e-12)


def test_cemented_element_keeps_shared_surface(db):
    rx = L.read_prescription(db, FIX / "doublet.json")
    new, note = L.replace_glass(db, rx, "SCHOTT-N-SF5", "HOYA-E-FD5")
    assert "surface 3 re-solved" in note
    assert new.surfaces[1].curvature == rx.surfaces[1].curvature   # cemented face
    assert L.element_power(new, _n(db, new), 1) == pytest.approx(
        L.element_power(rx, _n(db, rx), 1), rel=1e-12)


def test_cemented_both_sides_is_refused_not_forced(db):
    rx = L.from_dict(db, {"surfaces": [
        {"radius": 40, "thickness": 4, "glass": "SCHOTT-N-BK7"},
        {"radius": -30, "thickness": 2, "glass": "SCHOTT-N-SF5"},
        {"radius": 60, "thickness": 4, "glass": "SCHOTT-N-BK7"},
        {"radius": -90, "thickness": 80}]})
    new, note = L.replace_glass(db, rx, "SCHOTT-N-SF5", "HOYA-E-FD5")
    assert "cemented on both sides" in note
    assert [s.curvature for s in new.surfaces] == [s.curvature for s in rx.surfaces]


def test_element_mode_disturbs_downstream_less_than_curvatures(db):
    rx = L.read_prescription(db, FIX / "triplet.json")
    _, el = L.replacement_candidates(db, rx, "SCHOTT-F4", mode="element", max_results=50)
    _, cu = L.replacement_candidates(db, rx, "SCHOTT-F4", mode="curvatures",
                                     max_results=50, efl_tol_pct=None)
    both = el.merge(cu, on="glass_id", suffixes=("_el", "_cu"))
    assert len(both) > 5
    assert (both["ray_height_change_pct_el"] <= both["ray_height_change_pct_cu"] + 1e-9).mean() > 0.9
    assert {"petzval_change", "ray_height_change_pct", "focus_change_F_mm"} <= set(el.columns)


@pytest.mark.parametrize("name", ["doublet.zmx", "doublet.seq", "doublet_curv.seq"])
def test_round_trip_touches_only_changed_lines(db, name):
    rx = L.read_prescription(db, FIX / name)
    new, _ = L.replace_glass(db, rx, "SCHOTT-N-SF5", "HOYA-E-FD5")
    text, ext, enc = L.export_prescription(db, new)
    assert ext == name.split(".")[1]
    back = L.read_prescription(db, text=text, fmt=ext)
    a, b = L.analyse(db, new), L.analyse(db, back)
    for k in ("efl", "bfl", "axial_colour", "secondary_spectrum"):
        assert b[k] == pytest.approx(a[k], rel=1e-12, abs=1e-12)
    assert [s.material for s in back.surfaces] == ["SCHOTT-N-BK7", "HOYA-E-FD5", None]
    diff = [d for d in difflib.unified_diff(rx.source["text"].splitlines(),
                                            text.splitlines(), lineterm="", n=0)
            if d[:1] in "+-" and not d.startswith(("---", "+++"))]
    # glass line + one curvature line (+ GCAT for .zmx), old and new each
    assert len(diff) == (6 if ext == "zmx" else 4)
    if ext == "zmx":
        assert enc == "utf-16" and "+GCAT SCHOTT HOYA" in diff


def test_export_json_and_refusals(db):
    rx = L.read_prescription(db, FIX / "doublet.json")
    text, ext, _ = L.export_prescription(db, rx)
    assert ext == "json" and L.read_json(db, text).surfaces[1].material == "SCHOTT-N-SF5"
    with pytest.raises(L.PrescriptionError):
        L.export_prescription(db, rx, "zmx")


def test_codev_private_catalog(db):
    from glassmatch.export_codev import export_codev
    text, exported, skipped = export_codev(db, ["SCHOTT-N-BK7", "HOYA-E-FD5"],
                                           (656.2725, 587.5618, 486.1327))
    assert "PRV" in text and "END" in text
    assert "PWL 656.2725 587.5618 486.1327" in text
    line = next(ln for ln in text.splitlines() if ln.startswith("'SCHOTT_N-BK7'"))
    assert float(line.split()[2]) == pytest.approx(1.5168, abs=1e-6)
    # Outside the fit's stated range: skipped, never extrapolated.
    _, ex2, sk2 = export_codev(db, ["SCHOTT-N-BK7"], (587.5618, 10000.0))
    assert not ex2 and "not extrapolated" in sk2[0][1]


def test_cli_audit_and_use(tmp_path):
    out = subprocess.run([sys.executable, "-m", "glassmatch.cli", "audit",
                          str(ROOT / "docs" / "examples"), "--csv",
                          str(tmp_path / "a.csv")], capture_output=True,
                         text=True, cwd=ROOT, check=True)
    assert "SCHOTT-F4 ->" in out.stdout and "SCHOTT-SK16 -> SCHOTT-N-SK16" in out.stdout
    new = tmp_path / "new.zmx"
    subprocess.run([sys.executable, "-m", "glassmatch.cli", "replace",
                    str(FIX / "doublet.zmx"), "N-SF5", "--maker", "SCHOTT",
                    "--use", "E-FD5", "--use-maker", "HOYA", "-o", str(new)],
                   capture_output=True, text=True, cwd=ROOT, check=True)
    assert new.read_bytes()[:2] == b"\xff\xfe"
    db = load_default_database()
    assert L.read_prescription(db, new).surfaces[1].material == "HOYA-E-FD5"
