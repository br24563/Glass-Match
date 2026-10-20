"""Verify a catalog dispersion fit against an independent literature measurement.

The n(d)/V_d gate in the .agf importer cannot judge IR crystals: Zemax writes
n_d = 1.0 as a placeholder for materials that are opaque or uncharacterised
at 587.6 nm (Si, Ge, CdTe, ZnSe ...), so their coefficients would otherwise
stay archived however good they are. For those, GlassMatch compares the fit
with a room-temperature bulk measurement of the same material from
refractiveindex.info, over the wavelengths both cover.

The reference for each material is fixed in advance in REFERENCES - never
chosen by whichever happens to agree - and the tolerance is set by physics:
0.005 is about +/-12 K of germanium's dn/dT, the largest of these materials,
so a pass means "same material at room temperature, transcribed correctly",
which is the claim the label makes.
"""
from __future__ import annotations

import numpy as np

from glassmatch.spectra import n_from_row

TOLERANCE = 0.005
MIN_COVERAGE = 0.5
MIN_SAMPLES = 5
SAMPLES = 40

# catalog glass_id -> refractiveindex.info page (room temperature, bulk).
REFERENCES = {
    "INFRARED-CDTE": "RII-CDTE-DEBELL-300K",
    "INFRARED-GAAS": "RII-GAAS-SKAULI",
    "INFRARED-GERMANIUM": "RII-GE-ICENOGLE",
    "INFRARED-GE_LONG": "RII-GE-ICENOGLE",
    "INFRARED-GE_OLD": "RII-GE-ICENOGLE",
    "INFRARED-SILICON": "RII-SI-CHANDLER-HOROWITZ",
    "INFRARED-ZNSE": "RII-ZNSE-CONNOLLY",
    "INFRARED-ZNS_IR": "RII-ZNS-DEBENHAM",
}


def compare_to_reference(db, glass_id: str, ref_id: str) -> dict | None:
    """Max |n_fit - n_ref| over the overlap of the fit's range and the ref's.

    Returns None when the glass has no dispersion row or no stated range.
    The reference is read through db.n_at, so it answers only where its own
    source has data - nothing is extrapolated on either side.
    """
    row = db.sellmeier_for(glass_id)
    if row is None:
        return None
    lo, hi = db.dispersion_range(glass_id, row)
    if lo is None or hi is None or hi <= lo:
        return None
    pts = []
    for w in np.linspace(lo, hi, SAMPLES):
        ref, _basis = db.n_at(ref_id, w * 1000.0)
        fit = n_from_row(row, w)
        if ref is not None and fit == fit:
            pts.append((float(w), float(fit) - float(ref)))
    if not pts:
        return {"n": 0, "coverage": 0.0, "max_dn": None, "lo": lo, "hi": hi}
    d = np.array([x for _, x in pts])
    return {"n": len(pts), "coverage": (pts[-1][0] - pts[0][0]) / (hi - lo),
            "max_dn": float(np.abs(d).max()), "lo": pts[0][0],
            "hi": pts[-1][0]}


def verdict(cmp: dict | None) -> bool:
    return (cmp is not None and cmp["max_dn"] is not None
            and cmp["n"] >= MIN_SAMPLES and cmp["coverage"] >= MIN_COVERAGE
            and cmp["max_dn"] <= TOLERANCE)
