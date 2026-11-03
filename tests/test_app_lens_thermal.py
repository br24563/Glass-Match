"""App: the Lens Glass Replacement tab and the n(lambda, T, p) section of
Glass Detail render, react to their controls, and say what they are."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(scope="module")
def at():
    a = AppTest.from_file(APP_PATH, default_timeout=600)
    a.run()
    assert not a.exception
    return a


def test_lens_tab_ranks_and_resolves(at):
    assert any(m.label == "EFL (d)" and m.value.startswith("99.90")
               for m in at.metric)
    at.selectbox(key="rx_old").set_value("SCHOTT-N-SF5")
    at.selectbox(key="rx_res").set_value(2).run()
    assert not at.exception
    df = next(d.value for d in at.dataframe if "colour_change_mm" in d.value.columns)
    assert df["glass_id"].iloc[0] == "HOYA-E-FD5"
    assert (df["efl_change_pct"].abs() < 1e-8).all()
    assert any("first-order" in c.value.lower() for c in at.caption)


def test_thermal_section(at):
    at.number_input(key="th_t").set_value(-60).run()
    assert not at.exception
    df = next(d.value for d in at.dataframe
              if "n(λ, T, p) (calculated)" in d.value.columns)
    assert len(df) == 9 and df["method"].str.len().gt(0).any()
