"""Tests: dn/dT (TD records), OD cost/resistance, the HIKARI workbook importer,
the |dn/dT| filter, and the official-catalog merge."""
import math

import pandas as pd
import pytest

from glassmatch.database import load_default_database
from glassmatch.importers.agf import parse_agf_text
from glassmatch.matching import match_glasses
from glassmatch.spectra import dn_dt_abs

# HIKARI J-FK5 in Nikon's NIKON-HIKARI_201911.AGF (TD wrapped onto two lines,
# as NIKON writes it). HIKARI's 2025 catalog states absolute dn/dT at the d
# line, +20/+40 C, as -2.7e-6/K for the same glass.
J_FK5 = (
    "NM J-FK5 13 1 1.487490 70.318793 0 0 1\n"
    "CD 2.188268550E+000 -9.190447240E-003 -1.116210710E-004 9.263728150E-003 \n"
    "7.349007330E-005 4.197242420E-006 -1.154122030E-007 0.000000000E+000 \n"
    "0.000000000E+000 0.000000000E+000\n"
    "TD -8.080000000E-006 1.810000000E-008 -1.840000000E-012 3.750000000E-007 \n"
    "3.020000000E-010 1.690000000E-001 2.300000000E+001\n"
    "OD -1.00000 -1.00000 -1.00000 -1.00000 -1.00000 3.00000\n"
)
TD = (-8.08e-6, 1.81e-8, -1.84e-12, 3.75e-7, 3.02e-10, 0.169, 23.0)


def _props(text):
    g, p, s, t, issues = parse_agf_text(text, "HIKARI", "T")
    return p.set_index("property")["value"], p, issues


def test_dn_dt_formula_matches_the_manufacturers_own_figure():
    v = dn_dt_abs(TD, 1.48749, 0.5875618, 20.0, 40.0) * 1e6
    assert v == pytest.approx(-2.7, abs=0.1)


def test_wrapped_td_record_is_parsed_and_dn_dt_derived():
    vals, p, _ = _props(J_FK5)
    assert vals["td_D0"] == pytest.approx(-8.08e-6)
    assert vals["td_T0"] == 23.0                       # from the second line
    row = p[p["property"] == "dn_dt_abs_d_20_40"].iloc[0]
    assert row["data_type"] == "calculated"
    assert row["value"] == pytest.approx(-2.7, abs=0.1)


def test_all_zero_td_is_no_data():
    text = J_FK5.replace(
        "TD -8.080000000E-006 1.810000000E-008 -1.840000000E-012 3.750000000E-007 \n"
        "3.020000000E-010 1.690000000E-001 2.300000000E+001\n",
        "TD 0 0 0 0 0 0 20\n")
    vals, _, _ = _props(text)
    assert "td_D0" not in vals and "dn_dt_abs_d_20_40" not in vals


def test_implausible_td_is_kept_verbatim_but_not_used():
    # NIKON's 2019 file prints J-BASF2's D0 as -2.62 (the 1e-6 dropped).
    text = J_FK5.replace("TD -8.080000000E-006", "TD -2.620000000E+000")
    vals, _, issues = _props(text)
    assert vals["td_D0"] == -2.62
    assert "dn_dt_abs_d_20_40" not in vals
    assert any("TD implausible" in str(i.get("issue")) for i in issues)


def test_od_record_keeps_given_values_and_skips_placeholders():
    vals, _, _ = _props(J_FK5)
    assert vals["phosphate_resistance"] == 3.0
    for prop in ("relative_cost", "climate_resistance", "stain_resistance",
                 "acid_resistance", "alkali_resistance"):
        assert prop not in vals                    # -1 = not given
    vals, _, _ = _props(J_FK5.replace("OD -1.00000", "OD _"))
    assert "relative_cost" not in vals             # "_" = not given (SCHOTT)


# --- |dn/dT| filter --------------------------------------------------------

def _summary():
    return pd.DataFrame([
        {"glass_id": "A", "glass": "A", "nd": 1.5, "vd": 60, "dn_dt": 1.0},
        {"glass_id": "B", "glass": "B", "nd": 1.5, "vd": 60, "dn_dt": -6.0},
        {"glass_id": "C", "glass": "C", "nd": 1.5, "vd": 60, "dn_dt": None},
    ])


def test_dndt_limit_removes_glasses_above_it_and_says_so():
    out = match_glasses(_summary(), {"dndt_abs_max": 3.0}, {"nd": 1})
    assert set(out["glass_id"]) == {"A", "C"}
    assert out.attrs["dndt_filtered"] == 1


def test_dndt_limit_drops_missing_data_only_when_required():
    out = match_glasses(_summary(), {"dndt_abs_max": 3.0}, {"nd": 1},
                        require_data=True)
    assert set(out["glass_id"]) == {"A"}
    out = match_glasses(_summary(), {}, {"nd": 1})
    assert set(out["glass_id"]) == {"A", "B", "C"}


# --- shipped data ------------------------------------------------------------

@pytest.fixture(scope="module")
def db():
    return load_default_database()


def test_official_catalogs_replaced_the_mirror(db):
    src = db.properties.groupby("source_id")["glass_id"].nunique()
    for sid in ("HOYA-AGF-2026-07-07", "CDGM-AGF-2026-09",
                "SUMITA-AGF-2026-08-26", "HIKARI-XLSX-2025-06-01",
                "NIKON-HIKARI-AGF-2019-11"):
        assert src.get(sid, 0) > 100 or sid == "NIKON-HIKARI-AGF-2019-11"
    assert "HOYA-AGF-NZHAGEN-MIRROR" not in src or src["HOYA-AGF-NZHAGEN-MIRROR"] < 5
    assert "NIKON-AGF-NZHAGEN-MIRROR" not in src
    assert "HIKARI-AGF-NZHAGEN-MIRROR" not in src


def test_no_glass_is_listed_under_both_nikon_and_hikari(db):
    g = db.glasses
    nikon = set(g.loc[g["manufacturer_id"] == "NIKON", "glass_name"])
    hikari = set(g.loc[g["manufacturer_id"] == "HIKARI", "glass_name"])
    assert not nikon & hikari
    assert all(n.startswith(("NIFS", "NICF")) for n in nikon)


def test_mirror_only_glasses_are_kept_as_obsolete(db):
    g = db.glasses.set_index("glass_id")
    legacy = g[g["description"].astype(str).str.contains(
        "Not in .* current catalog", regex=True)]
    assert len(legacy) > 0
    assert (legacy["status"] == "obsolete").all()


def test_hikari_fits_verified_at_every_catalog_wavelength(db):
    s = db.sellmeier
    h = s[s["source_id"] == "HIKARI-XLSX-2025-06-01"]
    assert len(h) == 155
    assert h["formula"].str.startswith("Extended 3").all()
    assert h["notes"].str.contains("Verified against the catalog index").all()


def test_hikari_moduli_are_self_consistent(db):
    p = db.properties
    p = p[p["source_id"] == "HIKARI-XLSX-2025-06-01"]
    piv = p[p["property"].isin(["youngs_modulus", "shear_modulus",
                                "poisson_ratio"])].pivot_table(
        index="glass_id", columns="property", values="value", aggfunc="first")
    e = piv["shear_modulus"] * 2 * (1 + piv["poisson_ratio"])
    assert ((e - piv["youngs_modulus"]).abs() / piv["youngs_modulus"] < 0.03).all()


def test_manufacturer_cross_references_resolve_to_real_glasses(db):
    eq = db.equivalents
    x = eq[eq["relation"].str.contains("cross-reference")]
    ids = set(db.glasses["glass_id"])
    assert len(x) > 300
    assert set(x["glass_id_a"]) <= ids and set(x["glass_id_b"]) <= ids
    pair = x[(x["glass_id_a"] == "HIKARI-J-FK5")]
    assert {"SCHOTT-N-FK5", "HOYA-FC5", "OHARA-S-FSL5"} <= set(pair["glass_id_b"])


def test_dn_dt_values_are_physical(db):
    p = db.properties
    v = p.loc[p["property"] == "dn_dt_abs_d_20_40", "value"].astype(float)
    assert len(v) > 1500
    assert v.abs().max() < 1000 and not v.map(math.isnan).any()
