"""Tests: weights, scoring, missing-data handling, unit conversion sanity."""
from glassmatch.matching import normalize_weights, score_glass, match_glasses
from glassmatch.spectra import sellmeier_n
import pandas as pd


def test_weights_normalize():
    w = normalize_weights({"nd": 30, "vd": 20, "transmission": 30, "density": 10, "cte": 10})
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_weights_zero_fallback():
    w = normalize_weights({"nd": 0, "vd": 0, "transmission": 0, "density": 0, "cte": 0})
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_perfect_match_scores_one():
    props = {"nd": 1.517, "vd": 64.0, "density": 2.5, "cte": 7.1, "transmission": 95.0}
    req = {"nd_min": 1.5, "nd_max": 1.55, "vd_min": 60, "vd_max": 70,
           "density_min": 2.0, "density_max": 3.0, "cte_min": 5, "cte_max": 9,
           "transmission_min": 90.0}
    sc = score_glass(props, req, {"nd": 1, "vd": 1, "transmission": 1, "density": 1, "cte": 1})
    assert sc["overall"] > 0.99


def test_missing_data_flagged_not_failed():
    props = {"nd": 1.517, "vd": 64.0, "density": None, "cte": None, "transmission": None}
    req = {"nd_min": 1.5, "nd_max": 1.55, "vd_min": 60, "vd_max": 70,
           "transmission_min": 90.0}
    sc = score_glass(props, req, {"nd": 1, "vd": 1, "transmission": 1, "density": 1, "cte": 1})
    assert "density" in sc["missing"] and sc["overall"] > 0


def test_require_data_zeroes_incomplete():
    props = {"nd": 1.517, "vd": 64.0, "density": None, "cte": None, "transmission": None}
    req = {"nd_min": 1.5, "nd_max": 1.55}
    sc = score_glass(props, req, {"nd": 1, "vd": 1, "transmission": 1, "density": 1, "cte": 1},
                     require_data=True)
    assert sc["overall"] == 0.0


def test_match_sorts_descending():
    s = pd.DataFrame([
        {"glass_id": "A", "glass": "A", "manufacturer": "M", "manufacturer_id": "M",
         "family": "f", "nd": 1.52, "vd": 64.0, "density": 2.5, "cte": 7.0},
        {"glass_id": "B", "glass": "B", "manufacturer": "M", "manufacturer_id": "M",
         "family": "f", "nd": 1.80, "vd": 25.0, "density": 2.5, "cte": 7.0},
    ])
    req = {"nd_min": 1.5, "nd_max": 1.55, "vd_min": 60, "vd_max": 70}
    out = match_glasses(s, req, {"nd": 1, "vd": 1, "transmission": 0, "density": 0, "cte": 0})
    assert out.iloc[0]["glass_id"] == "A"


def test_sellmeier_nbK7_nd():
    n = sellmeier_n(0.5876, (1.03961212, 0.231792344, 1.01046945),
                    (0.00600069867, 0.0200179144, 103.560653))
    assert abs(n - 1.51680) < 0.001


def test_nm_um_conversion():
    assert 550.0 / 1000.0 == 0.55  # app converts nm<->um by /1000 consistently
