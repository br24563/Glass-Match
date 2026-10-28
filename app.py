"""GlassMatch: open-source optical glass selection & material database."""
from __future__ import annotations
import io
import numpy as np
import pandas as pd
import streamlit as st

from glassmatch import __version__
from glassmatch.database import load_default_database, PROPERTY_LABELS, PROPERTY_UNITS, DEFAULT_DATA_DIR
from glassmatch.matching import DEFAULT_WEIGHTS, WEIGHT_KEYS, match_glasses
from glassmatch.spectra import (dispersion_curve, fresnel_transmission,
                                scale_internal_transmittance)
from glassmatch.transmission import band_transmission as _band_transmission
from glassmatch.plotting import (dispersion_figure, transmission_figure, score_breakdown_figure,
                                 glass_map_figure, partial_dispersion_figure)
from glassmatch import pairs as gpairs
from glassmatch.validation import (validate_property_frame, validate_glass_frame,
                                   validate_transmission_frame,
                                   validate_spectral_nk_frame,
                                   orphan_source_ids,
                                   orphan_glass_ids,
                                   find_transmission_conflicts)
from glassmatch.importers.generic_csv import import_csv
from glassmatch.equivalency import (EquivalencyCriteria, candidate_pairs,
                                    candidates_for, curated_equivalents)

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
    nk_groups = {}
    if not db.spectral_nk.empty and "glass_id" in db.spectral_nk.columns:
        nk_groups = {str(gid): sub.reset_index(drop=True)
                     for gid, sub in db.spectral_nk.groupby("glass_id")}
    quality = {
        "properties": validate_property_frame(db.properties),
        "glasses": validate_glass_frame(db.glasses),
        "transmission": validate_transmission_frame(db.transmission),
        "spectral_nk": validate_spectral_nk_frame(db.spectral_nk),
        "orphan_sources": orphan_source_ids(db.glasses, db.properties, db.sources),
        "orphan_glasses": orphan_glass_ids(db.properties, db.glasses),
        "transmission_conflicts": _load_transmission_conflicts(db),
    }
    return db, summary, t_groups, nk_groups, quality


def _load_transmission_conflicts(db) -> pd.DataFrame:
    """Quarantine ledger for conflicting transmission samples.

    Read from the committed CSV; re-derived from the live table if any conflict
    ever reappears (e.g. a user import), so the report can never claim a clean
    database while conflicting samples are present.
    """
    path = DEFAULT_DATA_DIR / "transmission_conflicts.csv"
    stored = pd.read_csv(path) if path.exists() else pd.DataFrame()
    live = find_transmission_conflicts(db.transmission)
    if live.empty:
        return stored
    if stored.empty:
        return live
    seen = {tuple(k) for k in stored[["glass_id", "wavelength_um", "thickness_mm"]]
            .itertuples(index=False, name=None)}
    extra = [r for _, r in live.iterrows()
             if (r["glass_id"], r["wavelength_um"], r["thickness_mm"]) not in seen]
    return pd.concat([stored, pd.DataFrame(extra)], ignore_index=True) if extra else stored


db, summary, t_groups, nk_groups, quality = _load_all(_data_key())


@st.cache_resource
def _glass_table(_key: str):
    """Per-glass n_d, V_d, P_g,F (calculated), dPgF and thermo-optic
    coefficient for the glass map and pair finder; built once per data set."""
    return gpairs.glass_table(summary, gpairs.partial_dispersion_table(db), db)


gtable = _glass_table(_data_key())

st.title("GlassMatch")
st.subheader("Open-source optical glass selection, comparison, and material database")
st.caption("Traceable data \u2022 transparent scores \u2022 calculated values always labelled \u2014 "
           "verify against manufacturer datasheets before detailed design.")
st.caption(f"GlassMatch v{__version__} | {len(db.glasses):,} glasses | "
           f"{db.glasses['manufacturer_id'].nunique()} manufacturers | "
           f"{len(db.sources):,} sources")

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
with st.sidebar.expander("Crystals & materials without n_d / V_d"):
    st.caption(
        "Crystals were never sold as optical glasses, so they have no catalog "
        "n_d and no Abbe number. To let them be searched rather than merely "
        "browsed, GlassMatch judges them on **n at the reference wavelength "
        "below** and on transmission, and marks V_d as not applicable.")
    n_ref_nm = st.number_input("Index reference wavelength (nm)", min_value=200.0,
                               max_value=25000.0, value=587.6, step=0.1,
                               help="Applied to crystals and other materials with "
                                    "no catalog n_d. Glasses keep their own n_d.")
vd_min, vd_max = st.sidebar.slider("Abbe number V_d range", 15.0, 95.0, (20.0, 85.0), 0.5)
t_min = st.sidebar.slider("Minimum transmission (%)", 0.0, 99.0, float(p.get("tmin", 85.0)), 0.5)
t_mode = st.sidebar.radio("Transmission requirement applies to", ["Average", "Minimum", "Entire range"],
                          horizontal=True)
sample_thickness_mm = st.sidebar.number_input(
    "Sample thickness for transmission (mm)", min_value=0.1, max_value=100.0,
    value=10.0, step=0.5,
    help="Every glass is judged at this thickness. Catalogs list internal "
         "transmittance at different thicknesses (SCHOTT 25 mm, most others "
         "10 mm, some 1-3 mm); each sample is converted to this one by "
         "Beer-Lambert, T_d = T_listed ** (d / d_listed), and labelled as "
         "scaled.")
with st.sidebar.expander("Crystal / n-k based transmission"):
    st.caption(
        "Crystals and semiconductors publish measured n and k rather than a "
        "manufacturer transmittance curve. For those, GlassMatch computes "
        "transmission from Fresnel reflection plus Beer-Lambert absorption at "
        "the sample thickness above. It is **calculated**, and it depends on "
        "that thickness.")
d_lo2, d_hi2 = st.sidebar.slider("Density range (g/cm^3, optional filter)", 1.5, 6.0, (1.5, 6.0), 0.05)
use_density = st.sidebar.checkbox("Filter by density", value=False)
cte_max = st.sidebar.slider("Max CTE (1e-6/K, optional filter)", 0.0, 20.0, 20.0, 0.1)
use_cte = st.sidebar.checkbox("Filter by CTE", value=False)
use_dndt = st.sidebar.checkbox(
    "Limit |dn/dT| (athermal designs)", value=False,
    help="Absolute dn/dT at the d line, +20/+40 C: manufacturer figures where "
         "published, otherwise calculated from the catalog's TD coefficients. "
         "Glasses above the limit are removed; glasses with no thermal data "
         "are kept and flagged unless 'Require available data' is on.")
dndt_max = st.sidebar.slider("Max |dn/dT| (1e-6/K)", 0.0, 15.0, 3.0, 0.1,
                             disabled=not use_dndt)
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
                "cte_min": None, "cte_max": cte_max if use_cte else None,
                "dndt_abs_max": dndt_max if use_dndt else None}
# Transmission precedence (manufacturer -> tabulated n/k -> Fresnel) lives in
# glassmatch.transmission so it is importable and testable without Streamlit.


def band_transmission(gid, lo_um, hi_um, mode):
    """(value_pct | None, basis label) for this app's current state.

    Thin adapter: the chain itself takes its state as arguments so tests can
    pass synthetic groups; here it is bound to what the UI is holding.
    """
    return _band_transmission(db, gid, lo_um, hi_um, mode,
                              t_groups=t_groups, nk_groups=nk_groups,
                              thickness_mm=sample_thickness_mm)


trans, trans_basis = {}, {}
for gid in summary["glass_id"]:
    v, basis = band_transmission(gid, wl_min_um, wl_max_um, t_mode)
    trans[gid] = v
    trans_basis[gid] = basis

# Materials with no catalog n_d (crystals) are judged on n at the chosen
# reference wavelength instead. Their V_d stays not-applicable, so the Abbe
# weight moves to index + transmission the same way it already does for IR
# glasses.
nd_override = {}
for _, _r in summary.iterrows():
    if _r.get("nd") is not None and _r.get("nd") == _r.get("nd"):
        continue
    _v, _kind = db.n_at(str(_r["glass_id"]), n_ref_nm)
    if _v is not None:
        nd_override[str(_r["glass_id"])] = _v

results = match_glasses(summary, requirements, w_in, transmissions=trans,
                        require_data=require_data, nd_override=nd_override)
n_excluded = int(results.attrs.get("excluded_count", 0))
excluded_examples = results.attrs.get("excluded_examples", [])

tabs = st.tabs(["Matching Glasses", "Glass Map", "Pair Finder",
                "Glass Detail", "Spectral Analysis",
                "Comparison", "Database Explorer", "Data Sources",
                "Import / Export"])

with tabs[0]:
    st.header("Matching glasses")
    st.caption("Compatibility Score = weighted requirement match (never 'best glass').")
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
    show["transmission_%"] = show["glass_id"].map(
        lambda g: None if trans.get(g) is None else round(trans[g], 1))
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
    st.dataframe(show[["glass", "manufacturer", "compatibility", "nd", "vd", "density",
                        "cte", "dn_dt", "transmission_%", "completeness", "missing",
                        "class"]],
                 width="stretch", hide_index=True)
    if nd_override and (scoped["nd_basis"] == "n at reference wavelength").any():
        n_ov = int((scoped["nd_basis"] == "n at reference wavelength").sum())
        st.caption(
            f"The **n** column is a catalog n_d for {len(scoped) - n_ov} of these "
            f"results, and n at {n_ref_nm:g} nm for {n_ov} material(s) that have "
            f"no d-line entry (crystals). V_d is shown blank for those because "
            f"the Abbe number is not defined for them.")
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
            "- IR materials and crystals: V_d weight moves to index (60%) + "
            "transmission (40%); V_d is shown as n/a, never scored. Crystals "
            "are judged on n at the reference wavelength.\n"
            f"- Transmission modes (**{t_mode}**): *Average* = mean of samples in "
            "band; *Minimum* = worst sample; *Entire range* = worst sample but only "
            "when manufacturer samples span >=90% of the band — otherwise the value "
            "is reported missing, never guessed.\n"
            "- Transmission values prefer manufacturer IT rows (transmission.csv); "
            "a calculated uncoated Fresnel estimate is used only when a glass has no "
            "manufacturer rows at all, and is labelled as calculated.")
with tabs[1]:
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

with tabs[2]:
    st.header("Pair finder (achromatic doublet)")
    st.caption("Thin lenses in contact, total power φ: "
               "φ1 = φ·V1/(V1−V2), φ2 = −φ·V2/(V1−V2); "
               "secondary spectrum ∝ (P1−P2)/(V1−V2); thermo-optic "
               "coefficient γ = (dn/dT)/(n_d−1) − α. Every number here "
               "is **calculated** - a starting point for design, never a manufacturer "
               "recommendation.")
    pf_rank = st.radio("Rank by", ["Low element powers", "Low secondary spectrum",
                                   "Apochromat candidates", "Athermal (mount CTE)"],
                       horizontal=True, key="pf_rank")
    pf_key = {"Low element powers": "power", "Low secondary spectrum": "secondary",
              "Apochromat candidates": "apo", "Athermal (mount CTE)": "athermal"}[pf_rank]
    pc1, pc2, pc3, pc4 = st.columns(4)
    pf_f = pc1.number_input("Doublet focal length (mm)", 1.0, 100000.0, 100.0, 10.0,
                            key="pf_f")
    pf_min_dv = pc2.number_input("Min V1 − V2", 1.0, 80.0, 10.0, 1.0, key="pf_min_dv",
                                 help="Pairs closer in V_d need very strong elements.")
    pf_mount = pc3.number_input("Mount CTE (1e-6/K)", -5.0, 60.0, 23.6, 0.1,
                                key="pf_mount", help="23.6 aluminium, 17.3 stainless "
                                                     "303, 8.6 titanium, 1.2 Invar.",
                                disabled=pf_key != "athermal")
    pf_top = pc4.number_input("Pairs shown", 10, 2000, 200, 10, key="pf_top")
    if pf_key == "apo":
        ac1, ac2 = st.columns(2)
        pf_apo_dp = ac1.number_input("Max |P1 − P2|", 0.0001, 0.05, 0.003, 0.0005,
                                     format="%.4f", key="pf_apo_dp")
        pf_apo_dv = ac2.number_input("Min V1 − V2 for apochromats", 1.0, 80.0, 20.0,
                                     1.0, key="pf_apo_dv")
    else:
        pf_apo_dp, pf_apo_dv = 0.003, 20.0
    with st.expander("Which glasses are paired", expanded=False):
        fc1, fc2 = st.columns(2)
        pf_makers = fc1.multiselect("Makers", sorted(gtable["manufacturer"].unique()),
                                    default=sorted(gtable["manufacturer"].unique()),
                                    key="pf_makers")
        _classes = sorted(gtable["material_class"].unique())
        pf_classes = fc2.multiselect("Material classes", _classes,
                                     default=[c for c in _classes
                                              if c in ("oxide_glass", "moldable")]
                                     or _classes, key="pf_classes")
        pf_obsolete = st.checkbox("Include obsolete glasses", value=False,
                                  key="pf_obsolete")
        pf_trans = st.checkbox(
            f"Only glasses meeting the sidebar transmission requirement "
            f"({t_min:g}% {t_mode.lower()}, {wl_min:g}-{wl_max:g} {wl_unit}, "
            f"{sample_thickness_mm:g} mm)", value=False, key="pf_trans",
            help="Glasses with no transmission data are kept unless 'Require "
                 "available data' is on.")
        pf_min_score = st.slider("Minimum compatibility score (sidebar requirements)",
                                 0.0, 100.0, 0.0, 1.0, key="pf_min_score",
                                 help="0 pairs every glass; raise it to pair only "
                                      "glasses that fit the sidebar's n_d, V_d, "
                                      "density, CTE and dn/dT requirements.")
    # The pool starts from the match results, so the sidebar's hard filters
    # (|dn/dT| limit, "Require available data") already apply.
    pf_ok = results[results["compatibility"] >= pf_min_score]["glass_id"]
    pool_t = gtable[gtable["glass_id"].isin(set(pf_ok))
                    & gtable["manufacturer"].isin(pf_makers)
                    & gtable["material_class"].isin(pf_classes)]
    if not pf_obsolete:
        pool_t = pool_t[pool_t["status"] != "obsolete"]
    if pf_trans:
        def _t_ok(g):
            v = trans.get(g)
            return (not require_data) if v is None else v >= t_min
        pool_t = pool_t[pool_t["glass_id"].map(_t_ok)]
    pairs_df = gpairs.find_pairs(pool_t, sort_by=pf_key, top=int(pf_top),
                                 min_dv=pf_min_dv,
                                 mount_cte=pf_mount if pf_key == "athermal" else None,
                                 apo_dp_max=pf_apo_dp, apo_min_dv=pf_apo_dv)
    st.caption(f"{len(pool_t):,} glasses in the pool → "
               f"{pairs_df.attrs.get('n_pairs', 0):,} pairs with V1 − V2 ≥ "
               f"{pf_min_dv:g}; {pairs_df.attrs.get('n_ranked', 0):,} have the data "
               f"this ranking needs. Showing the top {len(pairs_df):,}.")
    if pairs_df.empty:
        st.info("No pairs for these settings - widen the filters.")
    else:
        pv = pairs_df.copy()
        pv["f1_mm"] = pf_f / pv["phi1"]
        pv["f2_mm"] = pf_f / pv["phi2"]
        pv_cols = ["crown", "crown_maker", "flint", "flint_maker", "V1", "V2",
                   "phi1", "phi2", "f1_mm", "f2_mm", "sum_abs_power",
                   "P1", "P2", "dP", "secondary_spectrum"]
        if pf_key == "athermal":
            pv_cols += ["gamma1", "gamma2", "focal_drift", "thermal_residual"]
        st.dataframe(pv[pv_cols].round(5), width="stretch", hide_index=True)
        st.caption(
            "φ1, φ2 in units of the total power; f1, f2 = element focal "
            "lengths for the focal length above. P = P_g,F calculated from the "
            "verified fit; secondary_spectrum ≈ g-F focal shift / f. "
            + ("γ in 1e-6/K from absolute dn/dT (d line, +20/+40 C; "
               "manufacturer or calculated from TD coefficients) and catalog CTE; "
               "focal_drift = (1/f)·df/dT, thermal_residual = focal_drift "
               "− mount CTE (0 = athermal). " if pf_key == "athermal" else "")
            + "Basis: " + gpairs.PAIR_BASIS + ".")
        st.download_button("Export pairs CSV", pv.to_csv(index=False).encode(),
                           "glassmatch_pairs.csv", "text/csv", key="dl_pairs")
        pick = st.selectbox(
            "Show a pair on the partial-dispersion diagram", range(len(pv)),
            format_func=lambda k: f"{pv['crown'].iloc[k]} ({pv['crown_maker'].iloc[k]})"
                                  f" + {pv['flint'].iloc[k]} ({pv['flint_maker'].iloc[k]})",
            key="pf_pick")
        st.plotly_chart(partial_dispersion_figure(
            pool_t, pair=(pv["crown_id"].iloc[pick], pv["flint_id"].iloc[pick]),
            height=520), width="stretch")

with tabs[3]:
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
    with st.expander("Score breakdown"):
        hit = results[results["glass_id"] == gid]
        if not hit.empty:
            r0 = hit.iloc[0]
            st.plotly_chart(score_breakdown_figure(
                {k: (None if pd.isna(r0[f"score_{k}"]) else float(r0[f"score_{k}"]) / 100)
                 for k in WEIGHT_KEYS}), width="stretch")
    st.subheader("Cross-manufacturer substitutions")
    cur = curated_equivalents(db.equivalents, gid)
    cand = candidates_for(summary, gid, EquivalencyCriteria(), max_results=8)
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
with tabs[4]:
    st.header("Spectral analysis")
    pool = scoped["glass_id"].tolist() if len(scoped) else results["glass_id"].tolist()
    sel = st.multiselect("Glasses on plot (max 8 for readability)", pool,
                         default=pool[:3], max_selections=8)
    wls = np.linspace(max(wl_min_um, 0.30), min(max(wl_max_um, 0.31), 2.5), 60)
    dcurves, tcurves = {}, {}
    non_sell, t_manufacturer, t_calculated, t_missing = [], [], [], []
    tabulated = []
    for g in sel:
        # --- transmission: manufacturer rows preferred, Fresnel fallback ---
        tdf = t_groups.get(str(g))
        if tdf is not None and len(tdf) >= 2:
            # Converted to the sidebar's sample thickness, like the matching
            # table; samples with no usable listed thickness are left out.
            scaled = scale_internal_transmittance(
                tdf["transmission"], tdf["thickness_mm"], sample_thickness_mm)
            listed = sorted({float(x) for x in tdf["thickness_mm"].dropna()
                             if x > 0})
            listed_s = "/".join(f"{x:g}" for x in listed)
            basis = (f"manufacturer IT, {listed_s} mm as listed"
                     if listed == [float(sample_thickness_mm)] else
                     f"manufacturer IT, scaled from {listed_s} mm to "
                     f"{sample_thickness_mm:g} mm")
            curve = pd.DataFrame({"wavelength_um": tdf["wavelength_um"],
                                  "transmission_pct": scaled * 100.0,
                                  "data_type": basis}).dropna()
            if len(curve):
                tcurves[g] = curve
                t_manufacturer.append(g)
            else:
                t_missing.append(g)
        elif db.dispersion_status(g) == "sellmeier1":
            c = db.sellmeier_for(g, sellmeier_only=True)
            df = dispersion_curve(c, list(wls), *db.dispersion_range(g, c))
            tcurves[g] = pd.DataFrame({"wavelength_um": df["wavelength_um"],
                                       "transmission_pct": df["n"].map(
                                           lambda n: fresnel_transmission(n) * 100),
                                       "data_type": "calculated (Fresnel, uncoated)"})
            t_calculated.append(g)
        else:
            t_missing.append(g)
        # --- dispersion: verified Sellmeier fits, or tabulated crystal n ---
        status = db.dispersion_status(g)
        tab = db.spectral_nk_for(g)
        if tab is not None and len(tab.dropna(subset=["n"])) >= 2:
            # Crystal page with a measured table: plot the source samples
            # themselves rather than a fit, and label them as such.
            npts = tab.dropna(subset=["n"]).copy()
            dcurves[g] = pd.DataFrame({
                "wavelength_um": npts["wavelength_um"], "n": npts["n"]})
            if g in t_missing:
                tcurves[g] = pd.DataFrame({
                    "wavelength_um": npts["wavelength_um"],
                    "transmission_pct": npts["n"].map(
                        lambda n: fresnel_transmission(n) * 100),
                    "data_type": "calculated (Fresnel, uncoated, from tabulated n)"})
                t_calculated.append(g)
                t_missing.remove(g)
            tabulated.append(g)
            continue
        if status != "sellmeier1":
            non_sell.append(g)
            continue
        c = db.sellmeier_for(g, sellmeier_only=True)
        dcurves[g] = dispersion_curve(c, list(wls), *db.dispersion_range(g, c))
    if non_sell:
        st.warning("Dispersion curve unavailable for these glasses - none "
                   "has a dispersion fit verified against the catalog n(d) "
                   "and V_d, so GlassMatch never evaluates one: "
                   + ", ".join(non_sell))
    if t_missing:
        st.info("No transmission data for: " + ", ".join(t_missing))
    if dcurves:
        st.plotly_chart(dispersion_figure(dcurves, "nm" if wl_unit == "nm" else "um"),
                        width="stretch")
        if tabulated:
            st.caption(
                f"Tabulated source measurements: {len(tabulated)} material(s) - "
                "plotted verbatim, no fit. Remaining traces are CALCULATED from "
                "the catalog dispersion formula, not manufacturer tables, and "
                "are not drawn outside the fit's stated wavelength range.")
        else:
            st.caption("CALCULATED from each catalog's dispersion formula "
                       "(Sellmeier, Schott, Extended ...) - not manufacturer "
                       "tables, and not drawn outside the fit's stated "
                       "wavelength range.")
        if tabulated:
            st.info("Tabulated n(λ) samples span a wider range than the glass "
                    "window above; the plot uses each material's own measured "
                    "wavelengths.")
    if tcurves:
        st.plotly_chart(transmission_figure(tcurves, "nm" if wl_unit == "nm" else "um",
                                            band=(wl_min_um, wl_max_um)),
                        width="stretch")
        st.caption(
            f"Manufacturer IT rows: {len(t_manufacturer)} glass(es); "
            f"calculated uncoated Fresnel: {len(t_calculated)} glass(es) — "
            "each trace is labelled by basis. Manufacturer internal "
            f"transmittance is converted to {sample_thickness_mm:g} mm "
            "(Beer-Lambert) from the thickness each catalog lists.")
with tabs[5]:
    st.header("Comparison (2-5 glasses)")
    comp = st.multiselect("Select glasses", results["glass_id"].tolist(),
                          default=results["glass_id"].tolist()[:2], max_selections=5)
    if len(comp) >= 2:
        st.dataframe(results[results["glass_id"].isin(comp)].set_index("glass_id")
                     .astype(str).T, width="stretch")
    else:
        st.info("Select at least 2 glasses.")

with tabs[6]:
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
    crit = EquivalencyCriteria(
        tolerance_overrides={"nd": tol_nd, "vd": tol_vd, "density": tol_rho})
    with st.spinner("Computing candidates..."):
        pairs = candidate_pairs(summary, crit)
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

with tabs[7]:
    st.header("Data sources and licensing")
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

with tabs[8]:
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




