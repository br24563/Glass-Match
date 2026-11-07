"""Compare section of the Search & Compare tab: 2-5 glasses side by side,
taken from whichever list (ranked matches or the whole database) is shown."""
from __future__ import annotations

import streamlit as st


def render(ctx, pool, key: str = "ranked"):
    st.subheader("Compare (2-5 glasses)")
    ids = pool["glass_id"].tolist()
    comp = st.multiselect("Glasses to compare", ids, default=ids[:2],
                          max_selections=5, key=f"cmp_{key}",
                          help="Chosen from the list above; change the list's "
                               "filters to compare other glasses.")
    if len(comp) >= 2:
        st.dataframe(pool[pool["glass_id"].isin(comp)].set_index("glass_id")
                     .astype(str).T, width="stretch")
        ctx.agf_download(comp, f"compare_{key}")
    else:
        st.info("Select at least 2 glasses.")
