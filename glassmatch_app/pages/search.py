"""Search & Compare tab: ranked matches or the whole database, and a
comparison of glasses from whichever list is shown. Replaces the separate
Matching Glasses, Database Explorer and Comparison tabs."""
from __future__ import annotations

import streamlit as st

from glassmatch_app.pages import comparison, explorer, matching


def render(ctx) -> dict:
    st.header("Search & compare")
    view = st.radio(
        "Show", ["Ranked matches", "Browse the whole database"], horizontal=True,
        key="sc_view",
        help="Ranked matches: every material scored against the sidebar "
             "requirements. Browse: the whole database, every column sortable, "
             "with simple filters - nothing is scored.")
    if view == "Ranked matches":
        out = matching.render(ctx)
        st.divider()
        comparison.render(ctx, out["scoped"], "ranked")
        return out
    pool = explorer.render(ctx)
    st.divider()
    comparison.render(ctx, pool, "browse")
    st.divider()
    explorer.render_extras(ctx)
    # The other tabs highlight "the current results": all of them here.
    return {"scoped": ctx.results}
