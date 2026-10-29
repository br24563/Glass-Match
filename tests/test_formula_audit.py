"""Regression tests for the 2026-10 data audit.

Each test pins one defect the audit found in shipped data:

* the .agf importer ignored the NM record's dispersion-formula number and
  evaluated every CD row as Sellmeier-1, so 1,550 Schott-formula and Extended
  fits were archived and HOYA/CDGM/SUMITA/HIKARI/LZOS had no dispersion;
* a Zemax n_d placeholder (1.0) made the importer read the formula number "2"
  as n_d, stored as manufacturer data for Si, CdTe, ZnSe ...;
* refractiveindex.info formula 1/2 pages lost their constant term, so 19
  crystal pages (GaAs Skauli, Ge Icenogle, the Li fluorides ...) drew the
  wrong material;
* IT samples outside 0.2-5 um (deep UV, mid/far IR) were discarded;
* NM status was ignored, so 1,156 discontinued glasses showed as standard;
* a hand-entered CDGM H-ZF52 carried SCHOTT SF6's n_d/V_d.
"""
import math

import pandas as pd
import pytest

from glassmatch.database import GlassDatabase, load_default_database
from glassmatch.importers.agf import is_dispersable_formula, parse_agf_text
from glassmatch.reference_check import compare_to_reference, verdict
from glassmatch.spectra import (dispersion_curve, n_from_row, rii_n, zemax_n)
from glassmatch.transmission import n_at

D, F, C = 0.5875618, 0.4861327, 0.6562725

# HOYA FC5 as shipped in the HOYA .agf: Zemax formula 1 (Schott).
FC5 = [2.1894054, -0.0099044908, 0.008640337, 0.00022263067,
       -1.2291942e-05, 5.9386349e-07]


@pytest.fixture(scope="module")
def db():
    return load_default_database()


def _vd(f):
    return (f(D) - 1.0) / (f(F) - f(C))


def test_schott_formula_reproduces_catalog():
    f = lambda w: zemax_n(1, FC5, w)  # noqa: E731
    assert f(D) == pytest.approx(1.487489, abs=1e-5)
    assert _vd(f) == pytest.approx(70.441164, abs=0.05)


def test_importer_evaluates_the_formula_the_nm_record_names():
    txt = ("NM FC5 1 487704 1.487489 70.441164 0 0 4\n"
           f"CD {' '.join(repr(c) for c in FC5)} 0 0 0 0\n")
    g, p, s, t, issues = parse_agf_text(txt, "HOYA", "T")
    row = s.iloc[0].to_dict()
    assert row["formula"] == "Schott (Zemax formula 1, CD record)"
    assert is_dispersable_formula(row["formula"])
    assert n_from_row(row, D) == pytest.approx(1.487489, abs=1e-5)


def test_vd_is_gated_too():
    # Right n_d, wrong V_d: a fit that only matches at one wavelength is not
    # the catalog's glass.
    txt = ("NM FC5 1 487704 1.487489 60.0 0 0 4\n"
           f"CD {' '.join(repr(c) for c in FC5)} 0 0 0 0\n")
    g, p, s, t, issues = parse_agf_text(txt, "HOYA", "T")
    assert s.iloc[0]["formula"].startswith("Non-dispersable")
    assert "V_d" in s.iloc[0]["formula"]


def test_nd_placeholder_is_missing_not_the_formula_number():
    txt = ("NM SILICON 2 1 1.000000 0.000000 0 0 0\n"
           "CD 10.6684293 0.0909121907 0.003043475 1.28766017 1.54133408 "
           "1218816.0 0 0 0 0\n")
    g, p, s, t, issues = parse_agf_text(txt, "INFRARED", "T")
    assert p.empty or p[p["property"].isin(["refractive_index_nd",
                                            "abbe_number_vd"])].empty
    assert "no catalog n(d)" in s.iloc[0]["formula"]


def test_nm_status_two_is_obsolete():
    # Status 1 is the maker's "preferred" class (kept since 0.7.0; it used to
    # be collapsed to "standard").
    g, *_ = parse_agf_text("NM OLD 2 517642 1.5168 64.17 0 2\n"
                           "NM NEW 2 517642 1.5168 64.17 0 1\n", "X", "T")
    assert dict(zip(g["glass_name"], g["status"])) == {"OLD": "obsolete",
                                                       "NEW": "preferred"}


def test_it_keeps_deep_uv_and_far_ir_but_rejects_placeholders():
    txt = ("NM G 2 1 1.5 60 0 1\n"
           "IT 0.157 0.36 10.0\nIT 12.0 0.96 1.0\nIT 0.28 -999.0 10.0\n"
           "IT 0.7 12.0 10.0\n")
    g, p, s, t, issues = parse_agf_text(txt, "X", "T")
    assert sorted(t["wavelength_um"]) == [0.157, 12.0]


def test_rii_constant_term_is_used():
    # Skauli et al. 2003 GaAs, refractiveindex.info formula 1, C1 = 4.37:
    # n(10 um) = 3.2737 published. Without C1 it comes out ~2.5.
    coeffs = [4.372514, 5.466742, 0.4431307, 0.02429960, 0.8746453,
              1.957522, 36.9166]
    assert rii_n(1, coeffs, 10.0) == pytest.approx(3.2737, abs=1e-3)


def test_curve_is_not_extrapolated():
    row = {"zemax_formula": 1, "coefficients": " ".join(map(repr, FC5))}
    curve = dispersion_curve(row, [0.3, 0.5876, 3.0], 0.4, 2.0)
    assert math.isnan(curve.iloc[0]["n"]) and math.isnan(curve.iloc[2]["n"])
    assert curve.iloc[1]["n"] == pytest.approx(1.4875, abs=1e-4)


def test_fresnel_index_respects_the_fit_range():
    gdb = GlassDatabase(
        glasses=pd.DataFrame([{"glass_id": "G", "manufacturer_id": "M"}]),
        sellmeier=pd.DataFrame([{
            "glass_id": "G", "formula": "Schott (Zemax formula 1, CD record)",
            "zemax_formula": 1, "coefficients": " ".join(map(repr, FC5)),
            "wavelength_um": "0.4-2.0"}]),
        transmission=pd.DataFrame(), spectral_nk=pd.DataFrame())
    assert n_at(gdb, "G", 0.5876) == pytest.approx(1.4875, abs=1e-4)
    assert n_at(gdb, "G", 3.0) is None


# --- shipped data ----------------------------------------------------------

def test_every_verified_catalog_fit_reproduces_its_nd_and_vd(db):
    props = db.properties
    nd = props[props["property"] == "refractive_index_nd"].groupby(
        "glass_id")["value"].first()
    vd = props[props["property"] == "abbe_number_vd"].groupby(
        "glass_id")["value"].first()
    checked = 0
    for _, r in db.sellmeier.iterrows():
        row = r.to_dict()
        gid = row["glass_id"]
        if not is_dispersable_formula(row.get("formula")) or gid not in nd:
            continue
        f = lambda w: n_from_row(row, w)  # noqa: E731
        assert abs(f(D) - float(nd[gid])) <= 2e-4, gid
        if gid in vd:
            assert abs(_vd(f) - float(vd[gid])) <= 0.5, gid
        checked += 1
    assert checked > 2400


def test_no_catalog_has_a_dispersion_blackout(db):
    s = db.sellmeier
    verified = s[s["formula"].map(is_dispersable_formula)]
    makers = verified["glass_id"].str.split("-").str[0].value_counts()
    for m in ("HOYA", "CDGM", "SUMITA", "HIKARI", "LZOS", "OHARA", "SCHOTT"):
        assert makers.get(m, 0) > 50, m


def test_ir_placeholder_rows_are_clean(db):
    p = db.properties
    nd = p[(p["property"] == "refractive_index_nd")
           & p["glass_id"].isin(["INFRARED-SILICON", "INFRARED-CDTE",
                                 "INFRARED-ZNSE", "UMICORE-GASIR2"])]
    assert nd.empty
    # The hand-entered H-ZF52 carried SCHOTT SF6's values (1.80518 / 25.43).
    # CDGM's own 2026 catalog now supplies the real glass.
    rows = db.property_provenance("CDGM-H-ZF52", "refractive_index_nd")
    assert [r["source_id"] for r in rows] == ["CDGM-AGF-2026-09"]
    assert db.property_value("CDGM-H-ZF52", "refractive_index_nd") == 1.84666


def test_ir_fits_verified_only_against_their_reference(db):
    row = db.sellmeier_for("INFRARED-SILICON", sellmeier_only=True)
    assert row is not None and "RII-SI-CHANDLER-HOROWITZ" in row["notes"]
    assert verdict(compare_to_reference(db, "INFRARED-SILICON",
                                        "RII-SI-CHANDLER-HOROWITZ"))
    # and the check rejects the wrong material outright
    assert not verdict(compare_to_reference(db, "INFRARED-SILICON",
                                            "RII-GE-ICENOGLE"))
    ref, _ = db.n_at("RII-SI-CHANDLER-HOROWITZ", 10000.0)
    assert n_from_row(row, 10.0) == pytest.approx(ref, abs=1e-3)
