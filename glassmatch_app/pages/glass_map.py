"""Glass Map tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch import pairs as gpairs
from glassmatch.plotting import glass_map_figure
from glassmatch.plotting import partial_dispersion_figure
import streamlit as st


def render(ctx):
    gtable = ctx.gtable
    scoped = ctx.scoped
    st.header("Glass map")
    st.caption("n_d and V_d are catalog (manufacturer) values. P_g,F is not stored: "
               "it is **calculated** from each glass's verified dispersion fit "
               "(n_g, n_F, n_C), only where the fit's stated range covers 435.8-656.3 nm.")
    gm1, gm2, gm3 = st.columns([2, 1, 1])
    gm_makers = gm1.multiselect("Makers", sorted(gtable["manufacturer"].unique()),
                                default=sorted(gtable["manufacturer"].unique()),
                                key="gm_makers")
    gm_obsolete = gm2.checkbox("Show obsolete glasses", value=False, key="gm_obsolete")
    gm_top = gm3.number_input("Highlight top N match results", 0, 500, 25, 5,
                              key="gm_top",
                              help="The highest-scoring glasses of the Matching "
                                   "Glasses tab (manufacturers in scope there).")
    gm_view = gtable[gtable["manufacturer"].isin(gm_makers)]
    if not gm_obsolete:
        gm_view = gm_view[gm_view["status"] != "obsolete"]
    gm_highlight = scoped["glass_id"].head(int(gm_top)).tolist()
    gm_kind = st.radio("View", ["n_d vs V_d (Abbe diagram)",
                                "P_g,F vs V_d (partial dispersion)"],
                       horizontal=True, key="gm_kind")
    if gm_kind.startswith("n_d"):
        st.plotly_chart(glass_map_figure(gm_view, gm_highlight), width="stretch")
        st.caption(f"{int(gm_view[['nd', 'vd']].notna().all(axis=1).sum()):,} glasses "
                   "plotted. Crystals and IR materials have no catalog n_d/V_d and "
                   "do not appear.")
    else:
        st.plotly_chart(partial_dispersion_figure(gm_view, gm_highlight),
                        width="stretch")
        st.caption(
            f"{int(gm_view['pgf'].notna().sum()):,} glasses plotted. dPgF on hover is "
            f"P_g,F minus the {gpairs.NORMAL_LINE_LABEL} (calculated); the "
            "manufacturer's own dPgF, measured against that maker's normal line, "
            "is shown beside it where stored. Glasses far from the line have "
            "anomalous partial dispersion - the ones that reduce secondary spectrum.")
