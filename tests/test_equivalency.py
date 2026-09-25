"""Equivalency candidate engine: gating, orientation, missing data, capping."""
import math

import pandas as pd
import pytest

from glassmatch.equivalency import (COMPARED_PROPERTIES, EquivalencyCriteria,
                                    _normalize_orientation, candidate_pairs,
                                    candidates_for, curated_equivalents,
                                    equivalence_report)


def _summary(rows):
    """Minimal stand-in for GlassDatabase.summary_frame()."""
    base = {"glass": "", "manufacturer": "", "material_class": "oxide_glass",
            "status": "standard", "nd": math.nan, "vd": math.nan,
            "density": math.nan, "cte": math.nan, "tg": math.nan}
    out = []
    for gid, mfr, nd, vd, *rest in rows:
        kw = rest[0] if rest else {}
        row = dict(base)
        row.update({"glass_id": gid, "manufacturer_id": mfr,
                    "glass": kw.get("glass", gid), "manufacturer": mfr,
                    "nd": nd, "vd": vd})
        row.update({k: v for k, v in kw.items() if k in base})
        out.append(row)
    return pd.DataFrame(out)


# N-BK7 / S-BSL7 / H-K9L are the textbook N-BK7-equivalent borosilicate crowns.
NEAR_EQUIVALENT_SET = [
    ("SCHOTT-N-BK7", "SCHOTT", 1.5168, 64.17,
     {"density": 2.51, "cte": 7.1, "tg": 557.0}),
    ("OHARA-S-BSL7", "OHARA", 1.5163, 64.14),
    ("CDGM-H-K9L", "CDGM", 1.5168, 64.20),
    ("SCHOTT-F2", "SCHOTT", 1.6200, 36.4, {"density": 3.24}),  # clearly different
]


def test_near_equivalents_found_across_manufacturers():
    pairs = candidate_pairs(_summary(NEAR_EQUIVALENT_SET))
    found = {frozenset((r["glass_id_a"], r["glass_id_b"])) for _, r in pairs.iterrows()}
    assert frozenset(("SCHOTT-N-BK7", "CDGM-H-K9L")) in found
    assert frozenset(("SCHOTT-N-BK7", "OHARA-S-BSL7")) in found
    assert frozenset(("SCHOTT-N-BK7", "SCHOTT-F2")) not in found  # gate rejects it
    # canonical ordering: the alphabetically smaller id is always side "a"
    for _, r in pairs.iterrows():
        assert r["glass_id_a"] < r["glass_id_b"]


def test_same_manufacturer_pairs_excluded_by_default():
    s = _summary([("A-N-BK7", "SCHOTT", 1.5168, 64.17),
                  ("SCHOTT-BK7", "SCHOTT", 1.5168, 64.17)])
    assert candidate_pairs(s).empty
    loose = EquivalencyCriteria(require_cross_manufacturer=False)
    assert not candidate_pairs(s, loose).empty


def test_material_class_must_match():
    s = _summary([("OX-1", "SCHOTT", 1.5168, 64.17),
                  ("IR-1", "UMICORE", 1.5168, 64.17,
                   {"material_class": "chalcogenide"})])
    assert candidate_pairs(s).empty
    loose = EquivalencyCriteria(require_same_material_class=False)
    assert not candidate_pairs(s, loose).empty


def test_min_shared_props_rejects_sparse_pairs():
    """Two shared gate properties are the minimum; a pair sharing only one
    comparable property is refused."""
    s = _summary([("A-1", "SCHOTT", 1.5168, 64.17, {"density": 2.51}),
                  ("B-1", "OHARA", 1.5169, 64.20)])   # no density -> 2 shared
    assert not candidate_pairs(s).empty
    assert candidate_pairs(s, EquivalencyCriteria(min_shared_props=3)).empty


def test_candidates_without_nd_or_vd_are_skipped():
    s = _summary([("A-1", "SCHOTT", 1.5168, 64.17),
                  ("B-1", "OHARA", math.nan, math.nan),
                  ("C-1", "CDGM", 1.5169, 64.18)])
    ids = set(candidate_pairs(s)["glass_id_a"]) | \
        set(candidate_pairs(s)["glass_id_b"])
    assert "B-1" not in ids


def test_nd_gate_uses_effective_tolerance():
    s = _summary([("A-1", "SCHOTT", 1.5168, 64.17),
                  ("B-1", "OHARA", 1.5300, 64.20)])   # d_nd = 0.0132 > 0.01
    assert candidate_pairs(s).empty
    loose = EquivalencyCriteria(tolerance_overrides={"nd": 0.05, "vd": 5.0})
    assert not candidate_pairs(s, loose).empty


def test_pairs_are_canonically_ordered_and_deduplicated():
    """Input row order must not change the result."""
    s = _summary(NEAR_EQUIVALENT_SET)
    pairs = candidate_pairs(s)
    assert len(pairs) == len(pairs.drop_duplicates(subset=["glass_id_a", "glass_id_b"]))
    for _, r in pairs.iterrows():
        assert r["glass_id_a"] < r["glass_id_b"]
    assert len(candidate_pairs(_summary(list(reversed(NEAR_EQUIVALENT_SET))))) == len(pairs)


def test_deltas_stay_b_minus_a_in_candidates_for():
    s = _summary(NEAR_EQUIVALENT_SET)
    out = candidates_for(s, "SCHOTT-N-BK7")
    assert not out.empty
    row = out.iloc[0]
    assert row["glass_id"] != "SCHOTT-N-BK7"
    ref = s[s["glass_id"] == "SCHOTT-N-BK7"].iloc[0]
    cand = s[s["glass_id"] == row["glass_id"]].iloc[0]
    assert row["d_nd"] == pytest.approx(cand["nd"] - ref["nd"])
    assert row["d_vd"] == pytest.approx(cand["vd"] - ref["vd"])


def test_candidates_for_is_symmetric_but_sign_follows_viewpoint():
    s = _summary(NEAR_EQUIVALENT_SET)
    a = candidates_for(s, "SCHOTT-N-BK7")
    b = candidates_for(s, "CDGM-H-K9L")
    assert "CDGM-H-K9L" in set(a["glass_id"])
    assert "SCHOTT-N-BK7" in set(b["glass_id"])
    m = a[a["glass_id"] == "CDGM-H-K9L"].iloc[0]
    n = b[b["glass_id"] == "SCHOTT-N-BK7"].iloc[0]
    assert m["d_nd"] == pytest.approx(-n["d_nd"])


def test_every_candidate_is_labelled_unverified():
    pairs = candidate_pairs(_summary(NEAR_EQUIVALENT_SET))
    assert (pairs["status"] == "candidate").all()
    assert pairs["verification"].str.contains("unverified").all()
    assert (pairs["source_id"] == "").all()   # no fabricated provenance


def test_curated_pairs_are_tagged_separately():
    eqv = pd.DataFrame([{"glass_id_a": "SCHOTT-N-BK7", "glass_id_b": "OHARA-S-BSL7",
                         "relation": "near-equivalent", "source_id": "OHARA-CAT",
                         "notes": "review melt data"}])
    cur = curated_equivalents(eqv, "SCHOTT-N-BK7")
    assert len(cur) == 1
    assert (cur["status"] == "curated").all()
    assert cur["verification"].str.contains("curated").all()
    assert curated_equivalents(eqv, "NOPE").empty


def test_curated_table_is_never_mutated_by_the_engine():
    eqv = pd.DataFrame([{"glass_id_a": "SCHOTT-N-BK7", "glass_id_b": "CDGM-H-K9L",
                         "relation": "near-equivalent", "source_id": "X"}])
    before = eqv.copy()
    candidate_pairs(_summary(NEAR_EQUIVALENT_SET))
    pd.testing.assert_frame_equal(eqv, before)


def test_cap_keeps_top_partners_and_never_starves_a_glass():
    """The cap is per-glass top-k, so a crowded glass cannot crowd others out -
    and every glass keeps at least one candidate."""
    rows = [("HUB", "SCHOTT", 1.5168, 64.17)]
    rows += [(f"S{i}", f"M{i:02d}", 1.5168 + i * 0.0005, 64.17 + i) for i in range(12)]
    k = 3
    pairs = candidate_pairs(_summary(rows), EquivalencyCriteria(max_per_glass=k))
    edges = [(r["glass_id_a"], r["glass_id_b"], float(r["confidence"])) for _, r in pairs.iterrows()]
    for gid in [r[0] for r in rows]:
        assert any(gid in (a, b) for a, b, _ in edges), f"{gid} starved"

    # Every kept pair must be inside the top-k of at least one endpoint.
    partners: dict = {}
    for a, b, c in edges:
        partners.setdefault(a, []).append((c, b))
        partners.setdefault(b, []).append((c, a))
    rank = {g: {p: i for i, (_, p) in enumerate(sorted(v, key=lambda t: (-t[0], t[1])))}
            for g, v in partners.items()}
    for a, b, _ in edges:
        assert rank[a][b] < k or rank[b][a] < k


def test_result_is_deterministic():
    s = _summary(NEAR_EQUIVALENT_SET)
    pd.testing.assert_frame_equal(candidate_pairs(s), candidate_pairs(s))


def test_empty_and_degenerate_inputs():
    assert candidate_pairs(pd.DataFrame()).empty
    assert candidate_pairs(_summary([("A", "X", 1.5, 60.0)])).empty
    assert equivalence_report(pd.DataFrame())["n_candidate_pairs"] == 0


def test_confidence_decreases_with_distance():
    s = _summary([("A-1", "SCHOTT", 1.5168, 64.17, {"density": 2.51}),
                  ("B-close", "OHARA", 1.5169, 64.20, {"density": 2.52}),
                  ("C-far", "CDGM", 1.5195, 63.00, {"density": 2.60})])
    pairs = candidate_pairs(s)
    conf = {(r["glass_id_a"], r["glass_id_b"]): r["confidence"]
            for _, r in pairs.iterrows()}
    close = [v for k, v in conf.items() if "B-close" in k][0]
    far = [v for k, v in conf.items() if "C-far" in k][0]
    assert close > far


def test_report_counts():
    eqv = pd.DataFrame([{"glass_id_a": "SCHOTT-N-BK7", "glass_id_b": "CDGM-H-K9L",
                         "relation": "near-equivalent", "source_id": "X"}])
    rep = equivalence_report(_summary(NEAR_EQUIVALENT_SET), eqv)
    assert rep["n_curated_pairs"] == 1
    assert rep["n_candidate_pairs"] > 0
    assert "max_dnd" in rep["criteria"]


def test_tolerance_overrides_respected_by_criteria():
    c = EquivalencyCriteria(tolerance_overrides={"density": 0.5})
    assert c.tolerance("density") == 0.5
    assert c.tolerance("nd") == COMPARED_PROPERTIES["nd"][0]
    assert c.as_dict()["max_dvd"] == 3.0



def test_normalize_orientation_flips_both_sides_and_delta_sign():
    df = pd.DataFrame([{
        "glass_id_a": "Z-1", "glass_id_b": "A-1", "glass_a": "Zed", "glass_b": "Ay",
        "manufacturer_a": "ZZ", "manufacturer_b": "AA",
        "nd_a": 1.60, "nd_b": 1.50, "vd_a": 60.0, "vd_b": 64.0,
        "d_nd": -0.10, "d_vd": 4.0, "d_density": math.nan, "d_cte": 1.0,
    }])
    out = _normalize_orientation(df).iloc[0]
    assert out["glass_id_a"] == "A-1" and out["glass_id_b"] == "Z-1"
    assert out["glass_a"] == "Ay" and out["glass_b"] == "Zed"
    assert out["nd_a"] == 1.50 and out["vd_b"] == 60.0
    # deltas stay (b - a): -0.10 becomes +0.10 once the sides swap
    assert out["d_nd"] == pytest.approx(0.10)
    assert out["d_vd"] == pytest.approx(-4.0)
    assert out["d_cte"] == pytest.approx(-1.0)
