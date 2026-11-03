"""Import / Export tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch.importers.generic_csv import import_csv
import io
import pandas as pd
import streamlit as st


def render(ctx):
    st.header("Import your data")
    st.markdown("User CSV columns: `name, manufacturer, nd, vd, density, cte, "
                "thermal_conductivity, source`.")
    up = st.file_uploader("Upload user glass CSV", type=["csv"])
    if up is not None:
        st.write(pd.read_csv(up).head())
        try:
            g_new, p_new = import_csv(io.BytesIO(up.getvalue()))
            st.success(f"Parsed {len(g_new)} glass(es), {len(p_new)} properties as user_imported.")
            st.dataframe(g_new, width="stretch", hide_index=True)
            import json as _json2
            st.download_button("Download normalized user data (JSON)",
                               _json2.dumps({"glasses": g_new.to_dict(orient="records"),
                                             "properties": p_new.to_dict(orient="records")},
                                            indent=2).encode(),
                               "user_glasses_normalized.json", "application/json")
        except Exception as e:  # noqa: BLE001 - surface import errors in UI
            st.error(f"Import failed: {e}")
    st.subheader("Manufacturer .agf catalog (Ring 1/2 expansion)")
    st.markdown("Download the .agf from the manufacturer link, then upload it here. "
                "GlassMatch parses it locally into normalized rows — bulk catalogs are "
                "never bundled or redistributed.")
    from glassmatch.importers.catalogs import CATALOGS
    cat = st.selectbox("Catalog", sorted(CATALOGS),
                       format_func=lambda k: f"{k} — {CATALOGS[k]['label']}")
    st.caption(f"Download: {CATALOGS[cat]['download_url']} | {CATALOGS[cat]['hint']} "
               f"| License: {CATALOGS[cat]['license']}")
    agf = st.file_uploader("Upload .agf file", type=["agf"])
    if agf is not None:
        from glassmatch.importers.agf import parse_agf_text
        sid = st.text_input("Source ID for these rows", f"{cat}-AGF-USER")
        try:
            g2, p2, s2, t2, iss = parse_agf_text(
                agf.getvalue().decode("utf-8", errors="replace"),
                cat, sid, CATALOGS[cat]["material_class"])
            st.success(f"Parsed {len(g2)} glass(es), {len(p2)} properties, "
                       f"{len(s2)} Sellmeier rows, {len(t2)} transmission rows.")
            st.dataframe(g2, width="stretch", hide_index=True)
            if iss:
                st.warning(f"{len(iss)} flagged record(s) — review, nothing auto-fixed.")
                st.dataframe(pd.DataFrame(iss), width="stretch", hide_index=True)
            import json as _json3
            st.download_button("Download normalized .agf import (JSON)",
                               _json3.dumps({"glasses": g2.to_dict(orient="records"),
                                             "properties": p2.to_dict(orient="records"),
                                             "sellmeier": s2.to_dict(orient="records"),
                                             "transmission": t2.to_dict(orient="records"),
                                             "issues": iss}, indent=2,
                                            default=str).encode(),
                               "agf_import_normalized.json", "application/json")
        except Exception as e:  # noqa: BLE001 - surface import errors in UI
            st.error(f".agf import failed: {e}")
