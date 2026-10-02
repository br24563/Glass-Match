"""Tests: "Require available data" actually removes what it claims to.

The checkbox zeroed a glass's score but never dropped the row, so enabling it
returned every material in the database at 0% - page one of the results table
was a wall of zeros. It also had the wrong rule: it failed a glass for *any*
missing property, so a glass with perfect n_d, V_d and transmission but no
published density was discarded from a query that never mentioned density.
"""
import pandas as pd

from glassmatch.matching import (constrained_keys, match_glasses, score_glass)

W = {"nd": 30.0, "transmission": 30.0, "vd": 20.0, "density": 10.0, "cte": 10.0}


def _summary(rows):
    return pd.DataFrame(rows)


BASE = {
    "glass_id": "MFR-A", "glass": "A", "manufacturer": "MFR",
    "manufacturer_id": "MFR", "family": "crown",
    "material_class": "oxide_glass", "ir_mode": False,
    "nd": 1.5168, "vd": 64.17, "density": 2.51, "cte": 7.1,
}
NO_DENSITY = dict(BASE, glass_id="MFR-B", glass="B", density=None)
NO_TRANSMISSION = dict(BASE, glass_id="MFR-C", glass="C")

REQ_ALL = {"nd_min": 1.50, "nd_max": 1.55, "vd_min": 55, "vd_max": 70,
           "transmission_min": 90}


def test_constrained_keys_reflects_only_stated_requirements():
    assert constrained_keys(REQ_ALL) == {"nd", "vd", "transmission"}
    assert constrained_keys({"nd_min": 1.5}) == {"nd"}
    assert constrained_keys({}) == set()
    assert constrained_keys({"density_min": 2.0}) == {"density"}
    assert "cte" in constrained_keys({"cte_max": 20.0})


def test_require_data_drops_rows_rather_than_zeroing_them():
    """The regression: previously every material came back, all at 0%."""
    summary = _summary([BASE, NO_DENSITY, NO_TRANSMISSION])
    trans = {"MFR-A": 99.0, "MFR-B": 99.0}  # C has no transmission data

    kept = match_glasses(summary, REQ_ALL, W, transmissions=trans, require_data=True)
    assert "MFR-C" not in set(kept.glass_id), \
        "a glass with no transmission data must be dropped"
    assert kept.attrs["excluded_count"] == 1
    assert "MFR-A" in set(kept.glass_id)
    # Nothing survives at 0% - that was the visible symptom.
    assert (kept.compatibility > 0).all(), \
        kept[kept.compatibility <= 0].to_dict("records")


def test_require_data_keeps_a_glass_missing_an_unconstrained_property():
    """No density requirement was asked for, so absent density must not fail."""
    summary = _summary([BASE, NO_DENSITY])
    trans = {"MFR-A": 99.0, "MFR-B": 99.0}
    kept = match_glasses(summary, REQ_ALL, W, transmissions=trans, require_data=True)
    assert set(kept.glass_id) == {"MFR-A", "MFR-B"}
    assert kept.attrs["excluded_count"] == 0
    # It is still flagged, and the coverage factor still discounts it.
    row = kept[kept.glass_id == "MFR-B"].iloc[0]
    assert "density" in row["missing"]
    assert row["compatibility"] < \
        kept[kept.glass_id == "MFR-A"].iloc[0]["compatibility"]


def test_require_data_failures_are_reported_with_the_blocking_property():
    summary = _summary([BASE, NO_TRANSMISSION])
    trans = {"MFR-A": 99.0}
    kept = match_glasses(summary, REQ_ALL, W, transmissions=trans, require_data=True)
    examples = kept.attrs["excluded_examples"]
    assert len(examples) == 1
    assert examples[0]["glass_id"] == "MFR-C"
    assert "transmission" in examples[0]["blocking_missing"]


def test_require_data_off_keeps_everything():
    summary = _summary([BASE, NO_TRANSMISSION])
    kept = match_glasses(summary, REQ_ALL, W, transmissions={"MFR-A": 99.0},
                         require_data=False)
    assert len(kept) == 2
    assert kept.attrs["excluded_count"] == 0


def test_requiring_a_property_excludes_glasses_without_it():
    summary = _summary([BASE, NO_DENSITY])
    trans = {"MFR-A": 99.0, "MFR-B": 99.0}
    req = dict(REQ_ALL, density_min=2.0)
    kept = match_glasses(summary, req, W, transmissions=trans, require_data=True)
    assert set(kept.glass_id) == {"MFR-A"}
    assert kept.attrs["excluded_count"] == 1


def test_no_constraints_means_require_data_excludes_nothing():
    """Otherwise a bare query would silently drop most of the catalogue."""
    summary = _summary([NO_DENSITY, NO_TRANSMISSION])
    kept = match_glasses(summary, {}, W, transmissions={}, require_data=True)
    assert len(kept) == 2


def test_internal_columns_are_not_leaked_into_results():
    summary = _summary([BASE])
    kept = match_glasses(summary, REQ_ALL, W, transmissions={"MFR-A": 99.0},
                         require_data=True)
    assert "excluded" not in kept.columns
    assert "blocking_missing" not in kept.columns


def test_a_requirement_ranks_above_a_zero_weight():
    """Setting a range means "I need this", even if the weight slider is 0.

    The two controls are different kinds of intent: a requirement is a question
    the user asked, while a weight only tunes scoring priority. Typing a
    density range and then zeroing the density weight is self-contradictory
    input, and excluding such a glass is the safe direction - it returns fewer
    results, never more than the data supports. The app's real gate is the
    separate "Filter by density" checkbox, which is what stops the requirement
    from being sent at all.
    """
    summary = _summary([NO_DENSITY])
    w = dict(W, density=0.0)
    kept = match_glasses(summary, dict(REQ_ALL, density_min=2.0), w,
                         transmissions={"MFR-B": 99.0}, require_data=True)
    assert kept.attrs["excluded_count"] == 1
    assert len(kept) == 0


def test_excluded_rows_never_carry_a_positive_score():
    """Defence in depth: even if a caller shows the frame, excluded is 0%."""
    summary = _summary([NO_TRANSMISSION])
    kept = match_glasses(summary, REQ_ALL, W, transmissions={"MFR-C": 50.0},
                         require_data=True)
    assert len(kept) == 1
    sc = score_glass({"nd": 1.5168, "vd": 64.17, "density": 2.51, "cte": 7.1,
                      "transmission": None}, REQ_ALL, W, require_data=True)
    assert sc["excluded"] is True
    assert sc["overall"] == 0.0