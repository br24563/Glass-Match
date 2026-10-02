"""Transmission value + basis for one material over one band.

This is the decision chain the matching table, the detail tab and the CSV
export all share, so it lives in the package where it can be tested without
Streamlit.  `app.py` only passes its groups and the user's assumptions in.

Precedence, highest first:

  1. **Manufacturer rows** (``transmission.csv``).  If the glass has them but
     they cannot answer the requested mode — no samples inside the band, or
     "Entire range" without the coverage to back the claim — the answer is
     *missing*.  It is never quietly replaced by a calculated estimate, because
     the user asked about measured internal transmittance and a Fresnel number
     is a different claim.
  2. **Calculated from tabulated n/k** for crystals and semiconductors, which
     publish optical constants rather than a transmittance curve.  Depends on
     the assumed blank thickness, which is why that is in the label.
  3. **Uncoated Fresnel estimate** from verified Sellmeier coefficients, only
     when the glass has no manufacturer rows *and* no tabulated n/k.

Every branch labels itself, so nothing calculated can be mistaken for data.
"""

from __future__ import annotations

import numpy as np

from glassmatch.spectra import band_stats, band_stats_nk, fresnel_transmission


def n_at(db, gid, wl_um):
    """n from the glass's verified Sellmeier coefficients, else None.

    `sellmeier_only=True` is deliberate: archived non-Sellmeier rows (NIKON
    polynomials, series forms) must never be evaluated as a curve, so a glass
    carrying only those answers "no index" rather than a fabricated number.
    """
    c = db.sellmeier_for(gid, sellmeier_only=True)
    if c is None:
        return None
    from glassmatch.spectra import sellmeier_n
    try:
        return sellmeier_n(wl_um, (float(c["B1"]), float(c["B2"]), float(c["B3"])),
                           (float(c["C1_um2"]), float(c["C2_um2"]), float(c["C3_um2"])))
    except (TypeError, ValueError):
        return None


def transmission_estimate(db, gid, wl_lo_um, wl_hi_um, n=12):
    """Mean uncoated Fresnel transmittance. CALCULATED, labelled."""
    c = db.sellmeier_for(gid)
    if c is None:
        return None, "missing (no Sellmeier data)"
    wls = np.linspace(wl_lo_um, wl_hi_um, n)
    vals = [fresnel_transmission(n_at(db, gid, w)) for w in wls]
    vals = [v for v in vals if v == v]
    if not vals:
        return None, "missing"
    return round(float(sum(vals) / len(vals) * 100.0), 1), "calculated (Fresnel, uncoated)"


def band_transmission(db, gid, lo_um, hi_um, mode, *, t_groups, nk_groups,
                      thickness_mm):
    """(value_pct | None, basis label) for the selected requirement mode.

    Manufacturer transmission.csv rows are preferred. If the glass HAS
    manufacturer rows but they can't satisfy the mode (no samples in band,
    or Entire-range coverage too sparse), the value is reported missing
    rather than silently substituting a calculated estimate. Fresnel is
    only the fallback when the glass has no manufacturer rows at all.

    `db`, `t_groups`, `nk_groups` and `thickness_mm` are passed in rather than
    read from module globals so the chain can be tested on a synthetic
    database; they are exactly the state `app.py` holds.
    """
    s = band_stats(t_groups.get(str(gid)), lo_um, hi_um, mode)
    if s is not None:
        if s.get("value_pct") is not None:
            # Round here so every consumer (table, caption, export) shows the
            # same number; a raw mean of binary floats prints as e.g.
            # 98.49999999999999%.
            return round(s["value_pct"], 1), s["label"]
        return None, f"missing ({s['label']})"
    # Crystals and semiconductors publish measured n and k rather than a
    # manufacturer transmittance curve, which left 195 materials unsearchable.
    # Derive it from the optical constants instead - clearly labelled, and only
    # from bulk measurements.
    nk = band_stats_nk(nk_groups.get(str(gid)), lo_um, hi_um, mode, thickness_mm)
    if nk is not None:
        if nk.get("value_pct") is not None:
            return round(nk["value_pct"], 1), nk["label"]
        return None, f"missing ({nk['label']})"
    v, note = transmission_estimate(db, gid, lo_um, hi_um)
    return v, note
