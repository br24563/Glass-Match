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
    at.radio(key="rx_mode").set_value("Re-solve one surface for the system EFL").run()
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


def test_two_bands_in_app(at):
    at.number_input(key="n_extra_bands").set_value(1).run()
    at.number_input(key="band0_lo").set_value(9000.0)
    at.number_input(key="band0_hi").set_value(10000.0).run()
    assert not at.exception
    df = at.dataframe[0].value
    worst = "transmission_% (worst band)"
    assert {worst, "T 0.4-0.7 um (%)", "T 9-10 um (%)"} <= set(df.columns)
    both = df.dropna(subset=["T 0.4-0.7 um (%)", "T 9-10 um (%)"])
    assert len(both) and (both[worst] == both[["T 0.4-0.7 um (%)",
                                                "T 9-10 um (%)"]].min(axis=1)).all()
    # A band with no data never passes as if it had.
    assert df.loc[df["T 9-10 um (%)"].isna(), worst].isna().all()
    at.number_input(key="n_extra_bands").set_value(0).run()


def test_lens_tab_writes_modified_design(at):
    at.selectbox(key="rx_old").set_value("SCHOTT-N-SF5")
    at.radio(key="rx_mode").set_value(
        "Keep each replaced element's power (recommended)").run()
    assert not at.exception
    assert any(b.label.startswith("Download modified design")
               for b in at.get("download_button"))
    assert any("element power held" in c.value for c in at.caption)


def test_lwir_band_mode():
    a = AppTest.from_file(APP_PATH, default_timeout=600)
    a.run()
    [s for s in a.selectbox if s.label == "Wavelength preset"][0].set_value(
        "LWIR (8.00-12.00 um)").run()
    a.selectbox(key="disp_band").set_value("LWIR (8 / 10 / 12 um)").run()
    assert not a.exception
    assert any("Glass map - 8/10/12 um" in h.value for h in a.header)
    assert any("required band" in c.value for c in a.caption)
    a.radio(key="pf_rank").set_value("Low secondary spectrum").run()
    assert not a.exception
    pairs = [d.value for d in a.dataframe if "crown" in d.value.columns]
    if pairs and len(pairs[0]):
        p = pairs[0]
        mat = lambda s: s.str.split(" (", regex=False).str[0]  # noqa: E731
        assert (mat(p["crown"]) != mat(p["flint"])).all()     # two materials
        assert not p["crown"].str.contains("-ray").any()
        assert not p["flint"].str.contains("-ray").any()
