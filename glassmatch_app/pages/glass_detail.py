"""Glass Detail tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch.database import PROPERTY_LABELS
from glassmatch.database import PROPERTY_UNITS
from glassmatch.equivalency import curated_equivalents
from glassmatch.matching import WEIGHT_KEYS
from glassmatch.plotting import score_breakdown_figure
import pandas as pd
import streamlit as st


def render(ctx):
    _candidates_for = ctx._candidates_for
    _data_key = ctx._data_key
    db = ctx.db
    results = ctx.results
    scoped = ctx.scoped
    t_mode = ctx.t_mode
    trans = ctx.trans
    trans_basis = ctx.trans_basis
    st.header("Glass detail + provenance")
    gid = st.selectbox("Glass", scoped["glass_id"].tolist() if len(scoped) else results["glass_id"].tolist())
    row = db.get_glass_row(gid)
    mfr = db.get_manufacturer_row(str(row["manufacturer_id"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("n_d", f"{db.property_value(gid, 'refractive_index_nd')}")
    c2.metric("V_d", f"{db.property_value(gid, 'abbe_number_vd')}")
    c3.metric("Manufacturer", str(mfr["name"]) if mfr is not None else "?")
    _t = trans.get(gid)
    st.caption(f"Transmission for the current requirement ({t_mode}): "
               f"{'missing' if _t is None else f'{_t:.1f}'}%"
               f" — {trans_basis.get(gid, 'missing')}")
    st.write(f"**Family:** {row['glass_family']} - {row['description']}")
    st.subheader("Properties and sources")
    for prop, label in PROPERTY_LABELS.items():
        for r in db.property_provenance(gid, prop):
            unit = r.get("unit") or PROPERTY_UNITS.get(prop, "")
            unit = "" if unit != unit else unit
            st.markdown(f"**{label}**: `{r['value']}` {unit} - *{r['data_type']}*")
            st.caption(f"Source: {r['source_name']} ({r['source_id']}) | "
                       f"license: {r['license']} | {r['notes']} {r['source_url']}")
    coef = db.sellmeier_for(gid)
    n_ref_wl = st.number_input("Reference wavelength for n (nm)", 100.0, 20000.0,
                               587.6, 1.0, key=f"nref_{gid}")
    n_val, n_dtype = db.n_at(gid, n_ref_wl)
    if n_val is not None:
        st.markdown(f"**Refractive index at {n_ref_wl:g} nm**: `{n_val:.5f}` "
                    f"- *{n_dtype}*")
    else:
        st.info(f"No refractive index available for this material at "
                f"{n_ref_wl:g} nm (outside the range the cited reference "
                "covers, or the page's dispersion formula is not implemented). "
                "Nothing is extrapolated.")
    tab = db.spectral_nk_for(gid)
    if tab is not None and len(tab):
        with st.expander(f"Tabulated optical constants ({len(tab)} samples, "
                         "literature values)"):
            st.dataframe(tab.head(400), width="stretch")
            st.caption("Verbatim from the cited reference via refractiveindex.info "
                       "(CC0 1.0). No smoothing or fitting applied.")
    if coef is not None:
        from glassmatch.importers.agf import is_dispersable_formula
        from glassmatch.spectra import describe_row
        ok = is_dispersable_formula(coef.get("formula"))
        label = (f"(verified {describe_row(coef)})" if ok
                 else "(ARCHIVED - not verified, never evaluated)")
        with st.expander("Dispersion coefficients " + label):
            keys = ["formula", "zemax_formula", "wavelength_um",
                    "coefficients"] + \
                [c for c in list(coef) if c.startswith(("B", "C"))] + \
                ["source_id", "notes"]
            st.json({k: coef[k] for k in keys
                     if k in coef and not (isinstance(coef[k], float)
                                           and coef[k] != coef[k])})
            if not ok:
                st.warning("These coefficients are archived verbatim and are "
                           "never evaluated: in the formula the catalog names "
                           "they do not reproduce the catalog n(d) and V_d, or "
                           "the catalog gives no n(d) to check them against. "
                           "No dispersion curve is drawn for this glass.")
    with st.expander("Index at temperature n(λ, T, p)"):
        _thermal_section(db, gid)
    with st.expander("Score breakdown"):
        hit = results[results["glass_id"] == gid]
        if not hit.empty:
            r0 = hit.iloc[0]
            st.plotly_chart(score_breakdown_figure(
                {k: (None if pd.isna(r0[f"score_{k}"]) else float(r0[f"score_{k}"]) / 100)
                 for k in WEIGHT_KEYS}), width="stretch")
    st.subheader("Cross-manufacturer substitutions")
    cur = curated_equivalents(db.equivalents, gid)
    cand = _candidates_for(_data_key(), gid)
    if not cur.empty:
        st.markdown("**Curated** - from manufacturer cross-reference / maintainer review")
        st.dataframe(cur, width="stretch", hide_index=True)
    if not cand.empty:
        st.markdown("**Computed candidates** - nearest glasses on shared properties, "
                    "**not** verified equivalences")
        show = cand[["glass", "manufacturer", "confidence", "relation_suggestion",
                     "shared_props", "d_nd", "d_vd", "d_density", "d_cte"]]
        st.dataframe(show, width="stretch", hide_index=True)
        st.download_button("Download these candidates (CSV)", cand.to_csv(index=False),
                           file_name=f"{gid}_equivalency_candidates.csv",
                           mime="text/csv", key="dl_equiv_glass")
    st.caption(
        "Candidates are computed from n_d, V_d, density, CTE and T_g where both "
        "glasses have a value (deltas are candidate minus this glass). They are "
        "starting points for review, **not** manufacturer-stated equivalences: "
        "check melt data, thermal history and coating/availability with the "
        "manufacturer before substituting.")


LINES_NM = (("i", 365.01), ("h", 404.66), ("g", 435.83), ("F", 486.13),
            ("e", 546.07), ("d", 587.56), ("C", 656.27), ("t", 1013.98))


def _thermal_section(db, gid):
    """n at another temperature / pressure, with how each value was got."""
    from glassmatch import thermal
    c1, c2, c3, c4 = st.columns(4)
    t_c = c1.number_input("Temperature (°C)", -273.0, 500.0, 20.0, 5.0,
                          key="th_t")
    p_pa = c2.number_input("Air pressure (Pa, 0 = vacuum)", 0.0, 2e5,
                           thermal.P0, 1000.0, key="th_p")
    absolute = c3.toggle("Absolute (vacuum) index", key="th_abs")
    extra = c4.number_input("Extra wavelength (nm)", 200.0, 20000.0, 1550.0,
                            key="th_wl")
    rows, reasons, notes = [], [], set()
    for name, wl in LINES_NM + ((f"{extra:g} nm", extra),):
        r = thermal.index_at(db, gid, wl, t_c, p_pa, absolute=absolute)
        d = thermal.dn_dt(db, gid, wl, 20.0, 40.0, absolute=True)
        rows.append({"line": name, "λ (nm)": wl,
                     "catalog n": r["n_catalog"],
                     "n(λ, T, p) (calculated)": r["n"],
                     "Δn ×1e6": (None if r["n"] is None or r["n_catalog"] is None
                                 else (r["n"] - r["n_catalog"]) * 1e6),
                     "dn/dT abs +20/+40 °C (1e-6/K)": d["dn_dt"],
                     "method": r["method"] or ""})
        if r["n"] is None and r["reason"]:
            reasons.append(f"{name}: {r['reason']}")
        notes.update(r["notes"] + d["notes"])
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    t0 = thermal.td_record(db, gid)
    st.caption(
        ("Catalog index is relative to air at T0 = "
         f"{t0[6]:g} °C, 101 325 Pa. " if t0 else
         "This glass has no dn/dT model record; its catalog does not state "
         "the reference temperature, so only dn/dT (from the maker's measured "
         "table) is shown. ")
        + "The SCHOTT dn/dT model is used only inside its stated validity "
          "(−100 … +140 °C, 365 … 1014 nm); elsewhere the maker's measured "
          "dn/dT table, when it covers the span. Nothing is extrapolated - see "
          "docs/VALIDATION.md for how the model compares with the tables.")
    for n in sorted(notes):
        st.info(n)
    if reasons:
        with st.expander(f"{len(reasons)} value(s) not given"):
            for r in reasons:
                st.write(r)
