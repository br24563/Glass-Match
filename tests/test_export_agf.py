"""Zemax .agf export: what goes out must come back identical.

Every exported glass is re-read with the GlassMatch importer
(``parse_agf_text``) and compared value for value with the database it came
from: n(lambda) from the re-imported CD record, n_d, V_d, CTE, the TD
coefficients and every transmission sample. Exact equality, not a tolerance:
the exporter writes stored numbers verbatim, so anything else is a bug.
"""
import datetime as dt

import pytest

from glassmatch.database import load_default_database
from glassmatch.export_agf import export_agf, rii_to_zemax
from glassmatch.importers.agf import TD_PROPS, is_dispersable_formula, parse_agf_text
from glassmatch.spectra import rii_n, zemax_formula_of, zemax_n

WAVELENGTHS_UM = (0.365, 0.4861327, 0.5875618, 0.6562725, 1.014, 1.55, 4.0, 10.6)
TODAY = dt.date(2026, 10, 28)


@pytest.fixture(scope="module")
def db():
    return load_default_database()


@pytest.fixture(scope="module")
def selection(db):
    """One glass per Zemax formula in use, a few refractiveindex.info
    crystals, an IR fit with no catalog n_d, and some that must be skipped."""
    ids = []
    sm = db.sellmeier
    for zf in sorted(sm["zemax_formula"].dropna().unique()):
        rows = sm[(sm["zemax_formula"] == zf) & sm["formula"].map(is_dispersable_formula)]
        ids += rows["glass_id"].head(2).tolist()
    ids += ["RII-AL2O3-MALITSON", "RII-CAF2-DAIMON-20", "RII-SI-EDWARDS",
            "RII-SIO2-RADHAKRISHNAN-O", "INFRARED-CDTE",
            "RII-BAF2-BOSOMWORTH-300K",                    # RII formula 4
            "RII-GE-ICENOGLE"]                             # constant + poles
    archived = sm[~sm["formula"].map(is_dispersable_formula)]["glass_id"]
    ids.append(archived.iloc[0])
    return ids


def _samples(frame) -> dict:
    """glass_id -> sorted (wavelength, T, thickness) samples."""
    out = {}
    if frame.empty:
        return out
    for gid, w, tv, th in zip(frame["glass_id"].astype(str), frame["wavelength_um"],
                              frame["transmission"], frame["thickness_mm"]):
        out.setdefault(gid, []).append((float(w), float(tv), float(th)))
    return {k: sorted(v) for k, v in out.items()}


@pytest.fixture(scope="module")
def db_samples(db):
    return _samples(db.transmission)


def _roundtrip(db, ids):
    ex = export_agf(db, ids, today=TODAY)
    g, p, s, t, issues = parse_agf_text(ex.to_bytes().decode("utf-8"), "RT", "RT-AGF")
    back = {gid: ("RT-" + name).upper() for name, gid in ex.exported.items()}
    props = {}
    for gid, prop, v in zip(p["glass_id"], p["property"], p["value"]):
        props.setdefault((gid, prop), v)
    sell = {r["glass_id"]: r for r in s.to_dict(orient="records")}
    # The importer drops a dPgF of 0 it cannot confirm against the file's own
    # normal line (test_dpgf_filler.py); it says so for each one it drops.
    dropped = {i["glass"] for i in issues if i["issue"].startswith("dPgF 0 dropped")}
    for gid in dropped:
        props[(gid, "dPgF-dropped")] = 0.0
    return ex, back, g, props, sell, _samples(t)


def _prop(p, gid, prop):
    v = p.get((gid, prop))
    return None if v is None else float(v)


def _check_glass(db, gid, rid, ex, p, s, t, db_t):
    src = db.sellmeier_for(gid, sellmeier_only=True)
    new = s[rid]
    coeffs = [float(x) for x in str(new["coefficients"]).split()]
    zf = zemax_formula_of(new)
    for w in WAVELENGTHS_UM:
        want = (rii_n(int(float(src["rii_formula"])), str(src["coefficients"]).split(), w)
                if str(src.get("rii_formula")) not in ("", "nan", "None")
                else zemax_n(zemax_formula_of(src), str(src["coefficients"]).split(), w))
        got = zemax_n(zf, coeffs, w)
        assert got == want or (got != got and want != want), (gid, w, got, want)

    nd, vd = db.property_value(gid, "refractive_index_nd"), db.property_value(gid, "abbe_number_vd")
    if gid in ex.calculated_nd:
        nd, vd = ex.calculated_nd[gid]
    assert _prop(p, rid, "refractive_index_nd") == nd, gid
    assert _prop(p, rid, "abbe_number_vd") == vd, gid
    if nd is not None:
        # n_d is there, so the importer's own n_d/V_d check must pass again.
        assert is_dispersable_formula(new.get("formula")), (gid, new.get("formula"))
    for prop in ["cte", "cte_20_300", "dPgF", "wl_min_um", "wl_max_um"] + \
            [k for k, _ in TD_PROPS]:
        want = db.property_value(gid, prop)
        if want is not None:
            got = _prop(p, rid, prop)
            if prop == "dPgF" and want == 0.0 and got is None:
                got = _prop(p, rid, "dPgF-dropped")
            assert got == want, (gid, prop)

    assert t.get(rid, []) == db_t.get(gid, []), gid


def test_selection_round_trips_exactly(db, selection, db_samples):
    ex, back, g, p, s, t = _roundtrip(db, selection)
    assert len(ex.exported) >= 15
    for gid, rid in back.items():
        _check_glass(db, gid, rid, ex, p, s, t, db_samples)


def test_whole_database_round_trips_exactly(db, db_samples):
    ex, back, g, p, s, t = _roundtrip(db, db.glass_ids())
    nm_lines = [ln for ln in ex.text.split("\r\n") if ln.startswith("NM ")]
    assert len(nm_lines) == len(ex.exported) == len(g), "Zemax names must be unique"
    for gid, rid in back.items():
        _check_glass(db, gid, rid, ex, p, s, t, db_samples)


def test_each_catalog_round_trips_with_its_dpgf_zeros(db):
    """One source catalog per file - the unit the importer calibrates its
    dPgF check on - brings every stored dPgF back, zeros included."""
    src = {}
    for gid in db.glass_ids():
        row = db.sellmeier_for(gid, sellmeier_only=True)
        if row is not None:
            src.setdefault(str(row["source_id"]), []).append(gid)
    for sid, ids in src.items():
        if not export_agf(db, ids).exported:
            continue                     # e.g. a crystal page with no Zemax form
        ex, back, g, p, s, t = _roundtrip(db, ids)
        for gid, rid in back.items():
            want = db.property_value(gid, "dPgF")
            if want is not None:
                assert _prop(p, rid, "dPgF") == want, (sid, gid)


def test_unverified_fits_are_skipped_and_reported(db, selection):
    ex = export_agf(db, selection, today=TODAY)
    skipped = dict(ex.skipped)
    archived = selection[-1]
    assert "archived" in skipped[archived]
    assert "formula 4" in skipped["RII-BAF2-BOSOMWORTH-300K"]
    assert "constant term" in skipped["RII-GE-ICENOGLE"]
    assert set(skipped).isdisjoint(ex.exported.values())
    # Nothing that is not a verified fit is ever written as a CD record.
    for gid in ex.exported.values():
        assert is_dispersable_formula(db.sellmeier_for(gid, sellmeier_only=True)["formula"])


def test_file_follows_agf_conventions(db, selection):
    ex = export_agf(db, selection, today=TODAY)
    raw = ex.to_bytes()
    raw.decode("utf-8")                                   # UTF-8
    assert b"\x00" not in raw                             # not UTF-16
    assert raw.endswith(b"\r\n")
    assert raw.count(b"\n") == raw.count(b"\r\n")         # CRLF throughout
    lines = ex.text.split("\r\n")[:-1]
    assert lines[0].startswith("CC GlassMatch export, 2026-10-28")
    header = [ln for ln in lines if ln.startswith("CC")]
    assert lines[:len(header)] == header, "CC comments form the header"
    for name, gid in ex.exported.items():
        line = next(ln for ln in header if ln.startswith(f"CC   {name}: "))
        src = db.sellmeier_for(gid, sellmeier_only=True)["source_id"]
        assert src in line, (gid, line)
    for ln in lines[len(header):]:
        tag = ln.split()[0]
        assert tag in {"NM", "ED", "CD", "TD", "OD", "LD", "IT"}, ln
        if tag == "NM":
            parts = ln.split()
            assert len(parts) == 9
            assert int(parts[2]) in range(1, 14)
            float(parts[4]), float(parts[5])
        elif tag == "CD":
            assert len(ln.split()) >= 11
    # Provenance names the date of a dated manufacturer catalog.
    schott = next((gid for gid in ex.exported.values() if gid.startswith("SCHOTT")), None)
    if schott:
        assert "published" in next(ln for ln in header if gid_name(ex, schott) in ln)


def gid_name(ex, gid):
    return next(n for n, g in ex.exported.items() if g == gid)


def test_duplicate_names_fall_back_to_glass_id(db):
    names = db.glasses.groupby("glass_name")["glass_id"].apply(list)
    pair = next(ids for ids in names if len(ids) == 2 and all(
        db.dispersion_status(g) == "sellmeier1" for g in ids))
    ex = export_agf(db, pair, today=TODAY)
    assert sorted(ex.exported.values()) == sorted(pair)
    assert sorted(ex.exported) == sorted(pair)


@pytest.mark.parametrize("rii,coeffs,zf", [
    (2, [0.0, 0.69, 0.0047, 0.41, 0.0135, 0.89, 97.9], 2),
    (1, [0.0, 1.02, 0.0614, 1.06, 0.111, 5.28, 17.9], 2),
    (1, [0.0, 1.0, 0.07, 0.5, 0.12, 0.1, 8.5, 2.0, 20.0], 6),
    (1, [0.0, 1.0, 0.07], 2),
    (7, [3.41983, 0.159906, -0.123109, 1.26878e-06, -1.95104e-09], 3),
])
def test_rii_mappings_are_bit_identical(rii, coeffs, zf):
    got_f, cd = rii_to_zemax(rii, coeffs)
    assert got_f == zf
    cd = [float(repr(x)) for x in cd]                     # through the file
    for w in (0.25, 0.55, 1.0, 3.0, 9.0):
        a, b = rii_n(rii, coeffs, w), zemax_n(zf, cd, w)
        assert a == b or (a != a and b != b)


@pytest.mark.parametrize("rii,coeffs", [
    (1, [2.5, 1.0, 0.3, 2.0, 30.0]),                      # constant + 2 poles
    (2, [0.3, 1.0, 0.1]),                                 # constant + 1 pole
    (3, [1.0, 0.1, 2.0]), (4, [0.0] * 9), (5, [1.4, 0.003, -2.0]),
])
def test_rii_without_identical_zemax_formula_is_refused(rii, coeffs):
    zf, why = rii_to_zemax(rii, coeffs)
    assert zf is None and why
