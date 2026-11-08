"""Lens Glass Replacement tab: read a prescription, first-order figures,
and ranked replacements for a glass (paraxial screening only)."""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import streamlit as st

from glassmatch import lens

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "examples" / "doublet.json"


def _fmt(v, unit="mm", digits=5):
    return "n/a" if v is None or v != v else f"{v:+.{digits}f} {unit}"


def render(ctx):
    db = ctx.db
    st.header("Lens glass replacement (first-order screening)")
    st.caption("Reads a prescription (JSON, CSV, Zemax .zmx, CODE V .seq), "
               "traces it paraxially and ranks available glasses to replace "
               "one of its glasses, keeping every curvature (or re-solving "
               "one to keep the focal length). This is a first-order screen: "
               "it does not see spherical aberration, coma, astigmatism, "
               "distortion or lateral colour - check any replacement in an "
               "optical design program.")
    up = st.file_uploader("Prescription file", type=["json", "csv", "zmx", "seq"],
                          key="rx_file")
    try:
        if up is not None:
            data = up.getvalue()
            text = (data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff")
                    else data.decode("utf-8-sig", errors="replace"))
            rx = lens.read_prescription(db, up.name, text=text)
        else:
            st.caption(f"No file uploaded - showing the example in "
                       f"docs/examples/{EXAMPLE.name}.")
            rx = lens.read_prescription(db, EXAMPLE)
    except (lens.PrescriptionError, ValueError, KeyError) as e:
        st.error(f"Cannot read the prescription: {e}")
        return
    status = dict(zip(db.glasses["glass_id"], db.glasses["status"]))
    st.dataframe(pd.DataFrame([{
        "surface": i + 1, "radius (mm)": (None if math.isinf(s.radius) else s.radius),
        "thickness (mm)": s.thickness, "glass after": s.material or "air",
        "as written": s.label, "status": status.get(s.material, "")
        if s.material else "", "stop": "yes" if rx.stop == i else ""}
        for i, s in enumerate(rx.surfaces)]), width="stretch", hide_index=True)

    from glassmatch import band as gm_band
    c0, c1, c2 = st.columns(3)
    band_name = c0.selectbox(
        "Design band", list(gm_band.PRESETS), key="rx_band",
        help="The wavelengths the lens is traced at. Visible: d (primary), "
             "F, C and g. Another band: its middle wavelength is primary and "
             "its short and long ends give the axial colour - pick MWIR or "
             "LWIR for an infrared design.")
    tri = None if band_name.startswith("Visible") else gm_band.PRESETS[band_name]
    line = tri[1] if tri else "d"
    if tri is None:
        lab_p, lab_ax, lab_sec = "d", "F−C", "d−(F+C)/2"
    else:
        _s, _m, _l = (f"{w / 1000:g}" for w in tri)
        lab_p, lab_ax, lab_sec = f"{_m} µm", f"{_s}−{_l} µm", f"{_m}−({_s}+{_l})/2 µm"
    t_c = c1.number_input("Thermal check: temperature (°C)", -100.0, 140.0,
                          60.0, 5.0, key="rx_t")
    mount = c2.number_input("Mount CTE (1e-6/K; 23.6 = Al 6061, 17.3 = "
                            "stainless 304)", 0.0, 100.0, 23.6, key="rx_mount")
    allow_x = False
    if not (lens.CTE_RANGE[0] <= t_c <= lens.CTE_RANGE[1]):
        allow_x = st.checkbox(
            "Extrapolate the catalog CTEs linearly outside −30/+70 °C "
            "(labelled estimate)", key="rx_allow_x",
            help="Catalog CTEs are means over −30/+70 °C; glass expansion is "
                 "not linear far outside it, so by default no thermal shift "
                 "is given there.")
    a = lens.analyse(db, rx, t_c=t_c, mount_cte=mount,
                     allow_cte_extrapolation=allow_x, band=tri)
    if a["reason"]:
        st.error(f"Cannot trace this design: {a['reason']}"
                 + (" - for an infrared design choose MWIR or LWIR as the "
                    "design band." if tri is None else ""))
        return
    m = st.columns(4)
    m[0].metric(f"EFL ({lab_p})", f"{a['efl']:.4f} mm")
    m[1].metric(f"BFL ({lab_p})", f"{a['bfl']:.4f} mm")
    m[2].metric(f"Axial colour {lab_ax}", _fmt(a["axial_colour"]))
    m[3].metric(f"Secondary spectrum {lab_sec}", _fmt(a["secondary_spectrum"]))
    th = a["thermal"]
    if th["reason"]:
        st.warning(f"Thermal focus shift unavailable: {th['reason']}")
    else:
        st.write(f"Thermal focus shift 20 → {t_c:g} °C with this mount: "
                 f"**{_fmt(th['focus_shift'])}** (EFL change "
                 f"{_fmt(th['efl_change'])}).")
        for n in th["notes"]:
            (st.warning if n.startswith("EXTRAPOLATED") else st.caption)(n)

    st.subheader("Rank replacements")
    glasses = rx.glasses()
    obsolete = [g for g in glasses if status.get(g) == "obsolete"]
    old = st.selectbox("Glass to replace", obsolete + [g for g in glasses
                                                       if g not in obsolete],
                       format_func=lambda g: f"{g} [{status.get(g, '')}]",
                       key="rx_old")
    modes = {"Keep each replaced element's power (recommended)": "element",
             "Keep every curvature": "curvatures",
             "Re-solve one surface for the system EFL": "efl"}
    mode = modes[st.radio(
        "How the design adapts", list(modes), key="rx_mode",
        help="Element power: the replaced element is re-shaped so its own "
             "focal length is unchanged (both curvatures scaled for an "
             "element in air, which keeps its shape; the air-side surface "
             "re-solved for a cemented element), so ray heights on the "
             "elements after it barely move. EFL re-solve restores the "
             "system focal length but can move every downstream ray.")]
    c1, c2, c3 = st.columns(3)
    tol_nd = c1.number_input("± n window" if tri else "± n_d window", 0.001,
                             0.5, 0.03, 0.005, key="rx_nd")
    if tri is None:
        tol_vd = c2.number_input("± V_d window", 0.5, 30.0, 8.0, 0.5, key="rx_vd")
        tol_v_pct = 25.0
    else:
        tol_vd = 8.0
        tol_v_pct = c2.number_input("± V_band window (%)", 1.0, 100.0, 25.0, 1.0,
                                    key="rx_vpct",
                                    help="V_band spans ~5 to ~2000 in the IR, so "
                                         "the window is relative.")
    resolve = None
    if mode == "efl":
        resolve = c3.selectbox("Surface to re-solve",
                               list(range(len(rx.surfaces))),
                               format_func=lambda i: f"surface {i + 1}",
                               key="rx_res")
    base, df = lens.replacement_candidates(
        db, rx, old, tol_nd=tol_nd, tol_vd=tol_vd, resolve_surface=resolve,
        t_c=t_c, mount_cte=mount, max_results=25,
        allow_cte_extrapolation=allow_x, include_mirrors=ctx.include_mirrors,
        mode=mode, band=tri, tol_v_pct=tol_v_pct)
    if df.empty:
        st.info("No available glass within these windows"
                + ("" if mode == "efl" else " keeps the EFL within 1 %")
                + "; widen the windows or change how the design adapts.")
        return
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "colour_change_mm": st.column_config.NumberColumn(
            "colour change (mm)", help="Worst change, over the other lines, "
            "of each line's focus relative to the primary line's focus",
            format="%.5f"),
        "efl_change_pct": st.column_config.NumberColumn("EFL change (%)",
                                                         format="%.4f"),
        "ray_height_change_pct": st.column_config.NumberColumn(
            "ray-height change (%)", help="Largest change of the paraxial "
            "marginal ray height on any surface, as % of the largest height: "
            "how far the rest of the lens is disturbed", format="%.4f"),
        "petzval_change": st.column_config.NumberColumn(
            "Petzval change (1/mm)", format="%.2e"),
        "thermal_shift_change_mm": st.column_config.NumberColumn(
            f"Δ thermal shift at {t_c:g} °C (mm)", format="%.5f")})
    st.caption("Sorted by colour change. All figures are paraxial and "
               "CALCULATED from catalog indices, dn/dT and CTE; candidates "
               "without an index at a needed line are left out, never "
               "approximated.")
    st.download_button("Download ranking (CSV)", df.to_csv(index=False).encode(),
                       "glass_replacements.csv", "text/csv")

    st.subheader("Write the modified design")
    pick = st.selectbox("Replacement", df["glass_id"].tolist(), key="rx_pick")
    new_rx, note = lens.replace_glass(db, rx, old, pick, mode,
                                      resolve_surface=resolve,
                                      target_efl=base["efl"], line=line)
    if new_rx is None:
        st.warning(f"Cannot build the design with {pick}: {note}")
        return
    src_fmt = (rx.source or {}).get("fmt")
    fmts = ([src_fmt] if src_fmt in ("zmx", "seq") else []) + ["json"]
    out_fmt = st.radio("Format", fmts, horizontal=True, key="rx_fmt",
                       help="The original .zmx / .seq is rewritten with only "
                            "the changed surfaces' curvature and glass lines "
                            "touched; everything else stays as it was.")
    try:
        text, ext, enc = lens.export_prescription(db, new_rx, out_fmt)
    except lens.PrescriptionError as e:
        st.warning(str(e))
        return
    changed = [i + 1 for i, (a_, b_) in enumerate(zip(rx.surfaces, new_rx.surfaces))
               if a_.material != b_.material or abs(a_.curvature - b_.curvature) > 1e-15]
    st.caption(f"{old} → {pick}: {note or 'curvatures kept'}. Surfaces changed: "
               f"{', '.join(map(str, changed))}.")
    st.download_button(f"Download modified design (.{ext})",
                       text.encode("utf-16" if enc == "utf-16" else "utf-8"),
                       f"{rx.name or 'design'}_{pick}.{ext}",
                       "application/octet-stream", key="rx_dl")
