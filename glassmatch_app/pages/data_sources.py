"""Data Sources tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch import __version__
import pandas as pd
import streamlit as st


def render(ctx):
    DATA_VERSION = ctx.DATA_VERSION
    db = ctx.db
    quality = ctx.quality
    st.header("Data sources and licensing")
    st.markdown(
        f"**Data version {DATA_VERSION}** (GlassMatch {__version__}). Every "
        "file is pinned by SHA-256 in `data/normalized/MANIFEST.json`, so this "
        "version identifies exactly one set of numbers - cite it with a design. "
        "How the data is checked: [docs/VALIDATION.md](https://github.com/"
        "br24563/Glass-Match/blob/main/docs/VALIDATION.md).")
    st.dataframe(db.sources, width="stretch", hide_index=True)
    st.warning("Glass nd/Vd and dispersion coefficients are parsed from each "
               "maker's Zemax .agf catalog (SCHOTT and OHARA direct; the rest "
               "via a third-party mirror of unknown vintage). Re-verify against "
               "the current manufacturer datasheet before detailed design. "
               "Crystal pages come from refractiveindex.info (CC0).")
    st.subheader("Data quality report")
    n_prop, n_glass = len(quality["properties"]), len(quality["glasses"])
    n_trans, n_orph = len(quality["transmission"]), len(quality["orphan_sources"])
    n_orph_g, n_nk = len(quality["orphan_glasses"]), len(quality["spectral_nk"])
    q1, q2, q3, q4, q5, q6 = st.columns(6)
    q1.metric("Property flags", n_prop)
    q2.metric("Glass flags", n_glass)
    q3.metric("Transmission flags", n_trans)
    q4.metric("Spectral n/k flags", n_nk)
    q5.metric("Orphan source refs", n_orph)
    q6.metric("Orphan glass refs", n_orph_g)
    total = n_prop + n_glass + n_trans + n_nk + n_orph + n_orph_g
    if total == 0:
        st.success("All checks pass — no flagged records. Nothing is auto-fixed; "
                   "flags here would list questionable records for review.")
    else:
        st.caption("Flagged records are listed, never silently corrected. "
                   "Review before relying on them.")
        for title, key in [("Properties", "properties"), ("Glasses", "glasses"),
                           ("Transmission samples", "transmission"),
                           ("Spectral n/k samples", "spectral_nk")]:
            if quality[key]:
                with st.expander(f"{title}: {len(quality[key])} flagged record(s)"):
                    st.dataframe(pd.DataFrame(quality[key]), width="stretch", hide_index=True)
        if quality["orphan_sources"]:
            st.warning("source_ids referenced by data but missing from sources.csv: "
                       + ", ".join(quality["orphan_sources"]))
        if quality["orphan_glasses"]:
            st.warning("glass_ids carrying properties but missing from glasses.csv "
                       "(these rows are invisible in the UI): "
                       + ", ".join(quality["orphan_glasses"][:20])
                       + (" ..." if len(quality["orphan_glasses"]) > 20 else ""))

    st.subheader("Quarantined transmission samples")
    n_conf = len(quality["transmission_conflicts"])
    st.metric("Quarantined conflicting samples", f"{n_conf:,}")
    if n_conf:
        st.caption("Where one wavelength carried two different values in a source "
                   "catalog, every row was moved out of the database into "
                   "`data/normalized/transmission_conflicts.csv` with both values "
                   "intact. GlassMatch never picks a winner: these samples are "
                   "excluded from band statistics until a maintainer checks the "
                   "source catalog.")
        with st.expander(f"Quarantine table: {n_conf} key(s)"):
            st.dataframe(quality["transmission_conflicts"], width="stretch",
                         hide_index=True)
    else:
        st.success("No conflicting transmission samples remain in the database.")
