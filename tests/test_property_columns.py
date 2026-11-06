"""Tests: newly imported properties, derived figures, n2, and the sortable
column layer (app + CLI)."""
import math

import pandas as pd
import pytest

from glassmatch import columns as gm_columns
from glassmatch import derived as dv
from glassmatch.cli import main as cli
from glassmatch.database import MAKER_SCALE_COLUMNS, load_default_database
from glassmatch.importers.maker_xlsx import colour_code
from glassmatch.spectra import dn_dt_abs, n_from_row


@pytest.fixture(scope="module")
def db():
    return load_default_database()


@pytest.fixture(scope="module")
def table(db):
    s = db.summary_frame()
    tg = {str(g): x for g, x in db.transmission.groupby("glass_id")}
    return gm_columns.columns(db, s, tg, 10.0, 800.0)


# --- colour-code parsing ------------------------------------------------------

def test_colour_code_cells():
    assert colour_code(10.0)("33/29") == {"uv_edge_80_nm": 330.0, "uv_edge_5_nm": 290.0}
    # SCHOTT marks a lambda70 value with '*'
    assert colour_code(10.0)("45/37*") == {"uv_edge_70_nm": 450.0, "uv_edge_5_nm": 370.0}
    assert colour_code()("340/-") == {"uv_edge_80_nm": 340.0}          # CDGM
    assert colour_code(hi=70)("425/365") == {"uv_edge_70_nm": 425.0,
                                             "uv_edge_5_nm": 365.0}
    assert colour_code(internal=True)("302/269") == {
        "uv_edge_internal_80_nm": 302.0, "uv_edge_internal_5_nm": 269.0}
    for empty in ("-", "", None, "n/a"):
        assert colour_code()(empty) is None


# --- imported properties ------------------------------------------------------

def test_new_workbook_properties_in_shipped_data(db):
    v = db.property_value
    assert v("SCHOTT-N-BK7", "uv_edge_80_nm") == 330.0     # colour code 33/29
    assert v("SCHOTT-N-BK7", "uv_edge_5_nm") == 290.0
    assert v("SCHOTT-N-BK7", "annealing_point") == 557.0   # T13
    assert v("SCHOTT-N-BK7", "relative_cost") == 1.0       # reference glass
    assert v("CDGM-H-K9L", "relative_cost") == 1.0         # CDGM coefficient / 10
    g = db.glasses.set_index("glass_id")
    assert g.loc["CDGM-H-K9L", "production_frequency"] == "MA"
    assert g["production_frequency"].isin(["A", "B", "C", "D"]).sum() > 100


def test_agf_typos_corrected_only_with_two_sources(db):
    v = db.property_value
    assert v("CDGM-H-TK9", "refractive_index_nd") == 1.62075
    assert v("HOYA-MC-TAF115", "refractive_index_nd") == 1.77047
    for gid in ("CDGM-H-TK9", "HOYA-MC-TAF115", "HOYA-MC-FAD61"):
        fit = db.sellmeier_for(gid, sellmeier_only=True)
        assert fit is not None, gid
        assert abs(n_from_row(fit, 0.5875618) - v(gid, "refractive_index_nd")) < 2e-4
    # rounding-level V_d differences keep the .agf value
    rows = db.property_provenance("CDGM-H-ZK7", "abbe_number_vd")
    assert rows[0]["source_id"] == "CDGM-AGF-2026-09"


def test_schott_tabulated_dn_dt_matches_td_coefficients(db):
    p = db.properties
    td = p[p["property"].str.startswith("td_")].pivot_table(
        index="glass_id", columns="property", values="value", aggfunc="first")
    worst, n = 0.0, 0
    for col, wl in (("dn_dt_abs_e_20_40", 0.546074),
                    ("dn_dt_abs_g_20_40", 0.4358343),
                    ("dn_dt_abs_1060_20_40", 1.06)):
        cat = p[p["property"] == col].set_index("glass_id")["value"].astype(float)
        for gid, v in cat.items():
            fit = db.sellmeier_for(gid, sellmeier_only=True)
            if gid not in td.index or fit is None:
                continue
            r = td.loc[gid]
            c = dn_dt_abs([r.td_D0, r.td_D1, r.td_D2, r.td_E0, r.td_E1,
                           r.td_lambda_tk, r.td_T0],
                          n_from_row(fit, wl), wl, 20, 40) * 1e6
            worst, n = max(worst, abs(c - v)), n + 1
    assert n > 400 and worst <= 0.1      # SCHOTT prints one decimal


def test_n2_measurements_are_their_own_table(db):
    t = db.nonlinear_n2
    assert len(t) > 150 and t["material"].nunique() >= 15
    milam = t[(t["source_id"] == "RII-CAF2-MILAM-N2")]
    assert milam["n2_m2_per_w"].iloc[0] == pytest.approx(1.9e-20)
    assert milam["wavelength_um"].iloc[0] == pytest.approx(1.064)
    # never read as an index or stored as a property
    assert not db.properties["property"].str.contains("n2").any()
    assert (t["n2_m2_per_w"].abs() < 1e-14).all()


# --- derived figures ------------------------------------------------------------

def test_optical_figures_match_catalog_values(table):
    bk7 = table.loc["SCHOTT-N-BK7"]
    assert bk7["ne"] == pytest.approx(1.51872, abs=2e-5)
    assert bk7["ve"] == pytest.approx(63.96, abs=0.02)
    assert bk7["pgf"] == pytest.approx(0.5349, abs=2e-4)
    assert bk7["dpgf_calc"] == pytest.approx(-0.0009, abs=3e-4)


def test_gvd_and_group_index_at_800_nm(table):
    assert table.loc["SCHOTT-N-BK7", "gvd"] == pytest.approx(44.65, abs=0.1)
    assert table.loc["SCHOTT-N-BK7", "group_index"] == pytest.approx(1.5266, abs=2e-4)
    assert table.loc["RII-SIO2-MALITSON", "gvd"] == pytest.approx(36.16, abs=0.1)


def test_wavelength_figures_are_never_extrapolated(db):
    w = dv.at_wavelength(db, 5000.0)          # far outside most glass fits
    assert "SCHOTT-N-BK7" not in w.index      # N-BK7's fit stops at 2.5 um


def test_thermo_mechanical_formulas():
    s = pd.DataFrame([{"glass_id": "G", "nd": 1.5168, "dn_dt": 1.513,
                       "cte": 7.1, "k_thermal": 1.114, "poisson": 0.206,
                       "young": 82.0, "density": 2.51}])
    t = dv.thermo_mechanical(s).loc["G"]
    assert t["athermal_gamma_vacuum"] == pytest.approx(1.513 / 0.5168 - 7.1)
    # In air, relative dn/dT: larger than absolute by ~n |dn_air/dT|.
    assert t["dn_dt_rel_calc"] == pytest.approx(1.513 + 1.32, abs=0.02)
    assert t["athermal_gamma_air"] == pytest.approx(
        t["dn_dt_rel_calc"] / 0.5168 - 7.1)
    assert t["athermal_gamma_air"] - t["athermal_gamma_vacuum"] > 2.5
    assert t["thermal_shock_fom"] == pytest.approx(
        1.114 * (1 - 0.206) / (7.1e-6 * 82e9) * 1e6)
    assert t["specific_stiffness"] == pytest.approx(82.0 / 2.51)


def test_uv_edge_matches_internal_colour_codes(db, table):
    p = db.properties
    cat = p[p["property"] == "uv_edge_internal_80_nm"].set_index(
        "glass_id")["value"].astype(float)
    j = pd.concat([cat, table["uv_edge_int80_calc"]], axis=1).dropna()
    d = (j.iloc[:, 1] - j.iloc[:, 0]).abs()
    assert len(j) > 400 and (d <= 5).mean() > 0.95


def test_transmission_figures_need_bracketing_samples():
    tdf = pd.DataFrame({"wavelength_um": [0.40, 0.50, 0.60],
                        "transmission": [0.10, 0.90, 0.99],
                        "thickness_mm": [10.0] * 3})
    t = dv.transmission_figures({"G": tdf}, 10.0).loc["G"]
    assert t["uv_edge_int80_calc"] == pytest.approx(400 + (0.8 - 0.1) / 0.8 * 100)
    assert t["uv_edge_int5_calc"] is None or math.isnan(t["uv_edge_int5_calc"])
    assert t["t_532"] == pytest.approx((0.9 + 0.32 * 0.09) * 100)
    assert t["t_355"] is None or math.isnan(t["t_355"])   # below the samples


# --- column layer -----------------------------------------------------------------

def test_every_column_is_labelled_and_maker_scales_flagged(table):
    labels = gm_columns.labels()
    assert set(table.columns) <= set(labels)
    for c in MAKER_SCALE_COLUMNS:
        assert "maker's own scale" in labels[c][0]
    for c in dv.LABELS:
        assert "calculated" in labels[c][0]


def test_range_filter_keeps_missing_unless_required():
    t = pd.DataFrame({"x": [1.0, 5.0, None]}, index=["a", "b", "c"])
    assert list(gm_columns.range_filter(t, {"x": (0, 2)})) == [True, False, True]
    assert list(gm_columns.range_filter(t, {"x": (0, 2)}, keep_missing=False)) == [
        True, False, False]


def test_cli_sort_where_columns(tmp_path):
    out = tmp_path / "r.csv"
    assert cli(["search", "--vd", "55:75", "--where", "athermal_gamma_air=-1:1",
                "--sort", "athermal_gamma_air", "--columns", "cte", "--top", "5",
                "--csv", str(out)]) == 0
    r = pd.read_csv(out)
    assert len(r) == 5 and r["athermal_gamma_air"].between(-1, 1).all()
    assert r["athermal_gamma_air"].is_monotonic_increasing


def test_cli_columns_n2_and_unknown_column(capsys):
    assert cli(["columns"]) == 0
    assert "athermal_gamma" in capsys.readouterr().out
    assert cli(["n2", "--material", "CaF2"]) == 0
    assert "RII-CAF2-MILAM-N2" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown column"):
        cli(["search", "--sort", "not_a_column"])


def test_maker_scale_filter_needs_a_maker():
    """Chemical classes are each maker's own scale: no cross-maker range."""
    t = pd.DataFrame({"acid_resistance": [1.0, 2.0, 1.0, None]},
                     index=["A1", "A2", "B1", "A3"])
    makers = ["OHARA", "OHARA", "SCHOTT", "OHARA"]
    with pytest.raises(ValueError, match="own scale"):
        gm_columns.range_filter(t, {"acid_resistance": (None, 1)}, makers=makers)
    m = gm_columns.range_filter(t, {"acid_resistance": (None, 1, "OHARA")},
                                makers=makers)
    assert list(m) == [True, False, False, True]      # SCHOTT dropped
    m = gm_columns.range_filter(t, {"acid_resistance": (None, 1, "ohara")},
                                makers=makers, keep_missing=False)
    assert list(m) == [True, False, False, False]


def test_cli_maker_scale_filter(tmp_path):
    with pytest.raises(SystemExit, match="own scale"):
        cli(["search", "--where", "acid_resistance=1:2"])
    out = tmp_path / "r.csv"
    assert cli(["search", "--where", "acid_resistance@OHARA=1:2",
                "--require-data", "--top", "20", "--csv", str(out)]) == 0
    r = pd.read_csv(out)
    assert len(r) and r["glass_id"].str.startswith("OHARA-").all()
    assert r["acid_resistance"].between(1, 2).all()
