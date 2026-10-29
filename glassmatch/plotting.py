"""Plotly figures. Every figure labels data_type (manufacturer vs calculated)."""
from __future__ import annotations
import plotly.graph_objects as go


def dispersion_figure(curves: dict, wl_unit: str = "nm") -> go.Figure:
    fig = go.Figure()
    for label, df in curves.items():
        x = df["wavelength_um"] * (1000.0 if wl_unit == "nm" else 1.0)
        dtype = df["data_type"].iloc[0] if "data_type" in df.columns and len(df) else "unknown"
        fig.add_trace(go.Scatter(x=x, y=df["n"], mode="lines+markers",
                                 name=f"{label} ({dtype})"))
    fig.update_layout(title="Refractive index vs wavelength",
                      xaxis_title=f"Wavelength ({wl_unit})",
                      yaxis_title="Refractive index n",
                      template="plotly_white", height=430)
    return fig


def transmission_figure(curves: dict, wl_unit: str = "nm",
                        band: tuple | None = None) -> go.Figure:
    fig = go.Figure()
    for label, df in curves.items():
        x = df["wavelength_um"] * (1000.0 if wl_unit == "nm" else 1.0)
        dtype = df["data_type"].iloc[0] if "data_type" in df.columns and len(df) else "unknown"
        fig.add_trace(go.Scatter(x=x, y=df["transmission_pct"], mode="lines+markers",
                                 name=f"{label} ({dtype})"))
    if band:
        lo, hi = band
        if wl_unit == "nm":
            lo, hi = lo * 1000.0, hi * 1000.0
        fig.add_vrect(x0=lo, x1=hi, fillcolor="LightSkyBlue", opacity=0.25,
                      line_width=0, annotation_text="requirement band")
    fig.update_layout(title="Transmission vs wavelength",
                      xaxis_title=f"Wavelength ({wl_unit})",
                      yaxis_title="Transmission (%)",
                      template="plotly_white", height=430)
    return fig


def score_breakdown_figure(scores: dict) -> go.Figure:
    keys = [k for k in scores if k != "overall" and scores[k] is not None]
    fig = go.Figure(go.Bar(x=keys, y=[scores[k] * 100 for k in keys]))
    fig.update_layout(title="Compatibility breakdown (%)",
                      yaxis_title="Score (%)", yaxis_range=[0, 100],
                      template="plotly_white", height=320)
    return fig


def _maker_traces(fig, table, y: str, hover_extra, highlight: set):
    for maker, grp in table.groupby("manufacturer", sort=True):
        fig.add_trace(go.Scattergl(
            x=grp["vd"], y=grp[y], mode="markers", name=str(maker),
            marker=dict(size=6, opacity=0.75),
            text=grp["glass"], customdata=hover_extra(grp),
            hovertemplate="<b>%{text}</b> (" + str(maker) + ")<br>"
                          "V_d %{x:.2f}<br>%{customdata}<extra></extra>"))
    hit = table[table["glass_id"].isin(highlight)]
    if len(hit):
        fig.add_trace(go.Scatter(
            x=hit["vd"], y=hit[y], mode="markers", name="current match results",
            marker=dict(size=14, symbol="circle-open", color="#d6336c",
                        line=dict(width=2.5)),
            text=hit["glass"], hoverinfo="text"))


def glass_map_figure(table, highlight=(), height: int = 620) -> go.Figure:
    """n_d vs V_d (Abbe diagram), coloured by maker, V_d decreasing to the
    right as on manufacturer glass maps. Catalog values (manufacturer)."""
    t = table.dropna(subset=["nd", "vd"])
    fig = go.Figure()
    _maker_traces(fig, t, "nd",
                  lambda g: [f"n_d {n:.5f} (manufacturer)" for n in g["nd"]],
                  set(highlight))
    fig.update_layout(title="Glass map: n_d vs V_d (catalog values)",
                      xaxis_title="Abbe number V_d", yaxis_title="Refractive index n_d",
                      xaxis_autorange="reversed", template="plotly_white",
                      height=height, legend_title="Maker")
    return fig


def partial_dispersion_figure(table, highlight=(), pair=None,
                              height: int = 620) -> go.Figure:
    """P_g,F vs V_d with the normal line. P_g,F is CALCULATED from each
    glass's verified dispersion fit; `pair` = (crown_id, flint_id) draws the
    chosen doublet's tie line."""
    from glassmatch.pairs import NORMAL_LINE_LABEL, normal_line_pgf
    t = table.dropna(subset=["pgf", "vd"])
    fig = go.Figure()

    def _hover(g):
        out = []
        for p, dc, dm in zip(g["pgf"], g["dpgf_calc"], g["dpgf_mfr"]):
            s = f"P_g,F {p:.4f} (calculated)<br>dPgF {dc:+.4f} vs normal line (calculated)"
            if dm == dm:
                s += f"<br>dPgF {dm:+.4f} (manufacturer, own normal line)"
            out.append(s)
        return out

    _maker_traces(fig, t, "pgf", _hover, set(highlight))
    if len(t):
        xs = [float(t["vd"].min()) - 2, float(t["vd"].max()) + 2]
        fig.add_trace(go.Scatter(x=xs, y=list(normal_line_pgf(xs)), mode="lines",
                                 name=NORMAL_LINE_LABEL,
                                 line=dict(color="grey", dash="dash")))
    if pair is not None:
        hit = t.set_index("glass_id").reindex(list(pair)).dropna(subset=["pgf"])
        if len(hit) == 2:
            fig.add_trace(go.Scatter(x=hit["vd"], y=hit["pgf"], mode="lines+markers",
                                     name="selected pair",
                                     marker=dict(size=12, color="red"),
                                     line=dict(color="red", width=2)))
    fig.update_layout(title="Partial dispersion: P_g,F vs V_d "
                            "(P_g,F calculated from verified dispersion fits)",
                      xaxis_title="Abbe number V_d", yaxis_title="P_g,F (calculated)",
                      xaxis_autorange="reversed", template="plotly_white",
                      height=height, legend_title="Maker")
    return fig
