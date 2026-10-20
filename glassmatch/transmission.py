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
    """n from the glass's verified dispersion fit, else None.

    `sellmeier_only=True` is deliberate: archived rows (coefficients that do
    not reproduce the catalog n_d / V_d) must never be evaluated as a curve, so
    a glass carrying only those answers "no index" rather than a fabricated
    number. The fit is evaluated in its own formula with every stored term,
    and only inside the range its source states - never extrapolated.
    """
    c = db.sellmeier_for(gid, sellmeier_only=True)
    if c is None:
        return None
    lo, hi = db.dispersion_range(gid, c)
    if lo is not None and hi is not None and not (lo <= wl_um <= hi):
        return None
    from glassmatch.spectra import n_from_row
    try:
        v = n_from_row(c, wl_um)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return v if v == v else None


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
    label = "calculated (Fresnel, uncoated)"
    if len(vals) < len(wls):
        # The fit is not evaluated outside its stated range, so say how much
        # of the band the estimate actually describes.
        label = (f"calculated (Fresnel, uncoated; dispersion fit valid for "
                 f"{len(vals)}/{len(wls)} band samples)")
    return round(float(sum(vals) / len(vals) * 100.0), 1), label


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
    # Manufacturer samples are converted to the same thickness as the n/k
    # branch, so every glass is judged on one path length.
    s = band_stats(t_groups.get(str(gid)), lo_um, hi_um, mode,
                   thickness_mm=thickness_mm)
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
