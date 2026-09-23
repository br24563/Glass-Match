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
