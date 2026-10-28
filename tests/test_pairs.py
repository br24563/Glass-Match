"""Tests: glass map / partial dispersion and the pair finder (glassmatch.pairs).

The formula checks use the textbook N-BK7 / N-F2 achromat (SCHOTT catalog
V_d 64.17 and 36.37 in the classic worked example): phi1 = 2.3083 phi,
phi2 = -1.3083 phi, so a 100 mm doublet has a 43.3 mm crown and a -76.4 mm
flint.
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from glassmatch import pairs as P
from glassmatch.database import load_default_database
from glassmatch.plotting import glass_map_figure, partial_dispersion_figure


@pytest.fixture(scope="module")
def db():
    return load_default_database()


@pytest.fixture(scope="module")
def table(db):
    ids = ["SCHOTT-N-BK7", "SCHOTT-N-F2", "SCHOTT-N-FK51A", "SCHOTT-N-KZFS11",
           "SCHOTT-N-SF6"]
    summary = db.summary_frame()
    summary = summary[summary["glass_id"].isin(ids)]
    return P.glass_table(summary, P.partial_dispersion_table(db, ids), db)


# ---- formulas ----------------------------------------------------------------

def test_textbook_bk7_f2_power_split():
    phi1, phi2 = P.power_split(64.17, 36.37, phi=1.0)
    assert float(phi1) == pytest.approx(2.3083, abs=1e-4)
    assert float(phi2) == pytest.approx(-1.3083, abs=1e-4)
    assert float(phi1 + phi2) == pytest.approx(1.0)
    # Achromatic condition phi1/V1 + phi2/V2 = 0.
    assert float(phi1 / 64.17 + phi2 / 36.37) == pytest.approx(0.0, abs=1e-12)
    f = 100.0
    assert f / float(phi1) == pytest.approx(43.32, abs=0.01)
    assert f / float(phi2) == pytest.approx(-76.43, abs=0.01)


def test_power_split_scales_with_total_power():
    phi1, phi2 = P.power_split(64.17, 36.37, phi=0.02)   # f = 50 mm
    assert float(phi1) == pytest.approx(0.02 * 2.3083, rel=1e-4)
    assert float(phi1 + phi2) == pytest.approx(0.02)


def test_partial_dispersion_matches_schott_catalog(table):
    t = table.set_index("glass_id")
    # SCHOTT datasheet: N-BK7 P_g,F 0.5349, N-F2 0.5881.
    assert t.loc["SCHOTT-N-BK7", "pgf"] == pytest.approx(0.5349, abs=2e-4)
    assert t.loc["SCHOTT-N-F2", "pgf"] == pytest.approx(0.5881, abs=2e-4)
    # dPgF against the SCHOTT normal line reproduces SCHOTT's own stored dPgF.
    for gid in t.index:
        assert t.loc[gid, "dpgf_calc"] == pytest.approx(t.loc[gid, "dpgf_mfr"], abs=2e-4)
    assert (t["pgf_basis"] == P.PGF_BASIS).all()


def test_secondary_spectrum_formula():
    assert float(P.secondary_spectrum(0.5349, 0.5881, 64.17, 36.37)) == \
        pytest.approx((0.5349 - 0.5881) / (64.17 - 36.37))
    # Equal P_g,F (an apochromatic pair) -> no secondary spectrum.
    assert float(P.secondary_spectrum(0.55, 0.55, 80.0, 40.0)) == 0.0


def test_thermo_optic_coefficient_and_athermal_residual():
    # N-BK7: dn/dT 1.513e-6/K (calculated from TD), n_d 1.5168, CTE 7.1e-6/K.
    g = float(P.thermo_optic_coefficient(1.513, 1.5168, 7.1))
    assert g == pytest.approx(1.513 / 0.5168 - 7.1)
    # A single lens (phi2 = 0): f grows by -gamma per kelvin.
    assert float(P.thermal_focal_drift(1.0, 0.0, g, 0.0)) == pytest.approx(-g)
    # Hand-built pair whose drift equals the mount CTE ranks first with 0 residual.
    tab = pd.DataFrame({
        "glass_id": ["a", "b", "c"], "glass": ["A", "B", "C"],
        "manufacturer": ["X"] * 3, "vd": [60.0, 30.0, 35.0],
        "pgf": [0.54, 0.60, 0.59], "thermo_optic": [-5.0, -5.0, 3.0]})
    # a+b: phi1 = 2, phi2 = -1 -> drift = -(2*-5 + -1*-5) = 5.
    out = P.find_pairs(tab, sort_by="athermal", mount_cte=5.0, min_dv=5.0)
    assert (out["crown"].iloc[0], out["flint"].iloc[0]) == ("A", "B")
    assert out["thermal_residual"].iloc[0] == pytest.approx(0.0, abs=1e-12)


def test_athermal_needs_a_mount_cte():
    tab = pd.DataFrame({"glass_id": ["a", "b"], "glass": ["A", "B"],
                        "manufacturer": ["X", "X"], "vd": [60.0, 30.0],
                        "pgf": [0.54, 0.6], "thermo_optic": [1.0, 2.0]})
    with pytest.raises(ValueError):
        P.find_pairs(tab, sort_by="athermal")


# ---- ranking -----------------------------------------------------------------

def test_find_pairs_orders_crown_first_and_ranks_by_power(table):
    out = P.find_pairs(table, sort_by="power")
    assert (out["V1"] > out["V2"]).all()
    assert out["sum_abs_power"].is_monotonic_increasing
    row = out[(out["crown_id"] == "SCHOTT-N-BK7") & (out["flint_id"] == "SCHOTT-N-F2")]
    assert len(row) == 1
    v1, v2 = row["V1"].iloc[0], row["V2"].iloc[0]
    assert row["phi1"].iloc[0] == pytest.approx(v1 / (v1 - v2))
    assert row["phi2"].iloc[0] == pytest.approx(-v2 / (v1 - v2))


def test_secondary_ranking_prefers_anomalous_crown(table):
    out = P.find_pairs(table, sort_by="secondary")
    assert out["secondary_spectrum"].abs().is_monotonic_increasing
    # N-FK51A (dPgF +0.034) with N-KZFS11 (dPgF -0.012) is the classic
    # low-secondary-spectrum pairing among these glasses.
    assert out["crown"].iloc[0] == "N-FK51A"


def test_apo_candidates_obey_their_thresholds():
    rng = np.random.default_rng(1)
    n = 300
    tab = pd.DataFrame({"glass_id": [str(k) for k in range(n)],
                        "glass": [f"G{k}" for k in range(n)],
                        "manufacturer": "X", "vd": rng.uniform(20, 90, n),
                        "pgf": rng.uniform(0.52, 0.62, n),
                        "thermo_optic": rng.normal(0, 3, n)})
    out = P.find_pairs(tab, sort_by="apo", apo_dp_max=0.002, apo_min_dv=25)
    assert len(out)
    assert (out["dP"].abs() <= 0.002).all()
    assert ((out["V1"] - out["V2"]) >= 25).all()
    assert (-(out["V1"] - out["V2"])).is_monotonic_increasing


def test_missing_partial_dispersion_is_never_ranked_on_secondary():
    tab = pd.DataFrame({"glass_id": ["a", "b", "c"], "glass": ["A", "B", "C"],
                        "manufacturer": "X", "vd": [60.0, 30.0, 40.0],
                        "pgf": [0.54, np.nan, 0.58], "thermo_optic": np.nan})
    out = P.find_pairs(tab, sort_by="secondary", min_dv=5)
    assert set(out["flint"]) == {"C"}


# ---- performance -------------------------------------------------------------

def test_two_thousand_glasses_rank_in_seconds():
    rng = np.random.default_rng(0)
    n = 2000
    tab = pd.DataFrame({"glass_id": [str(k) for k in range(n)],
                        "glass": [f"G{k}" for k in range(n)],
                        "manufacturer": "X", "vd": rng.uniform(20, 90, n),
                        "pgf": rng.uniform(0.52, 0.62, n),
                        "thermo_optic": rng.normal(0, 3, n)})
    t0 = time.perf_counter()
    for key in ("power", "secondary", "apo", "athermal"):
        out = P.find_pairs(tab, sort_by=key, mount_cte=23.6, min_dv=0.0)
    elapsed = time.perf_counter() - t0
    assert out.attrs["n_pairs"] == n * (n - 1) // 2
    assert elapsed < 10.0, f"4 rankings of ~2M pairs took {elapsed:.1f}s"


# ---- labelling ---------------------------------------------------------------

def test_pairs_are_labelled_calculated_not_recommended(table):
    out = P.find_pairs(table, sort_by="power")
    assert "calculated" in out.attrs["basis"]
    assert "not a manufacturer recommendation" in out.attrs["basis"]
    assert (out["basis"] == P.PAIR_BASIS).all()


def test_figures_label_calculated_partial_dispersion(table):
    fig = partial_dispersion_figure(table, highlight=["SCHOTT-N-BK7"],
                                    pair=("SCHOTT-N-BK7", "SCHOTT-N-F2"))
    assert "calculated" in fig.layout.yaxis.title.text
    assert "calculated" in fig.layout.title.text
    names = [t.name for t in fig.data]
    assert any(n and n.startswith("normal line") for n in names)
    assert "selected pair" in names and "current match results" in names
    hover = " ".join(str(c) for t in fig.data if t.customdata is not None
                     for c in t.customdata)
    assert "(calculated)" in hover and "(manufacturer" in hover
    gm = glass_map_figure(table, highlight=["SCHOTT-N-F2"])
    assert gm.layout.xaxis.autorange == "reversed"
    assert "SCHOTT AG" in [t.name for t in gm.data]


def test_fit_range_short_of_g_line_gives_no_pgf(db):
    """Never extrapolate: a fit whose stated range stops above 435.8 nm
    must not get a P_g,F."""
    class Narrow:
        def glass_ids(self):
            return ["SCHOTT-N-BK7"]

        def sellmeier_for(self, gid, sellmeier_only=False):
            return db.sellmeier_for(gid, sellmeier_only=sellmeier_only)

        def dispersion_range(self, gid, coef):
            return 0.45, 2.5

    assert P.partial_dispersion_table(Narrow()).empty


# ---- app ---------------------------------------------------------------------

def test_app_has_glass_map_and_pair_finder_tabs():
    st_testing = pytest.importorskip("streamlit.testing.v1")
    import os
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    os.chdir(app_path.parent)
    app = st_testing.AppTest.from_file(str(app_path), default_timeout=600)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    labels = [t.label for t in app.tabs]
    assert "Glass Map" in labels and "Pair Finder" in labels
    rank = next(r for r in app.radio if r.key == "pf_rank")
    rank.set_value("Athermal (mount CTE)").run()
    assert not app.exception, [e.value for e in app.exception]
    gm = next(r for r in app.radio if r.key == "gm_kind")
    gm.set_value("P_g,F vs V_d (partial dispersion)").run()
    assert not app.exception, [e.value for e in app.exception]
