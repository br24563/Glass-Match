"""Comparison tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

import streamlit as st


def render(ctx):
    agf_download = ctx.agf_download
    results = ctx.results
    st.header("Comparison (2-5 glasses)")
    comp = st.multiselect("Select glasses", results["glass_id"].tolist(),
                          default=results["glass_id"].tolist()[:2], max_selections=5)
    if len(comp) >= 2:
        st.dataframe(results[results["glass_id"].isin(comp)].set_index("glass_id")
                     .astype(str).T, width="stretch")
        agf_download(comp, "compare")
    else:
        st.info("Select at least 2 glasses.")
