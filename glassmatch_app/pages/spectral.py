"""Spectral Analysis tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch.plotting import dispersion_figure
from glassmatch.plotting import transmission_figure
from glassmatch.spectra import dispersion_curve
from glassmatch.spectra import fresnel_transmission
from glassmatch.spectra import scale_internal_transmittance
import numpy as np
import pandas as pd
import streamlit as st


def render(ctx):
    db = ctx.db
    results = ctx.results
    sample_thickness_mm = ctx.sample_thickness_mm
    scoped = ctx.scoped
    t_groups = ctx.t_groups
    wl_max_um = ctx.wl_max_um
    wl_min_um = ctx.wl_min_um
    wl_unit = ctx.wl_unit
    st.header("Spectral analysis")
    pool = scoped["glass_id"].tolist() if len(scoped) else results["glass_id"].tolist()
    sel = st.multiselect("Glasses on plot (max 8 for readability)", pool,
                         default=pool[:3], max_selections=8)
    wls = np.linspace(max(wl_min_um, 0.30), min(max(wl_max_um, 0.31), 2.5), 60)
    dcurves, tcurves = {}, {}
    non_sell, t_manufacturer, t_calculated, t_missing = [], [], [], []
    tabulated = []
    for g in sel:
        # --- transmission: manufacturer rows preferred, Fresnel fallback ---
        tdf = t_groups.get(str(g))
        if tdf is not None and len(tdf) >= 2:
            # Converted to the sidebar's sample thickness, like the matching
            # table; samples with no usable listed thickness are left out.
            scaled = scale_internal_transmittance(
                tdf["transmission"], tdf["thickness_mm"], sample_thickness_mm)
            listed = sorted({float(x) for x in tdf["thickness_mm"].dropna()
                             if x > 0})
            listed_s = "/".join(f"{x:g}" for x in listed)
            basis = (f"manufacturer IT, {listed_s} mm as listed"
                     if listed == [float(sample_thickness_mm)] else
                     f"manufacturer IT, scaled from {listed_s} mm to "
                     f"{sample_thickness_mm:g} mm")
            curve = pd.DataFrame({"wavelength_um": tdf["wavelength_um"],
                                  "transmission_pct": scaled * 100.0,
                                  "data_type": basis}).dropna()
            if len(curve):
                tcurves[g] = curve
                t_manufacturer.append(g)
            else:
                t_missing.append(g)
        elif db.dispersion_status(g) == "sellmeier1":
            c = db.sellmeier_for(g, sellmeier_only=True)
            df = dispersion_curve(c, list(wls), *db.dispersion_range(g, c))
            tcurves[g] = pd.DataFrame({"wavelength_um": df["wavelength_um"],
                                       "transmission_pct": df["n"].map(
                                           lambda n: fresnel_transmission(n) * 100),
                                       "data_type": "calculated (Fresnel, uncoated)"})
            t_calculated.append(g)
        else:
            t_missing.append(g)
        # --- dispersion: verified Sellmeier fits, or tabulated crystal n ---
        status = db.dispersion_status(g)
        tab = db.spectral_nk_for(g)
        if tab is not None and len(tab.dropna(subset=["n"])) >= 2:
            # Crystal page with a measured table: plot the source samples
            # themselves rather than a fit, and label them as such.
            npts = tab.dropna(subset=["n"]).copy()
            dcurves[g] = pd.DataFrame({
                "wavelength_um": npts["wavelength_um"], "n": npts["n"]})
            if g in t_missing:
                tcurves[g] = pd.DataFrame({
                    "wavelength_um": npts["wavelength_um"],
                    "transmission_pct": npts["n"].map(
                        lambda n: fresnel_transmission(n) * 100),
                    "data_type": "calculated (Fresnel, uncoated, from tabulated n)"})
                t_calculated.append(g)
                t_missing.remove(g)
            tabulated.append(g)
            continue
        if status != "sellmeier1":
            non_sell.append(g)
            continue
        c = db.sellmeier_for(g, sellmeier_only=True)
        dcurves[g] = dispersion_curve(c, list(wls), *db.dispersion_range(g, c))
    if non_sell:
        st.warning("Dispersion curve unavailable for these glasses - none "
                   "has a dispersion fit verified against the catalog n(d) "
                   "and V_d, so GlassMatch never evaluates one: "
                   + ", ".join(non_sell))
    if t_missing:
        st.info("No transmission data for: " + ", ".join(t_missing))
    if dcurves:
        st.plotly_chart(dispersion_figure(dcurves, "nm" if wl_unit == "nm" else "um"),
                        width="stretch")
        if tabulated:
            st.caption(
                f"Tabulated source measurements: {len(tabulated)} material(s) - "
                "plotted verbatim, no fit. Remaining traces are CALCULATED from "
                "the catalog dispersion formula, not manufacturer tables, and "
                "are not drawn outside the fit's stated wavelength range.")
        else:
            st.caption("CALCULATED from each catalog's dispersion formula "
                       "(Sellmeier, Schott, Extended ...) - not manufacturer "
                       "tables, and not drawn outside the fit's stated "
                       "wavelength range.")
        if tabulated:
            st.info("Tabulated n(λ) samples span a wider range than the glass "
                    "window above; the plot uses each material's own measured "
                    "wavelengths.")
    if tcurves:
        st.plotly_chart(transmission_figure(tcurves, "nm" if wl_unit == "nm" else "um",
                                            band=(wl_min_um, wl_max_um)),
                        width="stretch")
        st.caption(
            f"Manufacturer IT rows: {len(t_manufacturer)} glass(es); "
            f"calculated uncoated Fresnel: {len(t_calculated)} glass(es) — "
            "each trace is labelled by basis. Manufacturer internal "
            f"transmittance is converted to {sample_thickness_mm:g} mm "
            "(Beer-Lambert) from the thickness each catalog lists.")
