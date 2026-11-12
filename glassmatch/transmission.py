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
     the assumed blank thickness, which is why that is in the label.  Only
     measured tables: one computed from a dispersion model gives no value.
  3. **Uncoated Fresnel estimate** from verified Sellmeier coefficients, only
     when the glass has no manufacturer rows *and* no tabulated n/k.

Every branch labels itself, so nothing calculated can be mistaken for data.

One basis per question (``basis``): "internal" transmittance - bulk only, what
makers list - or "external", an uncoated blank with the reflection at both
surfaces.  Branches 1 and 2 answer in whichever was asked, so a maker's
internal figure is never ranked against a crystal's uncoated one.
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
    """Mean transmittance of an uncoated, non-absorbing blank of this index
    (reflection at both surfaces only). CALCULATED, labelled."""
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
                      thickness_mm, basis="internal"):
    """(value_pct | None, basis label) for the selected requirement mode.

    Manufacturer transmission.csv rows are preferred. If the glass HAS
    manufacturer rows but they can't satisfy the mode (no samples in band,
    or Entire-range coverage too sparse), the value is reported missing
    rather than silently substituting a calculated estimate. Fresnel is
    only the fallback when the glass has no manufacturer rows at all.

    `basis` picks the one quantity every glass is judged on, so that they
    are comparable: "internal" (the default - bulk absorption only, what
    makers list and an AR-coated part approaches) or "external" (an uncoated
    blank: reflection at both surfaces included). See
    glassmatch.spectra.TRANSMISSION_BASES. Manufacturer samples are internal;
    for "external" the reflection is applied with the index from the
    verified fit, and the result is labelled calculated.

    `db`, `t_groups`, `nk_groups` and `thickness_mm` are passed in rather than
    read from module globals so the chain can be tested on a synthetic
    database; they are exactly the state `app.py` holds.
    """
    # Manufacturer samples are converted to the same thickness as the n/k
    # branch, so every glass is judged on one path length.
    s = band_stats(t_groups.get(str(gid)), lo_um, hi_um, mode,
                   thickness_mm=thickness_mm, basis=basis,
                   n_at=lambda w: n_at(db, gid, w))
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
    nk = band_stats_nk(nk_groups.get(str(gid)), lo_um, hi_um, mode, thickness_mm,
                       basis=basis)
    if nk is not None:
        if nk.get("value_pct") is not None:
            return round(nk["value_pct"], 1), nk["label"]
        return None, f"missing ({nk['label']})"
    # Last resort: the uncoated Fresnel figure counts reflection at the two
    # surfaces and nothing else. It is an upper bound, not a transmittance -
    # it put LiF at 99 % over 9-10 um, where LiF is opaque - so it never
    # meets a requirement: the value is missing and the bound is stated.
    v, note = transmission_estimate(db, gid, lo_um, hi_um)
    if v is None:
        return None, note
    return None, upper_bound_label(v, note)


UPPER_BOUND_PREFIX = "missing (absorption unknown; reflection-only upper bound"


def upper_bound_label(v: float, note: str) -> str:
    """Basis for a glass whose only figure is the Fresnel reflection loss."""
    return f"{UPPER_BOUND_PREFIX} <= {v:g} %, {note})"


def upper_bound(basis) -> float | None:
    """The reflection-only upper bound stated in a basis label, or None."""
    import re
    m = re.search(r"reflection-only upper bound <= ([\d.]+) %", str(basis or ""))
    return float(m.group(1)) if m else None


def band_label(lo_um: float, hi_um: float) -> str:
    """'0.4-0.7 um' / '9-10 um' - the band as the UI and exports name it."""
    return f"{lo_um:g}-{hi_um:g} um"


def combine_bands(per_band: list) -> tuple:
    """Several bands that must ALL be met -> (value_pct | None, basis).

    per_band: [(lo_um, hi_um, value_pct | None, basis), ...]. The combined
    value is the lowest band's value - a glass meets "T >= x in every band"
    exactly when its worst band does - and it is None when any band has no
    value, because the requirement then cannot be shown to hold. The basis
    starts with the limiting band's basis (so "manufacturer ..." /
    "calculated ..." / "missing ..." still classify it) and lists every band.
    """
    if len(per_band) == 1:
        return per_band[0][2], per_band[0][3]
    detail = "; ".join(
        f"{band_label(lo, hi)}: "
        + ("no value" if v is None else f"{v:g} %") + f" ({b})"
        for lo, hi, v, b in per_band)
    missing = [p for p in per_band if p[2] is None]
    if missing:
        lo, hi, _, b = missing[0]
        why = b if str(b).startswith("missing") else f"missing ({b})"
        return None, f"{why} in {band_label(lo, hi)} | all bands: {detail}"
    lo, hi, v, b = min(per_band, key=lambda p: p[2])
    return v, f"{b} | limiting band {band_label(lo, hi)} | all bands: {detail}"


def multi_band_transmission(db, gid, bands, mode, *, t_groups, nk_groups,
                            thickness_mm, basis="internal") -> tuple:
    """band_transmission for every (lo_um, hi_um) in bands, combined with
    combine_bands -> (value_pct | None, basis, per_band)."""
    per = []
    for lo, hi in bands:
        v, b = band_transmission(db, gid, lo, hi, mode, t_groups=t_groups,
                                 nk_groups=nk_groups, thickness_mm=thickness_mm,
                                 basis=basis)
        per.append((float(lo), float(hi), v, b))
    v, b = combine_bands(per)
    return v, b, per
