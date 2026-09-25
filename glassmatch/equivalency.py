"""Cross-manufacturer equivalency candidates (computational, never auto-merged).

A glass substitution question - "is there an S-BSL7 that does what my N-BK7
does?" - is a real optical-engineering task, but answering it wrongly is
expensive: a wrong substitution invalidates a design.

So this module deliberately draws a hard line:

* It produces **candidates**: pairs of glasses that are numerically close on the
  properties GlassMatch actually has, scored transparently.
* It never **merges** anything. Nothing here writes to the database, nothing
  here asserts that two glasses are interchangeable.
* Every row carries its deltas, the properties actually compared, and a
  ``verification`` string, so a reviewer can check it against melt data and
  manufacturer cross-reference charts.

Curated, human-reviewed pairs in ``data/normalized/equivalents.csv`` are
surfaced alongside and tagged ``curated``, so a computed guess can never
masquerade as a reviewed equivalence.

Default tolerances (n_d +/-0.01, V_d +/-3) describe the range within which a
designer would say "worth checking", not the range within which they would say
"equivalent".
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd

# Properties compared, as (tolerance, weight). Tolerance is the deviation at
# which a property stops contributing to the confidence score; weight is its
# importance relative to the others.
COMPARED_PROPERTIES: dict[str, tuple[float, float]] = {
    "nd": (0.01, 3.0),        # refractive index at 587.6 nm
    "vd": (3.0, 2.0),         # Abbe number
    "density": (0.15, 1.0),   # g/cm3
    "cte": (0.6, 1.0),        # 1e-6 / K
    "tg": (25.0, 0.5),        # degC
}

# nd/vd gate: a pair must be inside these to be considered at all, whatever the
# other properties say. These drive the spatial index, so they are kept in sync
# with COMPARED_PROPERTIES.
GATE_PROPERTIES = ("nd", "vd")

UNVERIFIED = "unverified - computational candidate; check melt data before substitution"

PAIR_COLUMNS = ["glass_id_a", "glass_a", "manufacturer_a", "glass_id_b", "glass_b",
                "manufacturer_b", "confidence", "relation_suggestion", "shared_props",
                "d_nd", "d_vd", "d_density", "d_cte", "nd_a", "nd_b", "vd_a", "vd_b",
                "material_class", "status", "verification", "source_id"]


@dataclass(frozen=True)
class EquivalencyCriteria:
    """User-facing knobs for what counts as a candidate worth reviewing."""

    max_dnd: float = 0.01
    max_dvd: float = 3.0
    max_ddensity: float = 0.15
    max_dcte: float = 0.6
    min_shared_props: int = 2
    require_cross_manufacturer: bool = True
    require_same_material_class: bool = True
    exclude_status: tuple = ("obsolete",)
    min_confidence: float = 0.60
    max_per_glass: int = 5
    tolerance_overrides: dict = field(default_factory=dict)

    def tolerance(self, prop: str) -> float:
        """Effective tolerance for ``prop`` (UI sliders override the default)."""
        if prop in self.tolerance_overrides:
            return float(self.tolerance_overrides[prop])
        return COMPARED_PROPERTIES.get(prop, (0.0, 0.0))[0]

    def as_dict(self) -> dict:
        return {
            "max_dnd": self.max_dnd, "max_dvd": self.max_dvd,
            "max_ddensity": self.max_ddensity, "max_dcte": self.max_dcte,
            "min_shared_props": self.min_shared_props,
            "require_cross_manufacturer": self.require_cross_manufacturer,
            "require_same_material_class": self.require_same_material_class,
        }


def _num(v) -> float:
    """Coerce to float; None / NaN / non-numeric / inf all become NaN."""
    if v is None:
        return math.nan
    try:
        f = float(v)
    except (TypeError, ValueError):
        return math.nan
    return f if math.isfinite(f) else math.nan


def _confidence(deltas: dict[str, float], criteria: EquivalencyCriteria):
    """Weighted closeness over the properties both glasses actually have.

    Returns (confidence 0..1, compared-property count, worst normalized
    deviation). A property missing on either side is skipped and does not
    penalize - but skipping too many is what ``min_shared_props`` guards.
    """
    total_w, acc, worst, shared = 0.0, 0.0, 0.0, 0
    for prop, (_default_tol, w) in COMPARED_PROPERTIES.items():
        tol = criteria.tolerance(prop)
        d = deltas.get(prop)
        if d is None or not math.isfinite(d) or tol <= 0:
            continue
        nd_dev = abs(d) / tol
        worst = max(worst, nd_dev)
        acc += w * max(0.0, 1.0 - nd_dev)
        total_w += w
        shared += 1
    if total_w <= 0:
        return 0.0, 0, math.inf
    return acc / total_w, shared, worst


def _relation_label(conf: float, shared: int) -> str:
    if conf >= 0.97 and shared >= 3:
        return "very close - likely equivalent class"
    if conf >= 0.88:
        return "close - worth checking"
    return "possible - review before use"


def _pair_row(a: dict, b: dict, criteria: EquivalencyCriteria):
    """Build one candidate row, or None if the pair fails a hard gate."""
    if criteria.require_cross_manufacturer and \
            a.get("manufacturer_id") == b.get("manufacturer_id"):
        return None
    if criteria.require_same_material_class and \
            a.get("material_class") != b.get("material_class"):
        return None
    deltas, gate_ok = {}, True
    for prop in COMPARED_PROPERTIES:
        va, vb = _num(a.get(prop)), _num(b.get(prop))
        if math.isfinite(va) and math.isfinite(vb):
            d = vb - va
            deltas[prop] = d
            if prop in GATE_PROPERTIES and abs(d) > criteria.tolerance(prop):
                gate_ok = False
    if not gate_ok:
        return None
    conf, shared, worst = _confidence(deltas, criteria)
    if shared < criteria.min_shared_props:
        return None
    if not math.isfinite(worst) or worst > 1.0:
        return None
    if conf < criteria.min_confidence:
        return None
    return {
        "glass_id_a": a["glass_id"], "glass_a": a.get("glass", a["glass_id"]),
        "manufacturer_a": a.get("manufacturer", ""),
        "glass_id_b": b["glass_id"], "glass_b": b.get("glass", b["glass_id"]),
        "manufacturer_b": b.get("manufacturer", ""),
        "confidence": round(conf, 4),
        "relation_suggestion": _relation_label(conf, shared),
        "shared_props": shared,
        "d_nd": round(deltas.get("nd", math.nan), 6),
        "d_vd": round(deltas.get("vd", math.nan), 4),
        "d_density": round(deltas.get("density", math.nan), 4),
        "d_cte": round(deltas.get("cte", math.nan), 4),
        "nd_a": _num(a.get("nd")), "nd_b": _num(b.get("nd")),
        "vd_a": _num(a.get("vd")), "vd_b": _num(b.get("vd")),
        "material_class": a.get("material_class", ""),
        "status": "candidate",
        "verification": UNVERIFIED,
        "source_id": "",
    }


def _eligible(summary: pd.DataFrame, criteria: EquivalencyCriteria) -> pd.DataFrame:
    """Rows eligible to take part: not excluded by status, nd and vd present."""
    if summary is None or summary.empty:
        return summary
    view = summary
    if criteria.exclude_status and "status" in view.columns:
        view = view[~view["status"].isin(criteria.exclude_status)]
    for prop in GATE_PROPERTIES:
        if prop in view.columns:
            view = view[view[prop].map(_num).map(lambda x: math.isfinite(x))]
    return view


def _neighbor_pairs(view: pd.DataFrame, criteria: EquivalencyCriteria):
    """Yield (i, j) index pairs passing the nd/vd gate.

    A k-d tree on gate-scaled coordinates keeps the search local as the catalog
    grows; the numpy fallback is exact too, just O(n^2). Both apply the same
    gate, so results do not depend on scipy being installed.
    """
    n = len(view)
    if n < 2:
        return []
    xs = view["nd"].map(_num).to_numpy(dtype=float) / max(criteria.tolerance("nd"), 1e-12)
    ys = view["vd"].map(_num).to_numpy(dtype=float) / max(criteria.tolerance("vd"), 1e-12)
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(np.column_stack([xs, ys]))
        pairs = []
        for i, neigh in enumerate(tree.query_ball_point(np.column_stack([xs, ys]), r=1.0)):
            pairs.extend((i, j) for j in neigh if j > i)
        return pairs
    except ImportError:  # pragma: no cover - scipy is a hard dependency
        pairs = []
        for i in range(n):
            gate = (np.abs(xs[i + 1:] - xs[i]) <= 1.0) & (np.abs(ys[i + 1:] - ys[i]) <= 1.0)
            pairs.extend((i, j) for j in np.nonzero(gate)[0] + i + 1)
        return pairs


_SWAP_PAIRS = [("glass_id_a", "glass_id_b"), ("glass_a", "glass_b"),
               ("manufacturer_a", "manufacturer_b"),
               ("nd_a", "nd_b"), ("vd_a", "vd_b")]


def _normalize_orientation(df: pd.DataFrame) -> pd.DataFrame:
    """Put every pair in canonical (smaller glass_id first) order.

    De-duplicating a symmetric pair requires *normalizing* which side is "a",
    not filtering on it. Filtering on ``glass_id_a < glass_id_b`` silently
    discards every pair whose row order disagrees with alphabetical order -
    which depends on catalog ordering, not on the data.
    """
    if df.empty:
        return df
    out = df.copy()
    flip = (out["glass_id_a"].astype(str) > out["glass_id_b"].astype(str)).to_numpy()
    for col_a, col_b in _SWAP_PAIRS:
        if col_a in out.columns and col_b in out.columns:
            keep = out[col_a].to_numpy(copy=True)
            out[col_a] = out[col_b].to_numpy()
            out[col_b] = keep
    # Deltas flip sign with the swap so they stay (b - a).
    for col in ("d_nd", "d_vd", "d_density", "d_cte"):
        if col in out.columns:
            vals = pd.to_numeric(out[col], errors="coerce").to_numpy(dtype=float,
                                                                     copy=True)
            vals[flip] = -vals[flip]
            out[col] = vals
    return out


def _cap_per_glass(df: pd.DataFrame, max_per_glass: int) -> pd.DataFrame:
    """Limit each glass to its ``max_per_glass`` best partners, rank-based.

    Counting slots while walking a globally sorted list is order-dependent: a
    popular glass (N-BK7 has dozens of near-identical counterparts) consumes
    every slot before quieter glasses are reached, and can end up with none at
    all. Ranking each glass's own partners instead makes the cap independent of
    iteration order.

    Each glass's single best partner is kept unconditionally, so a glass always
    shows at least one substitution candidate when one exists.
    """
    if df.empty or not max_per_glass or max_per_glass <= 0:
        return df
    partners: dict = {}
    for _, r in df.iterrows():
        a, b = r["glass_id_a"], r["glass_id_b"]
        partners.setdefault(a, []).append((float(r["confidence"]), b))
        partners.setdefault(b, []).append((float(r["confidence"]), a))
    # Rank each glass's partners: best first, ties broken by glass_id so the
    # result is deterministic across runs.
    rank = {g: {p: i for i, (_, p) in
                enumerate(sorted(v, key=lambda t: (-t[0], t[1])))}
            for g, v in partners.items()}
    best_partner = {g: min(v, key=lambda t: (-t[0], t[1]))[1] for g, v in partners.items()}

    keep = []
    for _, r in df.iterrows():
        a, b = r["glass_id_a"], r["glass_id_b"]
        seeded = best_partner.get(a) == b or best_partner.get(b) == a
        ranked = (rank.get(a, {}).get(b, 10 ** 6) < max_per_glass or
                  rank.get(b, {}).get(a, 10 ** 6) < max_per_glass)
        if seeded or ranked:
            keep.append(r)
    return pd.DataFrame(keep) if keep else df.iloc[0:0]


def candidate_pairs(summary: pd.DataFrame,
                    criteria: EquivalencyCriteria | None = None) -> pd.DataFrame:
    """All cross-maker candidate pairs in ``summary``, best first.

    ``summary`` is :meth:`GlassDatabase.summary_frame`. Each unordered pair
    appears once, ordered by confidence, then capped per glass.
    """
    crit = criteria or EquivalencyCriteria()
    view = _eligible(summary, crit)
    if view is None or view.empty or "nd" not in view.columns:
        return pd.DataFrame(columns=PAIR_COLUMNS)
    records = view.to_dict("records")
    rows = [row for row in
            (_pair_row(records[i], records[j], crit)
             for i, j in _neighbor_pairs(view, crit))
            if row is not None]
    if not rows:
        return pd.DataFrame(columns=PAIR_COLUMNS)
    df = pd.DataFrame(rows)
    df = _normalize_orientation(df)  # canonical (min_id, max_id) ordering
    df = df.drop_duplicates(subset=["glass_id_a", "glass_id_b"])  # symmetric de-dup
    if df.empty:
        return pd.DataFrame(columns=PAIR_COLUMNS)
    df = df.sort_values(["confidence", "shared_props"], ascending=False)
    df = _cap_per_glass(df, crit.max_per_glass)
    return df[PAIR_COLUMNS].reset_index(drop=True)


def candidates_for(summary: pd.DataFrame, glass_id: str,
                   criteria: EquivalencyCriteria | None = None,
                   max_results: int = 5) -> pd.DataFrame:
    """Candidate substitutions for one glass, from that glass's point of view
    (deltas keep their sign: candidate minus the glass of interest)."""
    crit = criteria or EquivalencyCriteria()
    pairs = candidate_pairs(summary, crit)
    if pairs.empty:
        return pd.DataFrame()
    hit = pairs[(pairs["glass_id_a"] == glass_id) | (pairs["glass_id_b"] == glass_id)]
    rows = []
    for _, r in hit.iterrows():
        forward = r["glass_id_a"] == glass_id
        other = r["glass_id_b"] if forward else r["glass_id_a"]
        rows.append({
            "glass_id": other,
            "glass": r["glass_b"] if forward else r["glass_a"],
            "manufacturer": r["manufacturer_b"] if forward else r["manufacturer_a"],
            "confidence": r["confidence"],
            "relation_suggestion": r["relation_suggestion"],
            "shared_props": r["shared_props"],
            "d_nd": r["d_nd"] if forward else -r["d_nd"],
            "d_vd": r["d_vd"] if forward else -r["d_vd"],
            "d_density": r["d_density"] if forward else -r["d_density"],
            "d_cte": r["d_cte"] if forward else -r["d_cte"],
            "status": "candidate",
            "verification": UNVERIFIED,
        })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("confidence", ascending=False)
    return out.head(max_results).reset_index(drop=True)


def curated_equivalents(equivalents: pd.DataFrame, glass_id: str) -> pd.DataFrame:
    """Human-reviewed pairs for one glass, tagged so they outrank candidates."""
    if equivalents is None or equivalents.empty:
        return pd.DataFrame()
    hit = equivalents[(equivalents["glass_id_a"] == glass_id) |
                      (equivalents["glass_id_b"] == glass_id)].copy()
    if hit.empty:
        return hit
    hit["status"] = "curated"
    hit["verification"] = "curated - manufacturer cross-reference or maintainer review"
    return hit


def equivalence_report(summary: pd.DataFrame, equivalents: pd.DataFrame | None = None,
                       criteria: EquivalencyCriteria | None = None) -> dict:
    """Candidate table plus the counts the UI shows above it."""
    pairs = candidate_pairs(summary, criteria)
    curated = 0 if equivalents is None or equivalents.empty else len(equivalents)
    return {
        "pairs": pairs,
        "n_candidate_pairs": len(pairs),
        "n_curated_pairs": curated,
        "n_glasses_with_candidates": int(pairs["glass_id_a"].nunique()) if not pairs.empty else 0,
        "criteria": (criteria or EquivalencyCriteria()).as_dict(),
    }
