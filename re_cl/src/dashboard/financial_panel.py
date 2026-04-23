"""
financial_panel.py
------------------
Streamlit financial analysis panel for RE_CL.

Sections:
  1. Cap Rate / Yield Calculator
  2. Análisis de Subvaloración
  3. DCF Simplificado (5 años)
  4. Escenarios (Pesimista / Base / Optimista)
  5. Punto de equilibrio

Usage (standalone):
    render_financial_panel()

Usage (with selected property):
    render_financial_panel(property_row=row_dict)
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ── IRR helper ────────────────────────────────────────────────────────────────

def _irr(cashflows: list[float]) -> float:
    """Internal Rate of Return. Falls back to scipy if numpy_financial absent."""
    try:
        import numpy_financial as npf
        result = npf.irr(cashflows)
        return float(result) if not math.isnan(result) else float("nan")
    except ImportError:
        pass
    try:
        from scipy.optimize import brentq
        npv_func = lambda r: sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
        return float(brentq(npv_func, -0.5, 5.0))
    except Exception:
        return float("nan")


def _npv(rate: float, cashflows: list[float]) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


# ── Section 1: Cap Rate / Yield ───────────────────────────────────────────────

def _render_cap_rate(price_uf: float, rent_monthly_uf: float,
                     vacancy_pct: float, opex_pct: float) -> dict:
    """Compute and display cap rate metrics. Returns computed values."""
    gross_annual = rent_monthly_uf * 12 * (1 - vacancy_pct / 100)
    opex_annual  = gross_annual * (opex_pct / 100)
    noi_annual   = gross_annual - opex_annual

    gross_yield  = (gross_annual / price_uf * 100) if price_uf > 0 else 0.0
    net_yield    = (noi_annual   / price_uf * 100) if price_uf > 0 else 0.0
    cap_rate     = net_yield  # cap rate ≡ net yield when measuring on market value

    st.markdown("### 1. Cap Rate / Yield")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cap Rate", f"{cap_rate:.2f}%",
              help="NOI anual / Precio compra")
    c2.metric("Gross Yield", f"{gross_yield:.2f}%",
              help="Arriendo bruto anual / Precio compra")
    c3.metric("Net Yield", f"{net_yield:.2f}%",
              help="(Arriendo bruto − Gastos) / Precio compra")
    c4.metric("NOI anual (UF)", f"{noi_annual:,.1f}",
              help="Ingresos netos de operación")

    return {
        "gross_annual": gross_annual,
        "noi_annual":   noi_annual,
        "cap_rate":     cap_rate,
        "gross_yield":  gross_yield,
        "net_yield":    net_yield,
    }


# ── Section 2: Análisis de Subvaloración ─────────────────────────────────────

def _render_subvaluation(price_uf: float, property_row: Optional[dict]):
    st.markdown("### 2. Análisis de Subvaloración")

    if property_row is None:
        st.info("Selecciona una propiedad en la pestaña Ficha para ver el análisis de subvaloración.")
        return

    real_val    = property_row.get("real_value_uf")
    predicted   = property_row.get("predicted_uf_m2")
    surface     = property_row.get("surface_m2")
    gap_pct     = property_row.get("gap_pct")

    # Fall back gracefully when fields are missing
    predicted_total = (predicted * surface) if (predicted and surface) else None

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Precio actual (UF)",
        f"{real_val:,.1f}" if real_val else "—",
        help="real_value_uf del registro limpio"
    )
    c2.metric(
        "Precio predicho (UF)",
        f"{predicted_total:,.1f}" if predicted_total else "—",
        help="predicted_uf_m2 × surface_m2"
    )
    if gap_pct is not None:
        delta_label = f"{gap_pct * 100:+.1f}%"
        c3.metric(
            "Brecha (gap_pct)",
            delta_label,
            help="(real − predicho) / predicho. Negativo = subvalorado."
        )

    if real_val and predicted_total and gap_pct is not None:
        revalorization = predicted_total - real_val
        safety_margin  = -gap_pct * 100  # positive when undervalued

        col_a, col_b = st.columns(2)
        col_a.metric(
            "Potencial de revalorización (UF)",
            f"{revalorization:+,.1f}",
            help="Si el precio corrige al nivel predicho por el modelo"
        )
        col_b.metric(
            "Margen de seguridad",
            f"{safety_margin:.1f}%",
            help="Cuánto puede caer el precio antes de perder inversión (gap inverso)"
        )

        # Visual bar
        fig = go.Figure(go.Bar(
            x=["Precio actual", "Precio predicho"],
            y=[real_val, predicted_total],
            marker_color=["#EF5350", "#66BB6A"],
            text=[f"{real_val:,.0f} UF", f"{predicted_total:,.0f} UF"],
            textposition="outside",
        ))
        fig.update_layout(
            title="Precio actual vs predicho",
            yaxis_title="UF",
            height=320,
            margin=dict(t=40, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)


# ── Section 3: DCF Simplificado ───────────────────────────────────────────────

def _render_dcf(price_uf: float, noi_year1: float,
                ltv_pct: float, credit_rate_pct: float,
                noi_growth_pct: float, discount_rate_pct: float,
                exit_cap_rate_pct: float) -> dict:
    st.markdown("### 3. DCF Simplificado — 5 años")

    # Derived financing
    loan        = price_uf * ltv_pct / 100
    equity      = price_uf - loan
    annual_debt_service = loan * (credit_rate_pct / 100)  # interest-only simplification

    rows = []
    cashflows_equity = [-equity]  # year 0

    noi = noi_year1
    for yr in range(1, 6):
        if yr > 1:
            noi *= (1 + noi_growth_pct / 100)
        net_cf    = noi - annual_debt_service
        prop_val  = (noi / (exit_cap_rate_pct / 100)) if exit_cap_rate_pct > 0 else 0.0
        equity_val = prop_val - loan

        if yr < 5:
            cashflows_equity.append(net_cf)
        else:
            # Year 5: net CF + equity residual (property sale)
            cashflows_equity.append(net_cf + equity_val)

        rows.append({
            "Año": yr,
            "NOI (UF)":         round(noi, 1),
            "Servicio deuda (UF)": round(annual_debt_service, 1),
            "Flujo neto (UF)":  round(net_cf, 1),
            "Valor propiedad (UF)": round(prop_val, 1),
            "Patrimonio (UF)":  round(equity_val, 1),
        })

    df_dcf = pd.DataFrame(rows)

    # Metrics
    irr_val  = _irr(cashflows_equity)
    npv_val  = _npv(discount_rate_pct / 100, cashflows_equity)
    total_cf = sum(cashflows_equity[1:])
    equity_multiple = (total_cf / equity) if equity > 0 else float("nan")
    coc = ((noi_year1 - annual_debt_service) / equity * 100) if equity > 0 else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("TIR (IRR)",      f"{irr_val * 100:.1f}%" if not math.isnan(irr_val) else "N/A")
    c2.metric("VAN (NPV, UF)",  f"{npv_val:,.1f}")
    c3.metric("Equity Multiple", f"{equity_multiple:.2f}x" if not math.isnan(equity_multiple) else "N/A")
    c4.metric("Cash-on-Cash",   f"{coc:.1f}%")

    st.dataframe(
        df_dcf.set_index("Año"),
        use_container_width=True,
    )

    # Waterfall chart
    noi_vals = [r["NOI (UF)"] for r in rows]
    cf_vals  = [r["Flujo neto (UF)"] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="NOI",
        x=[f"Año {r['Año']}" for r in rows],
        y=noi_vals,
        marker_color="#42A5F5",
    ))
    fig.add_trace(go.Bar(
        name="Flujo neto",
        x=[f"Año {r['Año']}" for r in rows],
        y=cf_vals,
        marker_color="#66BB6A",
    ))
    fig.update_layout(
        barmode="group",
        title="NOI vs Flujo neto por año",
        yaxis_title="UF",
        height=340,
        margin=dict(t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    return {
        "irr":            irr_val,
        "npv":            npv_val,
        "equity_multiple": equity_multiple,
        "coc":            coc,
        "df_dcf":         df_dcf,
    }


# ── Section 4: Escenarios ─────────────────────────────────────────────────────

def _render_scenarios(price_uf: float, rent_monthly_uf: float,
                      vacancy_pct: float, opex_pct: float):
    st.markdown("### 4. Análisis de Escenarios")

    scenarios = {
        "Pesimista": {
            "rent_factor":    0.85,
            "vacancy_delta":  +5.0,
            "color":          "#EF5350",
        },
        "Base": {
            "rent_factor":    1.00,
            "vacancy_delta":   0.0,
            "color":          "#42A5F5",
        },
        "Optimista": {
            "rent_factor":    1.15,
            "vacancy_delta":  -2.0,
            "color":          "#66BB6A",
        },
    }

    results = {}
    for name, cfg in scenarios.items():
        r  = rent_monthly_uf * cfg["rent_factor"]
        v  = max(0.0, vacancy_pct + cfg["vacancy_delta"])
        ga = r * 12 * (1 - v / 100)
        oe = ga * (opex_pct / 100)
        noi = ga - oe
        cap  = (noi / price_uf * 100) if price_uf > 0 else 0.0
        gy   = (ga  / price_uf * 100) if price_uf > 0 else 0.0
        ny   = cap
        results[name] = {
            "Arriendo/mes (UF)": round(r, 2),
            "Vacancia (%)":      round(v, 1),
            "Gross Yield (%)":   round(gy, 2),
            "Net Yield (%)":     round(ny, 2),
            "Cap Rate (%)":      round(cap, 2),
            "NOI anual (UF)":    round(noi, 1),
        }

    df_scen = pd.DataFrame(results).T

    # Color-coded display via columns
    cols = st.columns(3)
    for idx, (name, cfg) in enumerate(scenarios.items()):
        with cols[idx]:
            color = cfg["color"]
            st.markdown(
                f"<div style='border-left:4px solid {color}; padding-left:10px;'>"
                f"<b>{name}</b></div>",
                unsafe_allow_html=True,
            )
            for metric, val in results[name].items():
                st.metric(metric, val)

    st.markdown("**Comparativa:**")
    st.dataframe(df_scen, use_container_width=True)

    # Bar chart comparison
    metrics_to_plot = ["Cap Rate (%)", "Gross Yield (%)", "Net Yield (%)"]
    fig = go.Figure()
    for name, cfg in scenarios.items():
        fig.add_trace(go.Bar(
            name=name,
            x=metrics_to_plot,
            y=[results[name][m] for m in metrics_to_plot],
            marker_color=cfg["color"],
        ))
    fig.update_layout(
        barmode="group",
        title="Rendimientos por escenario",
        yaxis_title="%",
        height=340,
        margin=dict(t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Section 5: Punto de equilibrio ───────────────────────────────────────────

def _render_breakeven(price_uf: float, vacancy_pct: float, opex_pct: float):
    st.markdown("### 5. Punto de Equilibrio")

    target_cap = st.slider(
        "Cap rate objetivo (%)",
        min_value=1.0, max_value=15.0, value=5.0, step=0.5,
        key="fin_target_cap",
    )

    # Min rent so that NOI/price = target_cap
    # NOI = rent_annual * (1 - vacancy%) * (1 - opex%)
    # rent_annual = target_cap * price / ((1 - vacancy%) * (1 - opex%))
    denom = (1 - vacancy_pct / 100) * (1 - opex_pct / 100)
    if denom > 0 and price_uf > 0:
        min_rent_annual  = (target_cap / 100) * price_uf / denom
        min_rent_monthly = min_rent_annual / 12
    else:
        min_rent_monthly = float("nan")

    c1, c2 = st.columns(2)
    c1.metric(
        f"Arriendo mínimo para {target_cap:.1f}% cap rate",
        f"{min_rent_monthly:,.2f} UF/mes" if not math.isnan(min_rent_monthly) else "—",
    )
    if not math.isnan(min_rent_monthly):
        c2.metric(
            "Arriendo mínimo anualizado",
            f"{min_rent_monthly * 12:,.1f} UF/año",
        )

    # Sensitivity: cap rate vs rent curve
    rent_range = np.linspace(
        max(0.01, min_rent_monthly * 0.5),
        min_rent_monthly * 2.0 if not math.isnan(min_rent_monthly) else 10.0,
        50,
    )
    cap_rates = []
    for r in rent_range:
        ga  = r * 12 * (1 - vacancy_pct / 100)
        noi = ga * (1 - opex_pct / 100)
        cap_rates.append((noi / price_uf * 100) if price_uf > 0 else 0.0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=rent_range,
        y=cap_rates,
        mode="lines",
        line=dict(color="#42A5F5", width=2),
        name="Cap Rate",
    ))
    if not math.isnan(min_rent_monthly):
        fig.add_vline(
            x=min_rent_monthly,
            line_dash="dash",
            line_color="#EF5350",
            annotation_text=f"Mínimo: {min_rent_monthly:.2f} UF/mes",
            annotation_position="top right",
        )
    fig.add_hline(
        y=target_cap,
        line_dash="dot",
        line_color="#66BB6A",
        annotation_text=f"Objetivo: {target_cap:.1f}%",
        annotation_position="bottom right",
    )
    fig.update_layout(
        title="Sensibilidad Cap Rate vs Arriendo mensual",
        xaxis_title="Arriendo mensual (UF)",
        yaxis_title="Cap Rate (%)",
        height=340,
        margin=dict(t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Main entry point ──────────────────────────────────────────────────────────

def render_financial_panel(property_row: Optional[dict] = None):
    """
    Main financial analysis panel.

    Parameters
    ----------
    property_row : dict | None
        Selected property data from v_opportunities. When provided, sliders
        are pre-populated from the property's fields. Pass None for standalone
        mode with manual inputs.
    """
    st.header("Simulador Financiero")
    st.caption(
        "Modela cap rate, yield, DCF a 5 años y escenarios de rentabilidad. "
        "Todos los valores en UF salvo indicación."
    )

    # ── Pre-populate defaults from property row ───────────────────────────────
    default_price      = 2_000.0  # UF
    default_rent       = 8.0      # UF/mes
    default_surface    = None

    if property_row is not None:
        uf_m2   = property_row.get("uf_m2_building") or property_row.get("predicted_uf_m2")
        surface = property_row.get("surface_m2")
        if uf_m2 and surface and uf_m2 > 0 and surface > 0:
            default_price = round(float(uf_m2) * float(surface), 1)
            default_surface = float(surface)
        # Rough rent estimate: 0.4% of price per month (common Chilean heuristic)
        default_rent = round(default_price * 0.004, 2)

    # ── Global inputs ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Parámetros generales")

    col_a, col_b = st.columns(2)
    with col_a:
        price_uf = st.number_input(
            "Precio de compra (UF)",
            min_value=10.0,
            max_value=500_000.0,
            value=float(default_price),
            step=50.0,
            key="fin_price",
            help="Precio total de adquisición del inmueble en UF",
        )
        rent_monthly_uf = st.number_input(
            "Arriendo mensual estimado (UF/mes)",
            min_value=0.1,
            max_value=5_000.0,
            value=float(default_rent),
            step=0.5,
            key="fin_rent",
        )
    with col_b:
        vacancy_pct = st.slider(
            "Vacancia anual (%)",
            min_value=0.0, max_value=30.0, value=5.0, step=1.0,
            key="fin_vacancy",
        )
        opex_pct = st.slider(
            "Gastos operacionales (% del ingreso bruto)",
            min_value=0.0, max_value=50.0, value=15.0, step=1.0,
            key="fin_opex",
            help="Administración, mantención, seguros, contribuciones, etc.",
        )

    st.markdown("---")

    # ── Section 1: Cap Rate / Yield ───────────────────────────────────────────
    cap_result = _render_cap_rate(price_uf, rent_monthly_uf, vacancy_pct, opex_pct)

    st.markdown("---")

    # ── Section 2: Subvaloración ──────────────────────────────────────────────
    _render_subvaluation(price_uf, property_row)

    st.markdown("---")

    # ── Section 3: DCF ────────────────────────────────────────────────────────
    st.markdown("#### Parámetros de financiamiento y DCF")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        ltv_pct = st.slider(
            "LTV — Loan-to-Value (%)",
            min_value=0, max_value=90, value=70, step=5,
            key="fin_ltv",
            help="Porcentaje del precio financiado con crédito hipotecario",
        )
        credit_rate_pct = st.slider(
            "Tasa crédito hipotecario anual (%)",
            min_value=1.0, max_value=15.0, value=4.5, step=0.25,
            key="fin_credit_rate",
        )
    with col_d2:
        noi_growth_pct = st.slider(
            "Crecimiento NOI anual (%)",
            min_value=0.0, max_value=10.0, value=2.28, step=0.1,
            key="fin_noi_growth",
            help="2.28% = tasa de referencia de la tesis metodológica",
        )
        discount_rate_pct = st.slider(
            "Tasa de descuento (%)",
            min_value=1.0, max_value=20.0, value=7.0, step=0.5,
            key="fin_discount",
        )
        exit_cap_rate_pct = st.slider(
            "Exit Cap Rate año 5 (%)",
            min_value=1.0, max_value=15.0,
            value=round(cap_result["cap_rate"], 1) if cap_result["cap_rate"] > 0 else 5.0,
            step=0.25,
            key="fin_exit_cap",
        )

    _render_dcf(
        price_uf         = price_uf,
        noi_year1        = cap_result["noi_annual"],
        ltv_pct          = ltv_pct,
        credit_rate_pct  = credit_rate_pct,
        noi_growth_pct   = noi_growth_pct,
        discount_rate_pct = discount_rate_pct,
        exit_cap_rate_pct = exit_cap_rate_pct,
    )

    st.markdown("---")

    # ── Section 4: Escenarios ─────────────────────────────────────────────────
    _render_scenarios(price_uf, rent_monthly_uf, vacancy_pct, opex_pct)

    st.markdown("---")

    # ── Section 5: Punto de equilibrio ───────────────────────────────────────
    _render_breakeven(price_uf, vacancy_pct, opex_pct)
