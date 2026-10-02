"""UI-level regression tests: the two `app.py` paths that call `GlassDatabase.n_at`.

`app.py` resolves an index for every material with no catalog n_d before it can
rank anything, and the Glass Detail tab resolves the index the user asked for.
Both go through the interpolation branch of `n_at` whenever the wavelength is
off the grid of stored reference rows.  The default 587.6 nm happens to sit on
that grid for every crystal, which is why the `zip(..., None)` crash survived
so long: at the default settings the broken branch is never entered, and no
test had ever moved the wavelength control.

Set the reference wavelength to 1550 nm - a routine telecom choice - and 70
materials entered the branch, so the app died on startup with
`TypeError: 'NoneType' object is not iterable` instead of showing results.
"""
import os
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")

# 1550 nm is covered by the tabulated n/k of many crystals but matches no
# stored n_at_reference row, so it is what forces the interpolation branch.
OFF_GRID_NM = 1550.0
# A crystal that the sweep showed is answered by interpolation at 1550 nm.
INTERPOLATED_CRYSTAL = "RII-AL2O3-BOIDIN"


def _app():
    os.chdir(Path(APP_PATH).parent)
    return AppTest.from_file(APP_PATH, default_timeout=600)


def _sidebar(app, label):
    for w in app.sidebar.number_input:
        if w.label == label:
            return w
    raise AssertionError(f"sidebar number_input {label!r} not found")


def test_app_starts_and_ranks_at_the_default_reference_wavelength():
    """Baseline: the app must run at all, or the other tests prove nothing."""
    app = _app()
    app.run()
    assert not app.exception, f"app raised at default settings: {[e.value for e in app.exception]}"


def test_matching_loop_survives_an_off_grid_reference_wavelength():
    """The regression: 70 materials hit n_at's interpolation branch here."""
    app = _app()
    app.run()
    _sidebar(app, "Index reference wavelength (nm)").set_value(OFF_GRID_NM)
    app.run()
    assert not app.exception, (
        f"app raised at {OFF_GRID_NM:g} nm: {[str(e.value) for e in app.exception]}")
    # ...and it must still produce a ranked table, not an empty page
    assert app.dataframe, "no results table was rendered"


def test_glass_detail_reports_an_interpolated_index_for_a_crystal():
    """The Glass Detail tab resolves n at a user-entered wavelength.

    A crystal with tabulated samples and no stored row at that wavelength must
    be answered from the table and labelled `interpolated` - a calculated
    number may never be presented as a manufacturer or literature value.
    """
    app = _app()
    app.run()
    glass = next(w for w in app.selectbox if w.label == "Glass")
    assert INTERPOLATED_CRYSTAL in glass.options, "crystal missing from the picker"
    glass.set_value(INTERPOLATED_CRYSTAL)
    app.run()
    assert not app.exception, f"[1] {[str(e.value) for e in app.exception]}"
    key = f"nref_{INTERPOLATED_CRYSTAL}"
    wl = next((w for w in app.number_input if w.key == key), None)
    assert wl is not None, f"index wavelength control {key!r} was not rendered"
    wl.set_value(OFF_GRID_NM)
    app.run()
    assert not app.exception, f"[2] {[str(e.value) for e in app.exception]}"
    text = " ".join(str(m.value) for m in app.markdown)
    assert "Refractive index at 1550 nm" in text, "the index was not shown at all"
    assert "interpolated" in text, (
        "index was not labelled interpolated - provenance is missing or wrong")
