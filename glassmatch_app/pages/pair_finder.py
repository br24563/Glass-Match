"""Pair Finder tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch import pairs as gpairs
from glassmatch.plotting import partial_dispersion_figure
import streamlit as st


def render(ctx):
    gtable = ctx.gtable
    require_data = ctx.require_data
    results = ctx.results
    sample_thickness_mm = ctx.sample_thickness_mm
    t_min = ctx.t_min
    t_mode = ctx.t_mode
    trans = ctx.trans
    wl_max = ctx.wl_max
    wl_min = ctx.wl_min
    wl_unit = ctx.wl_unit
    st.header("Pair finder (achromatic doublet)")
    st.caption("Thin lenses in contact, total power φ: "
               "φ1 = φ·V1/(V1−V2), φ2 = −φ·V2/(V1−V2); "
               "secondary spectrum ∝ (P1−P2)/(V1−V2); thermo-optic "
               "coefficient γ = (dn/dT)/(n_d−1) − α. Every number here "
               "is **calculated** - a starting point for design, never a manufacturer "
               "recommendation.")
    pf_rank = st.radio("Rank by", ["Low element powers", "Low secondary spectrum",
                                   "Apochromat candidates", "Athermal (mount CTE)"],
                       horizontal=True, key="pf_rank")
    pf_key = {"Low element powers": "power", "Low secondary spectrum": "secondary",
              "Apochromat candidates": "apo", "Athermal (mount CTE)": "athermal"}[pf_rank]
    pc1, pc2, pc3, pc4 = st.columns(4)
    pf_f = pc1.number_input("Doublet focal length (mm)", 1.0, 100000.0, 100.0, 10.0,
                            key="pf_f")
    pf_min_dv = pc2.number_input("Min V1 − V2", 1.0, 80.0, 10.0, 1.0, key="pf_min_dv",
                                 help="Pairs closer in V_d need very strong elements.")
    pf_mount = pc3.number_input("Mount CTE (1e-6/K)", -5.0, 60.0, 23.6, 0.1,
                                key="pf_mount", help="23.6 aluminium, 17.3 stainless "
                                                     "303, 8.6 titanium, 1.2 Invar.",
                                disabled=pf_key != "athermal")
    pf_top = pc4.number_input("Pairs shown", 10, 2000, 200, 10, key="pf_top")
    if pf_key == "apo":
        ac1, ac2 = st.columns(2)
        pf_apo_dp = ac1.number_input("Max |P1 − P2|", 0.0001, 0.05, 0.003, 0.0005,
                                     format="%.4f", key="pf_apo_dp")
        pf_apo_dv = ac2.number_input("Min V1 − V2 for apochromats", 1.0, 80.0, 20.0,
                                     1.0, key="pf_apo_dv")
    else:
        pf_apo_dp, pf_apo_dv = 0.003, 20.0
    with st.expander("Which glasses are paired", expanded=False):
        fc1, fc2 = st.columns(2)
        pf_makers = fc1.multiselect("Makers", sorted(gtable["manufacturer"].unique()),
                                    default=sorted(gtable["manufacturer"].unique()),
                                    key="pf_makers")
        _classes = sorted(gtable["material_class"].unique())
        pf_classes = fc2.multiselect("Material classes", _classes,
                                     default=[c for c in _classes
                                              if c in ("oxide_glass", "moldable")]
                                     or _classes, key="pf_classes")
        pf_obsolete = st.checkbox("Include obsolete glasses", value=False,
                                  key="pf_obsolete")
        pf_trans = st.checkbox(
            f"Only glasses meeting the sidebar transmission requirement "
            f"({t_min:g}% {t_mode.lower()}, {wl_min:g}-{wl_max:g} {wl_unit}, "
            f"{sample_thickness_mm:g} mm)", value=False, key="pf_trans",
            help="Glasses with no transmission data are kept unless 'Require "
                 "available data' is on.")
        pf_min_score = st.slider("Minimum compatibility score (sidebar requirements)",
                                 0.0, 100.0, 0.0, 1.0, key="pf_min_score",
                                 help="0 pairs every glass; raise it to pair only "
                                      "glasses that fit the sidebar's n_d, V_d, "
                                      "density, CTE and dn/dT requirements.")
    # The pool starts from the match results, so the sidebar's hard filters
    # (|dn/dT| limit, "Require available data") already apply.
    pf_ok = results[results["compatibility"] >= pf_min_score]["glass_id"]
    pool_t = gtable[gtable["glass_id"].isin(set(pf_ok))
                    & gtable["manufacturer"].isin(pf_makers)
                    & gtable["material_class"].isin(pf_classes)]
    if not pf_obsolete:
        pool_t = pool_t[pool_t["status"] != "obsolete"]
    if pf_trans:
        def _t_ok(g):
            v = trans.get(g)
            return (not require_data) if v is None else v >= t_min
        pool_t = pool_t[pool_t["glass_id"].map(_t_ok)]
    pairs_df = gpairs.find_pairs(pool_t, sort_by=pf_key, top=int(pf_top),
                                 min_dv=pf_min_dv,
                                 mount_cte=pf_mount if pf_key == "athermal" else None,
                                 apo_dp_max=pf_apo_dp, apo_min_dv=pf_apo_dv)
    st.caption(f"{len(pool_t):,} glasses in the pool → "
               f"{pairs_df.attrs.get('n_pairs', 0):,} pairs with V1 − V2 ≥ "
               f"{pf_min_dv:g}; {pairs_df.attrs.get('n_ranked', 0):,} have the data "
               f"this ranking needs. Showing the top {len(pairs_df):,}.")
    if pairs_df.empty:
        st.info("No pairs for these settings - widen the filters.")
    else:
        pv = pairs_df.copy()
        pv["f1_mm"] = pf_f / pv["phi1"]
        pv["f2_mm"] = pf_f / pv["phi2"]
        pv_cols = ["crown", "crown_maker", "flint", "flint_maker", "V1", "V2",
                   "phi1", "phi2", "f1_mm", "f2_mm", "sum_abs_power",
                   "P1", "P2", "dP", "secondary_spectrum"]
        if pf_key == "athermal":
            pv_cols += ["gamma1", "gamma2", "focal_drift", "thermal_residual"]
        st.dataframe(pv[pv_cols].round(5), width="stretch", hide_index=True)
        st.caption(
            "φ1, φ2 in units of the total power; f1, f2 = element focal "
            "lengths for the focal length above. P = P_g,F calculated from the "
            "verified fit; secondary_spectrum ≈ g-F focal shift / f. "
            + ("γ in 1e-6/K from absolute dn/dT (d line, +20/+40 C; "
               "manufacturer or calculated from TD coefficients) and catalog CTE; "
               "focal_drift = (1/f)·df/dT, thermal_residual = focal_drift "
               "− mount CTE (0 = athermal). " if pf_key == "athermal" else "")
            + "Basis: " + gpairs.PAIR_BASIS + ".")
        st.download_button("Export pairs CSV", pv.to_csv(index=False).encode(),
                           "glassmatch_pairs.csv", "text/csv", key="dl_pairs")
        pick = st.selectbox(
            "Show a pair on the partial-dispersion diagram", range(len(pv)),
            format_func=lambda k: f"{pv['crown'].iloc[k]} ({pv['crown_maker'].iloc[k]})"
                                  f" + {pv['flint'].iloc[k]} ({pv['flint_maker'].iloc[k]})",
            key="pf_pick")
        st.plotly_chart(partial_dispersion_figure(
            pool_t, pair=(pv["crown_id"].iloc[pick], pv["flint_id"].iloc[pick]),
            height=520), width="stretch")
