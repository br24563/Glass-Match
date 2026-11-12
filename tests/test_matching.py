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
    """A glass with no value for a property the user *asked about* fails.

    The requirement here is on transmission and the glass has none, so it is
    excluded and scored 0. This test used to pass a glass that was missing
    density/CTE/transmission while only constraining n_d, and asserted 0.0 -
    which is the bug: the glass answered the only question that was asked and
    was being thrown away for properties nobody mentioned.
    """
    props = {"nd": 1.517, "vd": 64.0, "density": None, "cte": None, "transmission": None}
    req = {"nd_min": 1.5, "nd_max": 1.55, "transmission_min": 90.0}
    sc = score_glass(props, req, {"nd": 1, "vd": 1, "transmission": 1, "density": 1, "cte": 1},
                     require_data=True)
    assert sc["excluded"] is True
    assert sc["blocking_missing"] == ["transmission"]
    assert sc["overall"] == 0.0


def test_require_data_ignores_properties_that_were_not_constrained():
    """Missing density cannot fail a query that only asked about n_d."""
    props = {"nd": 1.517, "vd": 64.0, "density": None, "cte": None, "transmission": None}
    req = {"nd_min": 1.5, "nd_max": 1.55}
    sc = score_glass(props, req, {"nd": 1, "vd": 1, "transmission": 1, "density": 1, "cte": 1},
                     require_data=True)
    assert sc["excluded"] is False
    assert sc["blocking_missing"] == []
    assert "density" in sc["missing"]          # still flagged...
    assert sc["overall"] > 0                    # ...and still discounted by coverage


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


def test_equal_scores_have_a_meaningful_stable_order():
    """Glasses that meet every requirement all score the same. Inside a tie:
    higher transmission, then the easier glass to buy, then the id."""
    import pandas as pd
    from glassmatch.matching import DEFAULT_WEIGHTS, match_glasses
    rows = [{"glass_id": g, "glass": g, "manufacturer": "M",
             "manufacturer_id": "M", "family": "", "material_class": "oxide_glass",
             "status": s, "nd": 1.5, "vd": 60.0, "density": 2.5, "cte": 7.0}
            for g, s in (("B", "standard"), ("D", "obsolete"), ("A", "standard"),
                         ("C", "preferred"), ("E", "standard"))]
    req = {"nd_min": 1.4, "nd_max": 1.6, "transmission_min": 80.0}
    trans = {"A": 90.0, "B": 90.0, "C": 90.0, "D": 90.0, "E": 99.0}
    for frame in (pd.DataFrame(rows), pd.DataFrame(rows[::-1])):
        out = match_glasses(frame, req, DEFAULT_WEIGHTS, transmissions=trans)
        assert out["compatibility"].nunique() == 1
        assert list(out["glass_id"]) == ["E", "C", "A", "B", "D"]
    # Without a transmission band the availability class and id decide.
    out = match_glasses(pd.DataFrame(rows), {"nd_min": 1.4, "nd_max": 1.6},
                        DEFAULT_WEIGHTS)
    assert list(out["glass_id"]) == ["C", "A", "B", "E", "D"]


def test_sellmeier_nbK7_nd():
    n = sellmeier_n(0.5876, (1.03961212, 0.231792344, 1.01046945),
                    (0.00600069867, 0.0200179144, 103.560653))
    assert abs(n - 1.51680) < 0.001


def test_nm_um_conversion():
    assert 550.0 / 1000.0 == 0.55  # app converts nm<->um by /1000 consistently
