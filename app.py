"""GlassMatch: open-source optical glass selection & material database."""
from __future__ import annotations
import io
import numpy as np
import pandas as pd
import streamlit as st

from glassmatch.database import load_default_database, PROPERTY_LABELS, PROPERTY_UNITS, DEFAULT_DATA_DIR
from glassmatch.matching import DEFAULT_WEIGHTS, WEIGHT_KEYS, match_glasses
from glassmatch.spectra import dispersion_curve, fresnel_transmission, band_stats
from glassmatch.plotting import dispersion_figure, transmission_figure, score_breakdown_figure
from glassmatch.validation import (validate_property_frame, validate_glass_frame,
                                   validate_transmission_frame, orphan_source_ids)
from glassmatch.importers.generic_csv import import_csv

st.set_page_config(page_title="GlassMatch", page_icon="🔭", layout="wide")

PRESETS = {
    "UV (0.30-0.40 um)": (0.30, 0.40), "Visible (0.40-0.70 um)": (0.40, 0.70),
    "NIR (0.70-1.40 um)": (0.70, 1.40), "SWIR (1.40-3.00 um)": (1.40, 3.00),
    "MWIR (3.00-5.00 um)": (3.00, 5.00), "Custom": None,
}
APP_PRESETS = {
    "General Visible Imaging": {"wl": "Visible (0.40-0.70 um)", "tmin": 90.0,
        "weights": {"nd": 25, "vd": 20, "transmission": 35, "density": 10, "cte": 10}},
    "Laser Optics": {"wl": "NIR (0.70-1.40 um)", "tmin": 95.0,
        "weights": {"nd": 35, "vd": 10, "transmission": 40, "density": 5, "cte": 10}},
    "Broadband Imaging": {"wl": "Visible (0.40-0.70 um)", "tmin": 92.0,
        "weights": {"nd": 30, "vd": 25, "transmission": 30, "density": 10, "cte": 5}},
    "UV Optics": {"wl": "UV (0.30-0.40 um)", "tmin": 80.0,
        "weights": {"nd": 25, "vd": 20, "transmission": 40, "density": 5, "cte": 10}},
    "Thermally Stable Systems": {"wl": "Visible (0.40-0.70 um)", "tmin": 85.0,
        "weights": {"nd": 25, "vd": 15, "transmission": 20, "density": 10, "cte": 30}},
    "Low-Dispersion Imaging": {"wl": "Visible (0.40-0.70 um)", "tmin": 90.0,
        "weights": {"nd": 20, "vd": 40, "transmission": 25, "density": 10, "cte": 5}},
}


def _data_key() -> str:
    """Fingerprint of the normalized CSVs — changes when data files change,
    so edited/imported data appears without restarting the server."""
    parts = []
    try:
        for f in sorted(DEFAULT_DATA_DIR.glob("*.csv")):
            stt = f.stat()
            parts.append(f"{f.name}:{stt.st_mtime_ns}:{stt.st_size}")
    except OSError:
        return "unavailable"
    return "|".join(parts)


@st.cache_resource
def _load_all(_key: str):
    db = load_default_database()
    summary = db.summary_frame()
    t_groups = {}
    if not db.transmission.empty and "glass_id" in db.transmission.columns:
        t_groups = {str(gid): sub.reset_index(drop=True)
                    for gid, sub in db.transmission.groupby("glass_id")}
    quality = {
        "properties": validate_property_frame(db.properties),
        "glasses": validate_glass_frame(db.glasses),
        "transmission": validate_transmission_frame(db.transmission),
        "orphan_sources": orphan_source_ids(db.glasses, db.properties, db.sources),
    }
    return db, summary, t_groups, quality


db, summary, t_groups, quality = _load_all(_data_key())

st.title("GlassMatch")
st.subheader("Open-source optical glass selection, comparison, and material database")
st.caption("Traceable data \u2022 transparent scores \u2022 calculated values always labelled \u2014 "
           "verify against manufacturer datasheets before detailed design.")

# ---------- Sidebar: requirements ----------
st.sidebar.header("1 \u2022 Requirements")
app_preset = st.sidebar.selectbox("Application preset (sets defaults; editable)",
                                  ["(none)"] + list(APP_PRESETS))
p = APP_PRESETS.get(app_preset, {})
if p:
    st.sidebar.info(f"Preset **{app_preset}** set defaults below \u2014 all fields remain editable.")

wl_preset = st.sidebar.selectbox("Wavelength preset", list(PRESETS),
                                 index=1 if not p else list(PRESETS).index(p["wl"]))
wl_unit = st.sidebar.radio("Wavelength unit", ["nm", "\u03bcm"], horizontal=True)
factor = 1000.0 if wl_unit == "nm" else 1.0
rng = PRESETS[wl_preset]
d_lo, d_hi = (rng[0] * factor, rng[1] * factor) if rng else (400.0 if wl_unit == "nm" else 0.4,
                                                            700.0 if wl_unit == "nm" else 0.7)
wl_min = st.sidebar.number_input(f"Min wavelength ({wl_unit})", value=float(d_lo))
wl_max = st.sidebar.number_input(f"Max wavelength ({wl_unit})", value=float(d_hi))
wl_min_um, wl_max_um = wl_min / factor, wl_max / factor
if wl_min_um >= wl_max_um:
    st.sidebar.error("Minimum wavelength must be < maximum wavelength.")

nd_min, nd_max = st.sidebar.slider("Refractive index n_d range", 1.30, 2.10, (1.45, 1.85), 0.005)
vd_min, vd_max = st.sidebar.slider("Abbe number V_d range", 15.0, 95.0, (20.0, 85.0), 0.5)
t_min = st.sidebar.slider("Minimum transmission (%)", 0.0, 99.0, float(p.get("tmin", 85.0)), 0.5)
t_mode = st.sidebar.radio("Transmission requirement applies to", ["Average", "Minimum", "Entire range"],
                          horizontal=True)
d_lo2, d_hi2 = st.sidebar.slider("Density range (g/cm^3, optional filter)", 1.5, 6.0, (1.5, 6.0), 0.05)
use_density = st.sidebar.checkbox("Filter by density", value=False)
cte_max = st.sidebar.slider("Max CTE (1e-6/K, optional filter)", 0.0, 20.0, 20.0, 0.1)
use_cte = st.sidebar.checkbox("Filter by CTE", value=False)
require_data = st.sidebar.checkbox("Require available data (missing = fail)",
                                   value=False,
                                   help="If off, missing data is flagged, not failed.")

st.sidebar.header("2 \u2022 Weights (%)")
w_in = {}
for k in WEIGHT_KEYS:
    default = float(p.get("weights", DEFAULT_WEIGHTS).get(k, DEFAULT_WEIGHTS[k]))
    w_in[k] = st.sidebar.slider(k, 0.0, 100.0, default, 1.0,
                                help="Relative importance; auto-normalized to 100%.")
tot = sum(w_in.values()) or 1.0
w_norm = {k: v / tot for k, v in w_in.items()}
st.sidebar.caption("Normalized: " + " \u2022 ".join(f"{k} {v*100:.0f}%" for k, v in w_norm.items()))

requirements = {"nd_min": nd_min, "nd_max": nd_max, "vd_min": vd_min, "vd_max": vd_max,
                "transmission_min": t_min, "transmission_mode": t_mode,
                "density_min": d_lo2 if use_density else None,
                "density_max": d_hi2 if use_density else None,
                "cte_min": None, "cte_max": cte_max if use_cte else None}
def n_at(db, gid, wl_um):
    c = db.sellmeier_for(gid, sellmeier_only=True)
    if c is None:
        return None
    from glassmatch.spectra import sellmeier_n
    try:
        return sellmeier_n(wl_um, (float(c["B1"]), float(c["B2"]), float(c["B3"])),
                           (float(c["C1_um2"]), float(c["C2_um2"]), float(c["C3_um2"])))
    except (TypeError, ValueError):
        return None


def transmission_estimate(db, gid, wl_lo_um, wl_hi_um, n=12):
    """Mean uncoated Fresnel transmittance. CALCULATED, labelled."""
    c = db.sellmeier_for(gid)
    if c is None:
        return None, "missing (no Sellmeier data)"
    import numpy as np
    wls = np.linspace(wl_lo_um, wl_hi_um, n)
    vals = [fresnel_transmission(n_at(db, gid, w)) for w in wls]
    vals = [v for v in vals if v == v]
    if not vals:
        return None, "missing"
    return float(sum(vals) / len(vals) * 100.0), "calculated (Fresnel, uncoated)"


def band_transmission(gid, lo_um, hi_um, mode):
    """(value_pct | None, basis label) for the selected requirement mode.

    Manufacturer transmission.csv rows are preferred. If the glass HAS
    manufacturer rows but they can't satisfy the mode (no samples in band,
    or Entire-range coverage too sparse), the value is reported missing
    rather than silently substituting a calculated estimate. Fresnel is
    only the fallback when the glass has no manufacturer rows at all.
    """
    s = band_stats(t_groups.get(str(gid)), lo_um, hi_um, mode)
    if s is not None:
        if s.get("value_pct") is not None:
            return s["value_pct"], s["label"]
        return None, f"missing ({s['label']})"
    v, note = transmission_estimate(db, gid, lo_um, hi_um)
    return v, note


trans, trans_basis = {}, {}
for gid in summary["glass_id"]:
    v, basis = band_transmission(gid, wl_min_um, wl_max_um, t_mode)
    trans[gid] = v
    trans_basis[gid] = basis

results = match_glasses(summary, requirements, w_in, transmissions=trans,
                        require_data=require_data)

tabs = st.tabs(["Matching Glasses", "Glass Detail", "Spectral Analysis",
                "Comparison", "Database Explorer", "Data Sources",
                "Import / Export"])

with tabs[0]:
    st.header("Matching glasses")
    st.caption("Compatibility Score = weighted requirement match (never 'best glass').")
    mf_match = st.multiselect("Manufacturers in scope", sorted(results["manufacturer"].unique()),
                              default=sorted(results["manufacturer"].unique()))
    scoped = results[results["manufacturer"].isin(mf_match)] if mf_match else results.iloc[0:0]
    st.caption(f"{len(scoped)} of {len(results)} glasses in scope.")
    page_size = st.selectbox("Rows per page", [25, 50, 100, 250], index=1)
    n_pages = max(1, (len(scoped) + page_size - 1) // page_size)
    page = st.number_input("Page", min_value=1, max_value=n_pages, value=1)
    show = scoped.iloc[(page - 1) * page_size: page * page_size].copy()
    show["transmission_%"] = show["glass_id"].map(
        lambda g: None if trans.get(g) is None else round(trans[g], 1))
    if show["ir_mode"].astype(bool).any():
        show.loc[show["ir_mode"].astype(bool), "vd"] = None  # V_d meaningless for IR
        show["class"] = show.apply(
            lambda r: "IR material" if r["ir_mode"] else str(r["material_class"]), axis=1)
        st.caption("IR materials (shaded class): V_d not applicable — weight "
                   "redistributed to n_d + transmission, never penalized.")
    else:
        show["class"] = show["material_class"]
    st.dataframe(show[["glass", "manufacturer", "compatibility", "nd", "vd", "density",
                        "cte", "transmission_%", "completeness", "missing", "class"]],
                 width="stretch", hide_index=True)
    n_mfr = sum(1 for g in scoped["glass_id"] if str(trans_basis.get(g, "")).startswith("manufacturer"))
    n_calc = sum(1 for g in scoped["glass_id"] if str(trans_basis.get(g, "")).startswith("calculated"))
    n_miss = len(scoped) - n_mfr - n_calc
    st.caption(f"Transmission basis ({t_mode} of band): {n_mfr} manufacturer IT rows · "
               f"{n_calc} calculated Fresnel · {n_miss} missing — full labels in the CSV export. "
               f"Page {page} of {n_pages}.")
    st.download_button("Export results CSV (in-scope glasses)",
                       scoped.assign(transmission_pct=scoped["glass_id"].map(trans),
                                     transmission_basis=scoped["glass_id"].map(trans_basis)
                                     .fillna("missing")).to_csv(
                           index=False).encode(),
                       "glassmatch_results.csv", "text/csv")
    import json as _json
    st.download_button("Export requirements + results JSON",
                       _json.dumps({"requirements": requirements, "weights": w_norm,
                                    "results": scoped.to_dict(orient="records")},
                                   indent=2, default=str).encode(),
                       "glassmatch_results.json", "application/json")
    with st.expander("How is Compatibility calculated?"):
        st.markdown(
            "- Each requirement (n_d, V_d, transmission, density, CTE) scores 0-1: "
            "1.0 inside the band, linear falloff outside.\n"
            "- Overall = weighted mean over **available** data x coverage factor "
            "(0.5 + 0.5 x covered weight).\n"
            "- IR materials (chalcogenide/IR makers): V_d weight moves to "
            "n_d (60%) + transmission (40%); V_d is shown as n/a, never scored.\n"
            f"- Transmission modes (**{t_mode}**): *Average* = mean of samples in "
            "band; *Minimum* = worst sample; *Entire range* = worst sample but only "
            "when manufacturer samples span >=90% of the band — otherwise the value "
            "is reported missing, never guessed.\n"
            "- Transmission values prefer manufacturer IT rows (transmission.csv); "
            "a calculated uncoated Fresnel estimate is used only when a glass has no "
            "manufacturer rows at all, and is labelled as calculated.")
with tabs[1]:
    st.header("Glass detail + provenance")
    gid = st.selectbox("Glass", scoped["glass_id"].tolist() if len(scoped) else results["glass_id"].tolist())
    row = db.get_glass_row(gid)
    mfr = db.get_manufacturer_row(str(row["manufacturer_id"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("n_d", f"{db.property_value(gid, 'refractive_index_nd')}")
    c2.metric("V_d", f"{db.property_value(gid, 'abbe_number_vd')}")
    c3.metric("Manufacturer", str(mfr["name"]) if mfr is not None else "?")
    st.caption(f"Transmission for the current requirement ({t_mode}): "
               f"{trans.get(gid) if trans.get(gid) is not None else 'missing'}%"
               f" — {trans_basis.get(gid, 'missing')}")
    st.write(f"**Family:** {row['glass_family']} - {row['description']}")
    st.subheader("Properties and sources")
    for prop, label in PROPERTY_LABELS.items():
        for r in db.property_provenance(gid, prop):
            unit = PROPERTY_UNITS.get(prop, "")
            st.markdown(f"**{label}**: `{r['value']}` {unit} - *{r['data_type']}*")
            st.caption(f"Source: {r['source_name']} ({r['source_id']}) | "
                       f"license: {r['license']} | {r['notes']} {r['source_url']}")
    coef = db.sellmeier_for(gid)
    if coef is not None:
        from glassmatch.importers.agf import is_sellmeier1_formula
        ok = is_sellmeier1_formula(coef.get("formula"))
        with st.expander("Dispersion coefficients "
                         + ("(verified Sellmeier-1)" if ok else "(ARCHIVED non-Sellmeier — not for curves)")):
            st.json({k: coef[k] for k in ("formula", "wavelength_um", "B1", "B2",
                                          "B3", "C1_um2", "C2_um2", "C3_um2",
                                          "source_id", "notes")})
            if not ok:
                st.warning("These coefficients are archived verbatim and must not be "
                           "evaluated as Sellmeier-1 (e.g. Nikon polynomial, Herzberger "
                           "legacy rows). No dispersion curve is drawn for this glass.")
    with st.expander("Score breakdown"):
        hit = results[results["glass_id"] == gid]
        if not hit.empty:
            r0 = hit.iloc[0]
            st.plotly_chart(score_breakdown_figure(
                {k: (None if pd.isna(r0[f"score_{k}"]) else float(r0[f"score_{k}"]) / 100)
                 for k in WEIGHT_KEYS}), width="stretch")
    eq = db.equivalents_for(gid)
    if not eq.empty:
        st.subheader("Known near-equivalents (verify melt data before substitution)")
        st.dataframe(eq, width="stretch", hide_index=True)
        st.caption("Seed examples — the bulk cross-reference table has not been "
                   "imported yet. Contribute manufacturer equivalency charts via PR.")
with tabs[2]:
    st.header("Spectral analysis")
    pool = scoped["glass_id"].tolist() if len(scoped) else results["glass_id"].tolist()
    sel = st.multiselect("Glasses on plot (max 8 for readability)", pool,
                         default=pool[:3], max_selections=8)
    wls = np.linspace(max(wl_min_um, 0.30), min(max(wl_max_um, 0.31), 2.5), 60)
    dcurves, tcurves = {}, {}
    non_sell, t_manufacturer, t_calculated, t_missing = [], [], [], []
    for g in sel:
        # --- transmission: manufacturer rows preferred, Fresnel fallback ---
        tdf = t_groups.get(str(g))
        if tdf is not None and len(tdf) >= 2:
            thick = tdf["thickness_mm"].dropna()
            thick_s = f", {thick.iloc[0]:g} mm as listed" if len(thick) else ""
            tcurves[g] = pd.DataFrame({
                "wavelength_um": tdf["wavelength_um"],
                "transmission_pct": tdf["transmission"] * 100.0,
                "data_type": f"manufacturer IT{thick_s}"})
            t_manufacturer.append(g)
        elif db.dispersion_status(g) == "sellmeier1":
            c = db.sellmeier_for(g, sellmeier_only=True)
            df = dispersion_curve(c, list(wls))
            tcurves[g] = pd.DataFrame({"wavelength_um": df["wavelength_um"],
                                       "transmission_pct": df["n"].map(
                                           lambda n: fresnel_transmission(n) * 100),
                                       "data_type": "calculated (Fresnel, uncoated)"})
            t_calculated.append(g)
        else:
            t_missing.append(g)
        # --- dispersion: verified Sellmeier-1 only ---
        status = db.dispersion_status(g)
        if status != "sellmeier1":
            non_sell.append(g)
            continue
        c = db.sellmeier_for(g, sellmeier_only=True)
        dcurves[g] = dispersion_curve(c, list(wls))
    if non_sell:
        st.warning("Dispersion curve unavailable (coefficients archived, not Sellmeier-1 — "
                   "never evaluated as Sellmeier): " + ", ".join(non_sell))
    if t_missing:
        st.info("No transmission data for: " + ", ".join(t_missing))
    if dcurves:
        st.plotly_chart(dispersion_figure(dcurves, "nm" if wl_unit == "nm" else "um"),
                        width="stretch")
        st.caption("CALCULATED from Sellmeier coefficients - not manufacturer tables.")
    if tcurves:
        st.plotly_chart(transmission_figure(tcurves, "nm" if wl_unit == "nm" else "um",
                                            band=(wl_min_um, wl_max_um)),
                        width="stretch")
        st.caption(
            f"Manufacturer IT rows: {len(t_manufacturer)} glass(es); "
            f"calculated uncoated Fresnel: {len(t_calculated)} glass(es) — "
            "each trace is labelled by basis. Thickness applies as listed; "
            "internal transmittance is not corrected to your sample thickness.")
with tabs[3]:
    st.header("Comparison (2-5 glasses)")
    comp = st.multiselect("Select glasses", results["glass_id"].tolist(),
                          default=results["glass_id"].tolist()[:2], max_selections=5)
    if len(comp) >= 2:
        st.dataframe(results[results["glass_id"].isin(comp)].set_index("glass_id")
                     .astype(str).T, width="stretch")
    else:
        st.info("Select at least 2 glasses.")

with tabs[4]:
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
    st.dataframe(view, width="stretch", hide_index=True)
    st.caption(f"{len(view)} of {len(summary)} glasses shown. "
               "Coverage grows ring by ring: core catalogs -> crystals/IR -> polymers.")
    cov = summary.groupby("manufacturer_id").agg(
        glasses=("glass_id", "count"),
        with_sellmeier=("has_sellmeier", "sum")).reset_index()
    st.subheader("Catalog coverage")
    st.dataframe(cov, width="stretch", hide_index=True)

with tabs[5]:
    st.header("Data sources and licensing")
    st.dataframe(db.sources, width="stretch", hide_index=True)
    st.warning("Catalog nd/Vd beyond N-BK7 are transcribed reference values: "
               "re-verify against the current manufacturer datasheet before detailed design. "
               "Sellmeier rows are CC0 mirrors via refractiveindex.info; manufacturers stay authoritative.")
    st.subheader("Data quality report")
    n_prop, n_glass = len(quality["properties"]), len(quality["glasses"])
    n_trans, n_orph = len(quality["transmission"]), len(quality["orphan_sources"])
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Property flags", n_prop)
    q2.metric("Glass flags", n_glass)
    q3.metric("Transmission flags", n_trans)
    q4.metric("Orphan source refs", n_orph)
    total = n_prop + n_glass + n_trans + n_orph
    if total == 0:
        st.success("All checks pass — no flagged records. Nothing is auto-fixed; "
                   "flags here would list questionable records for review.")
    else:
        st.caption("Flagged records are listed, never silently corrected. "
                   "Review before relying on them.")
        for title, key in [("Properties", "properties"), ("Glasses", "glasses"),
                           ("Transmission samples", "transmission")]:
            if quality[key]:
                with st.expander(f"{title}: {len(quality[key])} flagged record(s)"):
                    st.dataframe(pd.DataFrame(quality[key]), width="stretch", hide_index=True)
        if quality["orphan_sources"]:
            st.warning("source_ids referenced by data but missing from sources.csv: "
                       + ", ".join(quality["orphan_sources"]))

with tabs[6]:
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




