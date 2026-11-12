"""Matching Glasses tab - moved verbatim from app.py; shared state arrives in ctx."""
from __future__ import annotations

from glassmatch import __version__
from glassmatch.transmission import band_label
import streamlit as st


def render(ctx):
    DATA_VERSION = ctx.DATA_VERSION
    _col_label = ctx._col_label
    agf_download = ctx.agf_download
    col_table = ctx.col_table
    dndt_max = ctx.dndt_max
    excluded_examples = ctx.excluded_examples
    extra_cols = ctx.extra_cols
    n_excluded = ctx.n_excluded
    n_range_filtered = ctx.n_range_filtered
    n_ref_nm = ctx.n_ref_nm
    n_unavailable = ctx.n_unavailable
    nd_override = ctx.nd_override
    requirements = ctx.requirements
    results = ctx.results
    t_mode = ctx.t_mode
    t_basis = getattr(ctx, "t_basis", "internal")
    trans = ctx.trans
    trans_basis = ctx.trans_basis
    bands = ctx.bands
    band_results = ctx.band_results
    w_norm = ctx.w_norm
    where = ctx.where
    st.subheader("Ranked by your requirements")
    st.caption("Compatibility Score = weighted requirement match (never 'best glass').")
    if ctx.n_band_data_removed:
        st.caption(f"{ctx.n_band_data_removed:,} glass(es) removed for having no "
                   "transmission data in a required band ("
                   + ", ".join(ctx.bands_required) + "; sidebar).")
    if ctx.n_mirror_hidden:
        st.caption(f"{ctx.n_mirror_hidden:,} glass(es) from third-party mirrors "
                   "of unknown date hidden (sidebar: 'Include unverified "
                   "mirrors').")
    if n_unavailable:
        st.caption(f"{n_unavailable:,} material(s) hidden by the Availability "
                   "filter (obsolete glasses are hidden by default).")
    n_dndt = int(results.attrs.get("dndt_filtered", 0))
    if n_dndt:
        st.info(f"**{n_dndt:,} material(s) removed** by the |dn/dT| limit of "
                f"{dndt_max:g}e-6/K.")
    if n_excluded:
        detail = ", ".join(f"{r['glass_id']} (no {r['blocking_missing']})"
                           for r in excluded_examples[:3])
        st.info(
            f"**{n_excluded:,} material(s) excluded** by \u201cRequire available "
            f"data\u201d \u2014 they have no value for a property you set a "
            f"requirement on. Example: {detail}. Clear the checkbox to see them "
            f"anyway, flagged as missing rather than failed.")
    mf_match = st.multiselect("Manufacturers in scope", sorted(results["manufacturer"].unique()),
                              default=sorted(results["manufacturer"].unique()))
    scoped = results[results["manufacturer"].isin(mf_match)] if mf_match else results.iloc[0:0]
    st.caption(f"{len(scoped)} of {len(results)} glasses in scope.")
    page_size = st.selectbox("Rows per page", [25, 50, 100, 250], index=1)
    n_pages = max(1, (len(scoped) + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=n_pages, value=1)
    show = scoped.iloc[(page - 1) * page_size: page * page_size].copy()
    show["supply"] = show["glass_id"].map(ctx.supply_map).fillna("")
    show["transmission_%"] = show["glass_id"].map(
        lambda g: None if trans.get(g) is None else round(trans[g], 1))
    # Several bands: each band's own figure beside the combined (worst-band)
    # one, so it is visible which band limits a glass.
    band_cols = {}
    if len(bands) > 1:
        for (lo, hi), (vals, _b) in zip(bands, band_results):
            band_cols[f"T {band_label(lo, hi)} (%)"] = vals
        for col, vals in band_cols.items():
            show[col] = show["glass_id"].map(vals)
    if show["ir_mode"].astype(bool).any():
        show.loc[show["ir_mode"].astype(bool), "vd"] = None  # V_d undefined here
        # "IR material" is a label, not a judgement: CaF2 and fused silica are
        # crystals that happen to have no Abbe number, and calling them IR
        # materials misdescribes them. Only the genuinely IR classes get it.
        _ir_classes = {"chalcogenide", "crystal_ir"}
        show["class"] = show.apply(
            lambda r: "IR material"
            if (r["ir_mode"] and str(r["material_class"]) in _ir_classes)
            else str(r["material_class"]), axis=1)
        st.caption("IR materials and crystals: V_d not applicable — the Abbe "
                   "weight is redistributed to index + transmission, never "
                   "penalized. Crystals are scored on n at the reference "
                   "wavelength, not on a catalog n_d.")
    else:
        show["class"] = show["material_class"]
    _base = ["glass", "manufacturer", "compatibility", "nd", "vd", "density",
             "cte", "dn_dt", "transmission_%", *band_cols, "status", "supply",
             "completeness", "missing", "class",
             *(["data_tier"] if ctx.include_mirrors else [])]
    _extra = [c for c in dict.fromkeys(extra_cols + list(where))
              if c not in _base]
    if _extra:
        show = show.join(col_table[_extra], on="glass_id")
    st.dataframe(show[_base + _extra].rename(
                     columns={**{c: _col_label(c) for c in _extra},
                              **({"transmission_%": "transmission_% (worst band)"}
                                 if band_cols else {})}),
                 width="stretch", hide_index=True)
    _axes = (ctx.db.glasses.set_index("glass_id")["optic_axis"]
             if "optic_axis" in ctx.db.glasses.columns else None)
    if _axes is not None and scoped["glass_id"].map(_axes).isin(["o", "e"]).any():
        st.caption("Rows marked o-ray / e-ray are one polarisation of a "
                   "birefringent crystal (ordinary / extraordinary ray), not an "
                   "isotropic material: the other polarisation sees a "
                   "different index.")
    if n_range_filtered:
        st.caption(f"{n_range_filtered:,} material(s) removed by the range "
                   "filters.")
    if nd_override and (scoped["nd_basis"] == "n at reference wavelength").any():
        n_ov = int((scoped["nd_basis"] == "n at reference wavelength").sum())
        st.caption(
            f"The **n** column is a catalog n_d for {len(scoped) - n_ov} of these "
            f"results, and n at {n_ref_nm:g} nm for {n_ov} material(s) that have "
            f"no d-line entry (crystals). V_d is shown blank for those because "
            f"the Abbe number is not defined for them.")
    # On the uncoated basis a maker's samples carry a calculated reflection
    # loss, so their label starts "calculated from manufacturer ...".
    _labels = [str(trans_basis.get(g, "")) for g in scoped["glass_id"]]
    n_mfr = sum(1 for b in _labels
                if b.startswith(("manufacturer", "calculated from manufacturer")))
    n_calc = sum(1 for b in _labels if b.startswith("calculated")) - sum(
        1 for b in _labels if b.startswith("calculated from manufacturer"))
    n_ub = sum(1 for g in scoped["glass_id"]
               if "reflection-only upper bound" in str(trans_basis.get(g, "")))
    n_miss = len(scoped) - n_mfr - n_calc - n_ub
    if band_cols:
        st.caption(f"{len(bands)} bands, all required: "
                   + ", ".join(band_label(lo, hi) for lo, hi in bands)
                   + ". Basis counts below are for each glass's limiting band; "
                   "a glass with no value in any band is counted missing.")
    _what = ("internal transmittance" if t_basis == "internal" else
             "uncoated blank, reflection at both surfaces included")
    st.caption(f"Transmission ({t_mode} of band; {_what}): {n_mfr} from "
               f"manufacturer IT rows · "
               f"{n_calc} calculated from tabulated n/k · {n_ub} upper bound only "
               f"(reflection loss, absorption unknown) · {n_miss} missing — "
               f"full labels in the CSV export. "
               f"Page {page} of {n_pages}.")
    st.download_button("Export results CSV (in-scope glasses)",
                       scoped.assign(transmission_pct=scoped["glass_id"].map(trans),
                                     supply=scoped["glass_id"].map(ctx.supply_map),
                                     **{c: scoped["glass_id"].map(v)
                                        for c, v in band_cols.items()},
                                     transmission_basis=scoped["glass_id"].map(trans_basis)
                                     .fillna("missing"),
                                     data_version=DATA_VERSION)
                       .join(col_table[[c for c in dict.fromkeys(extra_cols + list(where))
                                        if c not in scoped.columns]], on="glass_id")
                       .to_csv(
                           index=False).encode(),
                       "glassmatch_results.csv", "text/csv")
    import json as _json
    st.download_button("Export requirements + results JSON",
                       _json.dumps({"glassmatch": __version__,
                                    "data_version": DATA_VERSION,
                                    "requirements": requirements, "weights": w_norm,
                                    "results": scoped.to_dict(orient="records")},
                                   indent=2, default=str).encode(),
                       "glassmatch_results.json", "application/json")
    agf_download(scoped["glass_id"].tolist(), "match")
    with st.expander("How is Compatibility calculated?"):
        st.markdown(
            "- Each requirement (n_d, V_d, transmission, density, CTE) scores 0-1: "
            "1.0 inside the band, linear falloff outside.\n"
            "- Overall = weighted mean over **available** data x coverage factor "
            "(0.5 + 0.5 x covered weight).\n"
            "- IR materials and crystals: V_d weight moves to index (60%) + "
            "transmission (40%); V_d is shown as n/a, never scored. Crystals "
            "are judged on n at the reference wavelength.\n"
            f"- Transmission modes (**{t_mode}**): *Average* = mean of samples in "
            "band; *Minimum* = worst sample; *Entire range* = worst sample but only "
            "when manufacturer samples span >=90% of the band — otherwise the value "
            "is reported missing, never guessed.\n"
            "- Every value is on the sidebar's **transmission basis**: internal "
            "(bulk only - what makers list) or an uncoated blank (reflection at "
            "both surfaces included, calculated). The two are never mixed in "
            "one ranking.\n"
            "- Transmission values prefer manufacturer IT rows (transmission.csv), "
            "then transmission calculated from tabulated k (measured tables "
            "only - never a table computed from a dispersion model). A glass with "
            "neither has only the uncoated Fresnel reflection loss, which ignores "
            "absorption: it is stated as an upper bound and the glass counts as "
            "missing, so it never meets a transmission requirement on it.")

    return {"scoped": scoped}
