"""n(lambda, T, p): air model, the SCHOTT dn/dT model, measured tables, and
what is refused rather than extrapolated."""
import copy
import math

import pytest

from glassmatch import thermal as T
from glassmatch.database import GlassDatabase


@pytest.fixture(scope="module")
def db():
    return GlassDatabase.load()


def test_air_index():
    # Edlen 1953 / TIE-19 at 15 C, 101325 Pa, d line: 1.000277 to 6 places.
    assert T.air_index(0.5875618) == pytest.approx(1.000277, abs=1e-6)
    assert T.air_index(0.5875618, 20.0, 0.0) == 1.0          # vacuum
    assert T.air_index(0.5875618, 40.0) < T.air_index(0.5875618, 0.0)


def test_catalog_temperature_returns_catalog_index(db):
    r = T.index_at(db, "SCHOTT-N-BK7", 587.5618, 20.0)
    assert r["n"] == pytest.approx(r["n_catalog"], abs=1e-12)
    assert r["method"].startswith("SCHOTT dn/dT model")


def test_vacuum_relative_equals_absolute(db):
    a = T.index_at(db, "SCHOTT-N-BK7", 587.5618, 20.0, p_pa=0.0)["n"]
    b = T.index_at(db, "SCHOTT-N-BK7", 587.5618, 20.0, absolute=True)["n"]
    assert a == pytest.approx(b, abs=1e-12)
    assert a == pytest.approx(1.5168 * T.air_index(0.5875618, 20.0), abs=1e-6)


def test_schott_catalog_dndt(db):
    # SCHOTT N-BK7 absolute dn/dT, e line, +20/+40 C: the catalog's 1.6.
    r = T.dn_dt(db, "SCHOTT-N-BK7", 546.074, 20, 40)
    assert r["dn_dt"] == pytest.approx(1.6, abs=0.05)


def test_cryogenic_is_refused_not_extrapolated(db):
    r = T.index_at(db, "SCHOTT-N-BK7", 587.5618, -196.0)
    assert r["n"] is None and "-100" in r["reason"]


def test_ir_outside_td_range_falls_back_to_measured_table(db):
    r = T.index_at(db, "OHARA-S-FPL51", 1550, -20.0)
    assert r["n"] is not None and "measured relative dn/dT" in r["method"]
    assert "OHARA-XLSX" in r["method"]
    # SCHOTT tabulates no 1550 nm line: nothing is given.
    assert T.index_at(db, "SCHOTT-N-BK7", 1550, 60.0)["n"] is None


def test_no_reference_temperature_no_absolute_n(db):
    r = T.index_at(db, "HIKARI-J-BAK1", 587.56, 40.0)
    assert r["n"] is None and "reference temperature" in r["reason"]
    d = T.dn_dt(db, "HIKARI-J-BAK1", 587.56, 20, 40, absolute=False)
    assert d["dn_dt"] == pytest.approx(3.1) and "HIKARI-XLSX" in d["method"]


def test_relative_absolute_conversion_matches_maker(db):
    # HIKARI tabulates both bases; converting one with the air model gives
    # the other to the printed precision.
    g = copy.copy(db)
    m = db.dn_dt_measured
    g.dn_dt_measured = m[(m["glass_id"] != "HIKARI-J-BAK1")
                         | (m["basis"] == "relative")]
    g.__dict__.pop("_dndt_tables", None)
    g.__dict__.pop("_dndt_rows", None)
    conv = T.dn_dt(g, "HIKARI-J-BAK1", 587.56, 20, 40, absolute=True)
    assert "converted" in conv["method"]
    assert conv["dn_dt"] == pytest.approx(1.7, abs=0.1)


def test_integrate_refuses_gaps():
    iv = [(-40.0, -20.0, 1.0, False, "S"), (20.0, 40.0, 2.0, False, "S")]
    assert T._integrate(iv, -30.0, 30.0) is None
    d, _ = T._integrate(iv, 20.0, 30.0)
    assert d == pytest.approx(20.0)
    d, _ = T._integrate(iv, 30.0, 20.0)
    assert d == pytest.approx(-20.0)


def test_model_vs_measured_disagreement_is_reported(db):
    r = T.index_at(db, "CDGM-ZF50", 587.56, -30.0)
    assert r["n"] is not None
    assert any("differs from the model" in n for n in r["notes"])


def test_td_model_matches_schott_tables(db):
    """The model (with the air index) reproduces SCHOTT's own measured
    tables to their printed precision for nearly every value."""
    from scripts.validate_dndt import compare
    g = copy.copy(db)
    m = db.dn_dt_measured
    g.dn_dt_measured = m[m["source_id"].str.startswith("SCHOTT")]
    df = compare(g)
    assert len(df) > 1500
    assert (df["diff"].abs() <= 0.05 + 1e-9).mean() > 0.98


def test_measured_table_sanity(db):
    m = db.dn_dt_measured
    assert len(m) > 100000
    assert set(m["basis"]) == {"relative", "absolute"}
    assert (m["t_lo_c"] < m["t_hi_c"]).all()
    assert m["dn_dt"].abs().max() < 100
    assert set(m["glass_id"]) <= set(db.glasses["glass_id"])
    assert set(m["source_id"]) <= set(db.sources["source_id"])
    assert not m.duplicated(["glass_id", "wavelength_um", "t_lo_c", "t_hi_c",
                             "basis"]).any()
    assert math.isclose(m["wavelength_um"].min(), 0.3650146, abs_tol=1e-6)
