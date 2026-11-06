"""Database Explorer tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(ctx):
    _COL_LABELS = ctx._COL_LABELS
    _candidate_pairs = ctx._candidate_pairs
    _data_key = ctx._data_key
    col_table = ctx.col_table
    db = ctx.db
    prop_wavelength_nm = ctx.prop_wavelength_nm
    sample_thickness_mm = ctx.sample_thickness_mm
    summary = ctx.summary
    st.header("Database explorer")
    mf = st.selectbox("Manufacturer", ["(all)"] + sorted(summary["manufacturer"].unique()))
    fam = st.selectbox("Family", ["(all)"] + sorted(summary["family"].unique()))
    mcls = st.selectbox("Material class", ["(all)"] + sorted(summary["material_class"].unique()))
    only_sell = st.checkbox("Only glasses with dispersion data")
    hide_obsolete = st.checkbox("Hide obsolete glasses", value=True)
    view = summary.copy()
    if mf != "(all)":
        view = view[view["manufacturer"] == mf]
    if fam != "(all)":
        view = view[view["family"] == fam]
    if mcls != "(all)":
        view = view[view["material_class"] == mcls]
    if only_sell:
        view = view[view["has_sellmeier"]]
    if hide_obsolete and "status" in view.columns:
        view = view[view["status"] != "obsolete"]
    if not ctx.include_mirrors and "data_tier" in view.columns:
        view = view[view["data_tier"] != "unverified_mirror"]
    _derived = [c for c in col_table.columns if c not in view.columns]
    view = view.join(col_table[_derived], on="glass_id")
    st.dataframe(view, width="stretch", hide_index=True)
    st.caption(f"{len(view)} of {len(summary)} glasses shown - click any column "
               "header to sort. Transmission figures are at the sidebar's sample "
               f"thickness ({sample_thickness_mm:g} mm); n, dn/dλ, group "
               f"index and GVD at {prop_wavelength_nm:g} nm.")
    with st.expander("What each column means"):
        st.dataframe(pd.DataFrame(
            [{"column": c, "meaning": lab, "unit": unit}
             for c, (lab, unit) in _COL_LABELS.items()]),
            width="stretch", hide_index=True)
    if not db.nonlinear_n2.empty:
        st.subheader("Nonlinear refractive index n2 (crystals, literature)")
        st.caption("One row per published measurement, verbatim, with its "
                   "wavelength, pulse duration and method - n2 depends on "
                   "both, so measurements are never averaged. Sort by n2 to "
                   "compare window materials for high-power lasers. Source: "
                   "refractiveindex.info (CC0); each row cites its paper.")
        _n2 = db.nonlinear_n2.copy()
        _n2["n2 (1e-20 m²/W)"] = _n2["n2_m2_per_w"] * 1e20
        st.dataframe(_n2[["material_name", "wavelength_um", "n2 (1e-20 m²/W)",
                          "pulse_duration_s", "method", "comments",
                          "source_id"]],
                     width="stretch", hide_index=True)
    cov = summary.groupby("manufacturer_id").agg(
        glasses=("glass_id", "count"),
        with_sellmeier=("has_sellmeier", "sum")).reset_index()
    st.subheader("Catalog coverage")
    st.dataframe(cov, width="stretch", hide_index=True)

    st.subheader("Equivalency candidates (substitution finder)")
    st.caption("Finds glasses from other manufacturers that are numerically close on "
               "n_d, V_d, density, CTE and T_g. These are **candidates for review**, "
               "not manufacturer-stated equivalences - nothing is merged, and every "
               "row shows the deltas that produced it.")
    c1, c2, c3 = st.columns(3)
    tol_nd = c1.slider("Max |Δn_d|", 0.001, 0.05, 0.01, 0.001,
                       help="Refractive-index tolerance at 587.6 nm. 0.01 is a typical "
                            "'worth checking' bound; tighter finds closer matches.")
    tol_vd = c2.slider("Max |ΔV_d|", 0.5, 15.0, 3.0, 0.5,
                       help="Abbe-number tolerance. Larger values pull in glasses with "
                            "somewhat different dispersion.")
    tol_rho = c3.slider("Max |Δdensity| (g/cm³)", 0.05, 1.0, 0.15, 0.05,
                        help="Only applies where both catalogs report density.")
    with st.spinner("Computing candidates..."):
        pairs = _candidate_pairs(_data_key(), float(tol_nd), float(tol_vd),
                                 float(tol_rho))
    m1, m2, m3 = st.columns(3)
    m1.metric("Candidate pairs", f"{len(pairs):,}")
    m2.metric("Curated pairs", f"{len(db.equivalents):,}")
    m3.metric("Glasses covered",
              f"{pairs[['glass_id_a', 'glass_id_b']].stack().nunique():,}" if not pairs.empty else "0")
    if not pairs.empty:
        only_curated = st.checkbox("Show only pairs already curated in equivalents.csv")
        view_pairs = pairs
        if only_curated and not db.equivalents.empty:
            known = {frozenset((r["glass_id_a"], r["glass_id_b"]))
                     for _, r in db.equivalents.iterrows()}
            view_pairs = pairs[pairs.apply(
                lambda r: frozenset((r["glass_id_a"], r["glass_id_b"])) in known,
                axis=1)]
        st.dataframe(view_pairs[["glass_a", "manufacturer_a", "glass_b", "manufacturer_b",
                                "confidence", "shared_props", "d_nd", "d_vd",
                                "d_density", "d_cte", "relation_suggestion"]]
                     .head(500), width="stretch", hide_index=True)
        st.download_button("Download candidate pairs (CSV)", pairs.to_csv(index=False),
                           file_name="equivalency_candidates.csv", mime="text/csv",
                           key="dl_equiv_pairs")
    if not db.equivalents.empty:
        with st.expander("Curated equivalencies (reviewed, source-backed)"):
            st.dataframe(db.equivalents, width="stretch", hide_index=True)
            st.caption("Reviewed pairs carry a source_id. Add manufacturer "
                       "cross-reference charts via PR - see CONTRIBUTING.md.")
