"""Tests: crystal data from refractiveindex.info, end to end through the DB.

Covers the schema integration (new `crystal` material class, the
`spectral_nk` table, n at an arbitrary reference wavelength) and pins the
n_at lookup that a precedence bug once broke.
"""
import pytest

from glassmatch.database import GlassDatabase


@pytest.fixture(scope="module")
def db():
    return GlassDatabase.load()


def test_crystal_material_class_is_present(db):
    classes = set(db.glasses["material_class"])
    assert "crystal" in classes
    n_crystal = int((db.glasses["material_class"] == "crystal").sum())
    assert n_crystal > 50, n_crystal


def test_crystal_pages_are_credited_and_cc0(db):
    rii = db.sources[db.sources["source_id"].astype(str).str.startswith("RII-")]
    assert len(rii) > 50
    assert rii["license"].str.contains("CC0").all()
    # every crystal property must point at a source that exists
    known = set(db.sources["source_id"].astype(str))
    used = set(db.properties.loc[
        db.properties["glass_id"].astype(str).str.startswith("RII-"),
        "source_id"].dropna().astype(str))
    assert used and used <= known, sorted(used - known)[:5]


def test_published_crystal_indices_are_reproduced(db):
    """Values an optical engineer would recognise, against the literature."""
    # Malitson 1963 CaF2: n_d = 1.43376
    assert db.n_at("RII-CAF2-MALITSON", 587.6)[0] == pytest.approx(1.43376, abs=3e-4)
    # Fused silica (Malitson): n_d = 1.4585
    assert db.n_at("RII-SIO2-MALITSON", 587.6)[0] == pytest.approx(1.4585, abs=3e-4)
    # Ordinary and extraordinary sapphire: n_o ~ 1.768
    assert db.n_at("RII-AL2O3-MALITSON", 587.6)[0] == pytest.approx(1.768, abs=3e-3)


def test_n_at_returns_exactly_one_reference_row(db):
    """Guards the `&` / `<` precedence bug.

    ``A & B & (C - w).abs() < tol`` parses as ``(A & B & (C - w).abs()) < tol``
    because `&` binds tighter than `<`, so the "match" compared a boolean
    Series to a float and returned 21,264 of 21,272 rows - the first being a
    NaN.  The observable symptom is a NaN index where a number belongs.
    """
    value, dtype = db.n_at("RII-CAF2-MALITSON", 587.6)
    assert value == value, "n_at returned NaN - the filter is mis-parenthesised"
    assert value > 1.0
    assert dtype == "calculated"


def test_n_at_reports_unavailable_rather_than_guessing(db):
    """Outside the page's range, or for an unimplemented formula: no number."""
    assert db.n_at("RII-CAF2-MALITSON", 100000.0) == (None, None)
    # Ge/Edwards is upstream "formula 7", which GlassMatch does not evaluate.
    assert db.n_at("RII-GE-EDWARDS", 587.6) == (None, None)
    assert db.n_at("NOT-A-GLASS", 587.6) == (None, None)


def test_n_at_dispersion_is_monotonic_for_crystals(db):
    vals = [db.n_at("RII-CAF2-MALITSON", w)[0] for w in (587.6, 2000.0, 4000.0)]
    assert all(a > b for a, b in zip(vals, vals[1:])), vals


def test_tabulated_spectral_rows_are_verbatim(db):
    df = db.spectral_nk_for("RII-SI-FRANTA-20C")
    assert df is not None and len(df) > 100
    assert {"wavelength_um", "n", "k", "data_type"} <= set(df.columns)
    assert df["wavelength_um"].is_monotonic_increasing
    assert df["data_type"].str.contains("literature").all()


def test_spectral_nk_rows_all_carry_a_known_source(db):
    if db.spectral_nk.empty:
        pytest.skip("spectral_nk.csv not present")
    known = set(db.sources["source_id"].astype(str))
    used = set(db.spectral_nk["source_id"].dropna().astype(str))
    assert used and used <= known, sorted(used - known)[:5]


def test_no_crystal_value_is_invented(db):
    """n_at_reference rows must be calculated or interpolated, never blank."""
    rii = db.properties[db.properties["glass_id"].astype(str).str.startswith("RII-")
                        & (db.properties["property"] == "n_at_reference")]
    assert len(rii) > 500
    assert rii["value"].notna().all()
    assert set(rii["data_type"]) <= {"calculated", "interpolated"}
