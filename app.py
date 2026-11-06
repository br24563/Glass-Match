"""GlassMatch: open-source optical glass selection & material database."""
from __future__ import annotations
import pandas as pd
import streamlit as st

from glassmatch import __version__
from glassmatch import columns as gm_columns
from glassmatch.importers.agf import AVAILABLE_STATUSES as _AVAIL
from glassmatch.manifest import data_version as _data_version
from glassmatch.database import load_default_database, DEFAULT_DATA_DIR
from glassmatch.matching import DEFAULT_WEIGHTS, WEIGHT_KEYS, match_glasses
from glassmatch.transmission import band_transmission as _band_transmission
from glassmatch import pairs as gpairs
from glassmatch.validation import (validate_property_frame, validate_glass_frame,
                                   validate_transmission_frame,
                                   validate_spectral_nk_frame,
                                   orphan_source_ids,
                                   orphan_glass_ids,
                                   find_transmission_conflicts)
from glassmatch.equivalency import (EquivalencyCriteria, candidate_pairs,
                                    candidates_for)

st.set_page_config(page_title="GlassMatch", page_icon="🔭", layout="wide")

PRESETS = {
    "UV (0.30-0.40 um)": (0.30, 0.40), "Visible (0.40-0.70 um)": (0.40, 0.70),
    "NIR (0.70-1.40 um)": (0.70, 1.40), "SWIR (1.40-3.00 um)": (1.40, 3.00),
    "MWIR (3.00-5.00 um)": (3.00, 5.00), "LWIR (8.00-12.00 um)": (8.00, 12.00),
    "Custom": None,
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
    from glassmatch import cache as _cache
    quality = _cache.obj(db.cache_dir(), "quality", lambda: {
        "properties": validate_property_frame(db.properties),
        "glasses": validate_glass_frame(db.glasses),
        "transmission": validate_transmission_frame(db.transmission),
        "spectral_nk": validate_spectral_nk_frame(db.spectral_nk),
        "orphan_sources": orphan_source_ids(db.glasses, db.properties, db.sources),
        "orphan_glasses": orphan_glass_ids(db.properties, db.glasses),
    })
    quality["transmission_conflicts"] = _load_transmission_conflicts(db)
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
DATA_VERSION = _data_version(DEFAULT_DATA_DIR)
st.sidebar.caption(f"GlassMatch {__version__} - data {DATA_VERSION} "
                   "(see Data Sources)")


@st.cache_resource
def _glass_table(_key: str):
    """Per-glass n_d, V_d, P_g,F (calculated), dPgF and thermo-optic
    coefficient for the glass map and pair finder; built once per data set."""
    return _disk_frame("glass_table", lambda: gpairs.glass_table(
        summary, gpairs.partial_dispersion_table(db), db))


def _disk_frame(name, build):
    """A frame from the local derived-data cache (glassmatch.cache), so a new
    session with the same data and settings starts from stored results."""
    from glassmatch import cache as _c
    return _c.frame(db.cache_dir(), name, build)


def _disk_obj(name, build):
    from glassmatch import cache as _c
    return _c.obj(db.cache_dir(), name, build)


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
# More bands, each of which must ALSO be met (e.g. 400-700 nm and 9-10 um for
# a dual-band window). The transmission requirement and mode apply to every
# band; a glass's combined figure is its worst band.
with st.sidebar.expander("Additional wavelength bands (all must be met)"):
    n_extra_bands = int(st.number_input("Number of additional bands", 0, 4, 0,
                                        key="n_extra_bands"))
    extra_bands = []
    for _i in range(n_extra_bands):
        _c1, _c2 = st.columns(2)
        _lo = _c1.number_input(f"Band {_i + 2} min ({wl_unit})",
                               value=8.0 * factor, key=f"band{_i}_lo")
        _hi = _c2.number_input(f"Band {_i + 2} max ({wl_unit})",
                               value=12.0 * factor, key=f"band{_i}_hi")
        if _lo >= _hi:
            st.error(f"Band {_i + 2}: minimum must be < maximum; ignored.")
        else:
            extra_bands.append((_lo / factor, _hi / factor))
    if n_extra_bands:
        st.caption("The minimum transmission and its mode below apply to "
                   "every band. A glass passes only if it meets them in all "
                   "bands; its transmission figure is its worst band, and a "
                   "band with no data makes it missing, never assumed - tick "
                   "'Require available data' to drop glasses with no data "
                   "in a band (most oxide glasses have none past 2.5 um).")
bands = [(float(wl_min_um), float(wl_max_um))] + extra_bands

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
availability = st.sidebar.multiselect(
    "Availability", list(_AVAIL) + ["obsolete"], default=list(_AVAIL),
    help="From each maker's catalog: preferred = the maker's recommended "
         "line; standard; special / melt = special production; inquiry = "
         "available on request (SCHOTT inquiry glasses, OHARA special order); "
         "obsolete = no longer produced. HIKARI and the mirror-only makers "
         "publish no preferred class, so they are 'standard' unless obsolete.")
include_mirrors = st.sidebar.checkbox(
    "Include unverified mirrors (unknown date)", value=False,
    help="305 glasses (Corning, LZOS, RPO, the IR and polymer makers, some "
         "legacy CDGM) come only from a third-party mirror of unknown date: "
         "they may no longer be made, or made to these numbers. Hidden by "
         "default; shown with their data tier when included.")
require_data = st.sidebar.checkbox("Require available data (missing = fail)",
                                   value=False,
                                   help="If off, missing data is flagged, not failed.")

_COL_LABELS = gm_columns.labels()


def _col_label(c):
    lab, unit = _COL_LABELS.get(c, (c, ""))
    return f"{lab} [{unit}]" if unit else lab


with st.sidebar.expander("3 \u2022 More columns & filters"):
    st.caption("Every stored property plus figures GlassMatch calculates "
               "from them (marked 'calculated'). Columns marked \"maker's own "
               "scale\" are only comparable within one maker.")
    prop_wavelength_nm = st.number_input(
        "Wavelength for n, dn/d\u03bb, group index, GVD (nm)", 200.0, 20000.0,
        1064.0, 1.0)
    extra_cols = st.multiselect("Extra columns in results", list(_COL_LABELS),
                                format_func=_col_label)
    filter_cols = st.multiselect(
        "Range filters", [c for c in _COL_LABELS if c != "production_frequency"],
        format_func=_col_label,
        help="Glasses outside a range are removed; glasses with no value are "
             "kept and shown blank, unless 'Require available data' is on.")
    where = {}
    from glassmatch.database import MAKER_SCALE_COLUMNS as _MAKER_SCALE
    for _c in filter_cols:
        _maker = None
        if _c in _MAKER_SCALE:
            # Each maker's own test and scale: a range only means something
            # within one maker, so the filter keeps that maker's glasses only.
            _have = sorted(summary.loc[pd.to_numeric(summary[_c], errors="coerce")
                                       .notna(), "manufacturer_id"].astype(str)
                           .unique()) if _c in summary.columns else []
            if not _have:
                st.caption(f"No maker gives {_c}; filter ignored.")
                continue
            _maker = st.selectbox(f"{_c}: whose scale", _have, key=f"mk_{_c}",
                                  help="This class is each maker's own test "
                                       "and scale. The filter keeps only this "
                                       "maker's glasses inside the range.")
        _a, _b = st.columns(2)
        _lo = _a.number_input(f"min {_c}", value=None, key=f"lo_{_c}",
                              placeholder="no min")
        _hi = _b.number_input(f"max {_c}", value=None, key=f"hi_{_c}",
                              placeholder="no max")
        where[_c] = (_lo, _hi) + ((_maker,) if _maker else ())

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
                "dndt_abs_max": dndt_max if use_dndt else None,
                "wavelength_bands_um": bands}
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


@st.cache_data(show_spinner=False)
def _band_all(_key: str, lo_um: float, hi_um: float, mode: str,
              thickness_mm: float):
    """Band transmission for every glass; recomputed only when the band, mode
    or thickness changes, not on every widget interaction."""
    def build():
        vals, basis = {}, {}
        for g in summary["glass_id"]:
            vals[g], basis[g] = _band_transmission(
                db, g, lo_um, hi_um, mode, t_groups=t_groups,
                nk_groups=nk_groups, thickness_mm=thickness_mm)
        return {"v": vals, "b": basis}
    got = _disk_obj(f"band_{lo_um:g}_{hi_um:g}_{mode.replace(' ', '')}_"
                    f"{thickness_mm:g}", build)
    out_v, out_b = got["v"], got["b"]
    return out_v, out_b


band_results = [_band_all(_data_key(), lo, hi, str(t_mode),
                           float(sample_thickness_mm)) for lo, hi in bands]
if len(bands) == 1:
    trans, trans_basis = band_results[0]
else:
    from glassmatch.transmission import combine_bands as _combine_bands
    trans, trans_basis = {}, {}
    for _g in summary["glass_id"]:
        trans[_g], trans_basis[_g] = _combine_bands(
            [(lo, hi, v.get(_g), b.get(_g, "missing"))
             for (lo, hi), (v, b) in zip(bands, band_results)])

# Materials with no catalog n_d (crystals) are judged on n at the chosen
# reference wavelength instead. Their V_d stays not-applicable, so the Abbe
# weight moves to index + transmission the same way it already does for IR
# glasses.
def _nd_override_build():
    out = {}
    for gid, nd in zip(summary["glass_id"], summary["nd"]):
        if nd is not None and nd == nd:
            continue
        v, _kind = db.n_at(str(gid), n_ref_nm)
        if v is not None:
            out[str(gid)] = v
    return out


nd_override = _disk_obj(f"nd_override_{float(n_ref_nm):g}", _nd_override_build)

results = match_glasses(summary, requirements, w_in, transmissions=trans,
                        require_data=require_data, nd_override=nd_override)
_n_before, _attrs = len(results), dict(results.attrs)
results = results[results["status"].isin(availability)].reset_index(drop=True)     if availability else results.iloc[0:0]
n_unavailable = _n_before - len(results)
_n_before = len(results)
if not include_mirrors:
    results = results[results["data_tier"] != "unverified_mirror"].reset_index(drop=True)
results.attrs.update(_attrs)
n_mirror_hidden = _n_before - len(results)


@st.cache_data(show_spinner=False)
def _supply_map(_key: str) -> dict:
    from glassmatch.supply import supply_column
    return supply_column(summary)


supply_map = _supply_map(_data_key())
n_excluded = int(results.attrs.get("excluded_count", 0))
excluded_examples = results.attrs.get("excluded_examples", [])


@st.cache_data(show_spinner=False)
def _candidates_for(_key: str, gid: str):
    import re as _re
    return _disk_frame("cand_" + _re.sub(r"[^A-Za-z0-9_.-]", "_", gid),
                       lambda: candidates_for(summary, gid, EquivalencyCriteria(),
                                              max_results=8))


@st.cache_data(show_spinner=False)
def _candidate_pairs(_key: str, tol_nd: float, tol_vd: float, tol_rho: float):
    return _disk_frame(f"pairs_{tol_nd:g}_{tol_vd:g}_{tol_rho:g}",
                       lambda: candidate_pairs(summary, EquivalencyCriteria(
                           tolerance_overrides={"nd": tol_nd, "vd": tol_vd,
                                                "density": tol_rho})))


@st.cache_data(show_spinner="Computing derived properties…")
def _column_table(_key: str, thickness_mm: float, wavelength_nm: float):
    return _disk_frame(
        f"columns_{thickness_mm:g}_{wavelength_nm:g}",
        lambda: gm_columns.columns(db, summary, t_groups, thickness_mm,
                                   wavelength_nm).reset_index()
    ).set_index("glass_id")


col_table = _column_table(_data_key(), float(sample_thickness_mm),
                          float(prop_wavelength_nm))
n_range_filtered = 0
if where:
    _attrs = dict(results.attrs)
    _mask = gm_columns.range_filter(
        col_table.reindex(results["glass_id"]), where,
        keep_missing=not require_data,
        makers=results["manufacturer_id"].to_numpy())
    n_range_filtered = int((~_mask).sum())
    results = results[_mask.to_numpy()].reset_index(drop=True)
    results.attrs.update(_attrs)

@st.cache_data(show_spinner=False)
def _agf_export(glass_ids: tuple, data_key: str):
    from glassmatch.export_agf import export_agf
    ex = export_agf(db, glass_ids)
    return ex.to_bytes(), len(ex.exported), ex.skipped


@st.cache_data(show_spinner=False)
def _codev_export(glass_ids: tuple, data_key: str):
    from glassmatch.export_codev import export_codev
    text, exported, skipped = export_codev(db, glass_ids)
    return text.encode(), len(exported), skipped


def agf_download(glass_ids, key):
    """Zemax .agf (and CODE V private catalog) download for a selection,
    with what was left out."""
    cv, n_cv, _cv_skip = _codev_export(tuple(glass_ids), _data_key())
    st.download_button(f"Export CODE V private catalog (.seq, {n_cv} glasses)",
                       cv, "glassmatch_private.seq", "text/plain",
                       key=f"cv_{key}", disabled=not n_cv,
                       help="PRV block with each glass's index at the t, C, d, "
                            "e, F, g and h lines, calculated inside its "
                            "stated range; glasses that do not cover them all "
                            "are left out.")
    data, n_out, skipped = _agf_export(tuple(glass_ids), _data_key())
    st.download_button(f"Export Zemax catalog (.agf, {n_out} glasses)",
                       data, "glassmatch_selection.agf",
                       "application/octet-stream", key=f"agf_{key}",
                       disabled=not n_out)
    st.caption("The .agf contains manufacturer catalog data, written verbatim "
               "with its source and date in the header, for your own design "
               "work. Only verified dispersion fits are included.")
    if skipped:
        with st.expander(f"{len(skipped)} glass(es) not in the .agf"):
            st.dataframe(pd.DataFrame(skipped, columns=["glass_id", "reason"]),
                         width="stretch", hide_index=True)


tabs = st.tabs(["Matching Glasses", "Glass Map", "Pair Finder",
                "Glass Detail", "Spectral Analysis",
                "Comparison", "Lens Glass Replacement", "Database Explorer",
                "Data Sources", "Import / Export"])

# --- pages ----------------------------------------------------------------
# Each tab lives in glassmatch_app/pages/<name>.py as render(ctx); ctx
# carries every name the code above defines, exactly as the tabs used
# them when they were inline here.
import types as _types  # noqa: E402
from glassmatch_app import pages as _pages  # noqa: E402
from glassmatch_app.pages import (comparison, data_sources, explorer,  # noqa: E402,F401
                                  glass_detail, glass_map, import_export,
                                  lens_replace, matching, pair_finder,
                                  spectral)
_ctx = _types.SimpleNamespace(**{k: v for k, v in globals().items()
                                 if not k.startswith('__')})

with tabs[0]:
    _ctx.__dict__.update(_pages.matching.render(_ctx))
with tabs[1]:
    _pages.glass_map.render(_ctx)
with tabs[2]:
    _pages.pair_finder.render(_ctx)
with tabs[3]:
    _pages.glass_detail.render(_ctx)
with tabs[4]:
    _pages.spectral.render(_ctx)
with tabs[5]:
    _pages.comparison.render(_ctx)
with tabs[6]:
    _pages.lens_replace.render(_ctx)
with tabs[7]:
    _pages.explorer.render(_ctx)
with tabs[8]:
    _pages.data_sources.render(_ctx)
with tabs[9]:
    _pages.import_export.render(_ctx)
