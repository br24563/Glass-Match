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

    c1, c2 = st.columns(2)
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
                     allow_cte_extrapolation=allow_x)
    if a["reason"]:
        st.error(f"Cannot trace this design: {a['reason']}")
        return
    m = st.columns(4)
    m[0].metric("EFL (d)", f"{a['efl']:.4f} mm")
    m[1].metric("BFL (d)", f"{a['bfl']:.4f} mm")
    m[2].metric("Axial colour F−C", _fmt(a["axial_colour"]))
    m[3].metric("Secondary spectrum d−(F+C)/2", _fmt(a["secondary_spectrum"]))
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
    c1, c2, c3 = st.columns(3)
    tol_nd = c1.number_input("± n_d window", 0.001, 0.2, 0.03, 0.005, key="rx_nd")
    tol_vd = c2.number_input("± V_d window", 0.5, 30.0, 8.0, 0.5, key="rx_vd")
    opts = [None] + list(range(len(rx.surfaces)))
    resolve = c3.selectbox("Re-solve curvature to keep EFL", opts,
                           format_func=lambda i: "none (keep all curvatures)"
                           if i is None else f"surface {i + 1}", key="rx_res")
    base, df = lens.replacement_candidates(
        db, rx, old, tol_nd=tol_nd, tol_vd=tol_vd, resolve_surface=resolve,
        t_c=t_c, mount_cte=mount, max_results=25,
        allow_cte_extrapolation=allow_x, include_mirrors=ctx.include_mirrors)
    if df.empty:
        st.info("No available glass within these windows"
                + ("" if resolve is not None else
                   " keeps the EFL within 1 %; try re-solving a surface") + ".")
        return
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "colour_change_mm": st.column_config.NumberColumn(
            "colour change (mm)", help="Worst change, over F, C and g, of "
            "that line's focus relative to the d-line focus", format="%.5f"),
        "efl_change_pct": st.column_config.NumberColumn("EFL change (%)",
                                                         format="%.4f"),
        "thermal_shift_change_mm": st.column_config.NumberColumn(
            f"Δ thermal shift at {t_c:g} °C (mm)", format="%.5f")})
    st.caption("Sorted by colour change. All figures are paraxial and "
               "CALCULATED from catalog indices, dn/dT and CTE; candidates "
               "without an index at a needed line are left out, never "
               "approximated.")
    st.download_button("Download ranking (CSV)", df.to_csv(index=False).encode(),
                       "glass_replacements.csv", "text/csv")
