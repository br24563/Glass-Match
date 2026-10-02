"""Tests: `GlassDatabase.n_at()` interpolation branch.

The interpolation branch is reached whenever a material has tabulated n
samples and the requested wavelength does not match a stored
`n_at_reference` row - which is the ordinary case for a crystal asked
about an off-grid wavelength.  It was also effectively dead code: the call
built its rows with ``zip(wavelengths, n, None)``, and zipping with `None`
raises ``TypeError: 'NoneType' object is not iterable`` before `_interp`
is ever reached.  123 of the 124 materials that can reach the branch
therefore crashed rather than answered.

These tests pin the three things that matter: the interpolated number is a
true linear interpolation of the source table, an out-of-range request
still declines instead of extrapolating, and no material with tabulated
data can raise.
"""
import bisect
from pathlib import Path

import pandas as pd
import pytest

from glassmatch.database import DEFAULT_DATA_DIR, GlassDatabase


def _db_with_table(rows, sellmeier=None, properties=None):
    """A database holding exactly one material's tabulated n/k samples."""
    return GlassDatabase(
        glasses=pd.DataFrame([{"glass_id": "T-TEST-MAT", "glass": "TESTMAT",
                               "manufacturer_id": "TEST", "material_class": "crystal"}]),
        properties=pd.DataFrame(properties or []),
        sellmeier=pd.DataFrame(sellmeier or []),
        spectral_nk=pd.DataFrame([
            {"glass_id": "T-TEST-MAT", "wavelength_um": w, "n": n, "k": None,
             "data_type": "manufacturer", "source_id": "TEST-SRC",
             "measurement_form": "n (bulk)"}
            for w, n in rows
        ]),
    )


# n falls linearly with wavelength: 1.50 at 0.40 um down to 1.40 at 0.70 um.
TABLE = [(0.40, 1.50), (0.45, 1.48), (0.50, 1.46), (0.55, 1.44),
         (0.60, 1.42), (0.65, 1.41), (0.70, 1.40)]


def test_interpolation_matches_manual_linear_interpolation():
    """Midpoint of the 0.45/0.50 um samples -> mean of 1.48 and 1.46."""
    db = _db_with_table(TABLE)
    value, data_type = db.n_at("T-TEST-MAT", 475.0)  # 0.475 um
    assert value == pytest.approx(1.47, abs=1e-12), value
    assert data_type == "interpolated", data_type


def test_interpolation_at_a_non_midpoint_offset_is_linear():
    """0.4625 um lies a quarter of the way 0.45 -> 0.50, so n = 1.475."""
    db = _db_with_table(TABLE)
    value, _ = db.n_at("T-TEST-MAT", 462.5)
    assert value == pytest.approx(1.475, abs=1e-12), value


def test_interpolation_uses_the_bracketing_samples_not_the_endpoints():
    """Guards against interpolating across the whole table instead of the
    local segment: 0.625 um is the midpoint of the 0.60/0.65 samples, so the
    answer is mean(1.42, 1.41) - not the 1.45 a whole-table line would give."""
    db = _db_with_table(TABLE)
    value, _ = db.n_at("T-TEST-MAT", 625.0)
    assert value == pytest.approx(1.415, abs=1e-12), value


@pytest.mark.parametrize("wl_nm", [350.0, 399.9, 700.1, 800.0, 10000.0])
def test_outside_the_tabulated_range_is_unavailable_not_extrapolated(wl_nm):
    """No stored row, no table coverage, no verified Sellmeier -> no answer."""
    db = _db_with_table(TABLE)
    value, data_type = db.n_at("T-TEST-MAT", wl_nm)
    assert value is None, f"extrapolated {value} at {wl_nm} nm"
    assert data_type is None, data_type


def test_a_stored_reference_row_still_wins_over_the_table():
    """Precedence: a literature `n_at_reference` row is reported as such and
    is not overwritten by interpolating the neighbouring samples."""
    db = _db_with_table(TABLE, properties=[{
        "glass_id": "T-TEST-MAT", "property": "n_at_reference", "value": 1.999,
        "unit": "", "reference_wavelength_nm": 475.0, "data_type": "calculated",
        "source_id": "TEST-SRC", "notes": "",
    }])
    value, data_type = db.n_at("T-TEST-MAT", 475.0)
    assert value == pytest.approx(1.999), value
    assert data_type == "calculated", data_type


def test_nan_n_samples_are_skipped_rather_than_interpolated_through():
    """A table with gaps must interpolate between the surviving samples."""
    db = _db_with_table([(0.40, 1.50), (0.45, float("nan")), (0.50, 1.46)])
    value, data_type = db.n_at("T-TEST-MAT", 450.0)
    assert data_type == "interpolated", data_type
    assert value == pytest.approx(1.48, abs=1e-12), value



# --- the shipped database: nothing may raise -------------------------------

@pytest.fixture(scope="module")
def db():
    return GlassDatabase.load()


_DB_CACHE = {}


def _shared_db():
    """GlassDatabase.load() once for the parametrized sweep; a module-scoped
    fixture cannot be used as a parametrize argument."""
    if "db" not in _DB_CACHE:
        _DB_CACHE["db"] = GlassDatabase.load()
    return _DB_CACHE["db"]


def _tabulated_ids():
    """glass_ids with >= 2 tabulated n samples.  Read straight from the CSV so
    parametrization does not have to build a whole GlassDatabase."""
    f = pd.read_csv(Path(DEFAULT_DATA_DIR) / "spectral_nk.csv", encoding="utf-8")
    f = f.dropna(subset=["n"])
    return sorted(str(g) for g, grp in f.groupby("glass_id") if len(grp) >= 2)


def test_every_tabulated_material_can_be_interpolated(db):
    """The sweep the old code failed: 123 of these raised TypeError."""
    n = db.spectral_nk.dropna(subset=["n"])
    material_ids = _tabulated_ids()
    assert len(material_ids) > 100, material_ids[:5]
    failures = []
    for gid in material_ids:
        pts = n[n["glass_id"] == gid].sort_values("wavelength_um")
        w = pts["wavelength_um"].tolist()
        mid_um = (w[0] + w[-1]) / 2.0
        try:
            db.n_at(gid, mid_um * 1000.0)
        except Exception as exc:  # noqa: BLE001 - catching anything is the point
            failures.append(f"{gid} @ {mid_um:.4f} um: {type(exc).__name__}: {exc}")
    assert not failures, f"{len(failures)} materials raised:\n" + "\n".join(failures[:5])


@pytest.mark.parametrize("gid", _tabulated_ids())
def test_n_at_never_raises_for_tabulated_materials(gid):
    """One case per material, in range and deliberately out of range."""
    database = _shared_db()
    pts = database.spectral_nk
    pts = pts[pts["glass_id"] == gid].dropna(subset=["n"]).sort_values("wavelength_um")
    w, v = pts["wavelength_um"].tolist(), pts["n"].tolist()
    for wl_um in (w[0], w[-1], (w[0] + w[-1]) / 2.0, w[0] / 2.0, w[-1] * 2.0):
        value, data_type = database.n_at(gid, wl_um * 1000.0)
        assert value is None or (value == value and value > 0), (gid, wl_um, value)
        assert (value is None) == (data_type is None), (gid, wl_um, value, data_type)
    # when the table is what answers, it must agree with a manual interpolation
    mid = (w[0] + w[-1]) / 2.0
    i = max(0, min(bisect.bisect_right(w, mid) - 1, len(w) - 2))
    w0, w1, n0, n1 = w[i], w[i + 1], v[i], v[i + 1]
    manual = n0 if w1 == w0 else n0 + (n1 - n0) * (mid - w0) / (w1 - w0)
    value, data_type = database.n_at(gid, mid * 1000.0)
    # Unconditional on purpose.  The weak version of this sweep was a
    # `if data_type == "interpolated"` guard, and the bug it was meant to
    # catch presented itself as (None, "unavailable") at a wavelength the
    # table plainly covers, so a conditional check sails through it.
    assert value is not None, (gid, mid, data_type)
    assert data_type == "interpolated", (gid, mid, value, data_type)
    assert value == pytest.approx(manual, abs=1e-9), (gid, mid, value, manual)


def test_interp_helper_takes_the_two_column_rows_callers_build():
    """The bug was in how the caller built the rows, not in the maths.

    ``_interp(wl, rows, col)`` reads ``r[col]`` on every row, and ``n_at``
    built those rows with ``list(zip(wavelengths, n_values, None))`` - ``zip()``
    iterates its arguments, so the ``None`` raised TypeError before ``_interp``
    was even entered.  Pin the contract here, because a sweep through ``n_at``
    alone reports the resulting (None, "unavailable") as though it were a
    legitimate "this source does not cover it" answer.
    """
    from glassmatch.importers.refractiveindex_yaml import _interp

    rows = [(0.5, 1.5), (1.0, 1.6), (2.0, 1.4)]
    value, rng = _interp(0.75, rows)
    assert value == pytest.approx(1.55), (value, rng)

    # Unsorted input is sorted internally, so callers need not pre-sort.
    value, rng = _interp(1.5, [(2.0, 1.4), (0.5, 1.5), (1.0, 1.6)])
    assert value == pytest.approx(1.50), (value, rng)

    # Outside the table it declines, and reports the span it does cover.
    value, rng = _interp(0.1, rows)
    assert value is None and rng == (0.5, 2.0), (value, rng)

    # A third, empty zip argument is exactly what used to be built.
    with pytest.raises(TypeError):
        list(zip([0.5, 1.0], [1.5, 1.6], None))

    # ...and the parametrized sweep really does have materials to sweep.
    assert len(_tabulated_ids()) > 100

