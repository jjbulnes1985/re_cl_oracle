"""
app.py
------
Streamlit dashboard for RE_CL opportunity detection platform.

Features:
  - Sidebar: filters by typology, commune, city_zone, min opportunity score
  - Interactive Folium map embedded in the app
  - Property ranking table with score and SHAP drivers
  - Asset detail view: single property with comparables + V4 characteristics
  - Enrichment tab: commune context, OSM/metro scatter, age distribution
  - Data quality panel: null rates, score distribution

Usage:
    streamlit run src/dashboard/app.py
"""

import json
import os
import sys
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.dashboard.financial_panel import render_financial_panel
from src.dashboard.quality_panel import render_quality_panel

MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")
MAP_CENTER    = [-33.45, -70.67]
MAP_ZOOM      = 11

TYPOLOGY_COLORS = {
    "apartments":  "#2196F3",
    "residential": "#4CAF50",
    "land":        "#FF9800",
    "retail":      "#9C27B0",
    "unknown":     "#9E9E9E",
}

st.set_page_config(
    page_title="RE_CL — Oportunidades Inmobiliarias RM",
    page_icon="🏢",
    layout="wide",
)

st.markdown("""
<style>
  .stMetric { background: #1e293b; border-radius: 8px; padding: 12px; }
  .stMetric label { color: #94a3b8 !important; font-size: 0.75rem; }
  .stMetric .metric-value { color: #f1f5f9 !important; }
  .block-container { max-width: 1400px; padding-top: 1rem; }
  .stDataFrame { border: 1px solid #334155; border-radius: 6px; }
  .stAlert { border-radius: 6px; }
  h1, h2, h3 { color: #f1f5f9; }
</style>
""", unsafe_allow_html=True)


# ── DB connection (cached) ────────────────────────────────────────────────────

@st.cache_resource
def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db   = os.getenv("POSTGRES_DB",   "re_cl")
        user = os.getenv("POSTGRES_USER", "re_cl_user")
        pwd  = os.getenv("POSTGRES_PASSWORD", "")
        url  = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=300)
def load_opportunities(typologies, communes, min_score, city_zones=(), limit=10000):
    engine = get_engine()
    type_list    = "', '".join(typologies)
    commune_list = "', '".join(communes)

    zone_clause = ""
    if city_zones:
        zone_list = "', '".join(city_zones)
        zone_clause = f"AND tf.city_zone IN ('{zone_list}')"

    query = f"""
        SELECT
            vo.score_id, vo.raw_id, vo.project_type, vo.county_name, vo.year,
            vo.real_value_uf,
            vo.surface_m2, vo.surface_building_m2, vo.surface_land_m2,
            vo.uf_m2_building, vo.uf_m2_land,
            vo.opportunity_score, vo.undervaluation_score,
            vo.gap_pct, vo.gap_percentile,
            vo.predicted_uf_m2,
            vo.data_confidence, vo.shap_top_features,
            vo.latitude, vo.longitude,
            tr.id_role, tr.address, tr.apartment, tr.seller_name,
            tf.age, tf.construction_year_bucket, tf.city_zone,
            tf.dist_metro_km, tf.amenities_500m
        FROM v_opportunities vo
        LEFT JOIN model_scores ms ON ms.id = vo.score_id
        LEFT JOIN transaction_features tf ON tf.clean_id = ms.clean_id
        LEFT JOIN transactions_raw tr ON tr.id = vo.raw_id
        WHERE vo.model_version = '{MODEL_VERSION}'
          AND vo.project_type IN ('{type_list}')
          AND vo.county_name IN ('{commune_list}')
          AND vo.opportunity_score >= {min_score}
          AND vo.latitude IS NOT NULL
          {zone_clause}
        ORDER BY vo.opportunity_score DESC
        LIMIT {limit}
    """
    return pd.read_sql(query, engine)


@st.cache_data(ttl=300)
def load_land_opportunities(county_name: str = None, limit: int = 500):
    """Carga oportunidades de terrenos usando comparable-based pricing."""
    engine = get_engine()
    where = f"AND county_name = '{county_name.replace(chr(39), chr(39)*2)}'" if county_name else ""
    query = f"""
        SELECT raw_id, county_name, year,
            real_value_uf, surface_land_m2, surface_building_m2,
            uf_m2_land, commune_median_uf_m2, p25_uf_m2, p75_uf_m2,
            land_gap_pct, land_opportunity_score, comparable_count,
            land_ratio, latitude, longitude
        FROM v_land_opportunities
        WHERE 1=1 {where}
        ORDER BY land_opportunity_score DESC
        LIMIT {limit}
    """
    return pd.read_sql(query, engine)


@st.cache_data(ttl=300)
def load_commune_stats():
    engine = get_engine()
    return pd.read_sql(
        f"SELECT * FROM commune_stats WHERE model_version = '{MODEL_VERSION}' ORDER BY median_score DESC",
        engine
    )


@st.cache_data(ttl=300)
def load_commune_properties(county_name: str):
    """Carga propiedades de una comuna directo desde DB, sin depender de filtros sidebar."""
    engine = get_engine()
    query = f"""
        SELECT
            vo.score_id, vo.raw_id, vo.project_type, vo.county_name, vo.year,
            vo.real_value_uf,
            vo.surface_m2, vo.surface_building_m2, vo.surface_land_m2,
            vo.uf_m2_building, vo.uf_m2_land,
            vo.predicted_uf_m2,
            vo.gap_pct,
            vo.opportunity_score, vo.data_confidence,
            vo.latitude, vo.longitude,
            tr.id_role, tr.address, tr.apartment, tr.seller_name
        FROM v_opportunities vo
        LEFT JOIN transactions_raw tr ON tr.id = vo.raw_id
        WHERE vo.model_version = '{MODEL_VERSION}'
          AND vo.county_name = '{county_name.replace("'", "''")}'
          AND vo.opportunity_score IS NOT NULL
        ORDER BY vo.opportunity_score DESC
        LIMIT 500
    """
    return pd.read_sql(query, engine)


@st.cache_data(ttl=300)
def load_typologies():
    engine = get_engine()
    result = pd.read_sql(
        "SELECT DISTINCT project_type FROM v_opportunities WHERE project_type IS NOT NULL ORDER BY 1",
        engine
    )
    return result["project_type"].tolist()


@st.cache_data(ttl=300)
def load_communes():
    engine = get_engine()
    result = pd.read_sql(
        "SELECT DISTINCT county_name FROM v_opportunities WHERE county_name IS NOT NULL ORDER BY 1",
        engine
    )
    return result["county_name"].tolist()


@st.cache_data(ttl=600)
def load_data_quality():
    engine = get_engine()
    quality = pd.read_sql("""
        SELECT
            COUNT(*)                                        AS total_clean,
            COUNT(*) FILTER (WHERE surface_m2 IS NULL)     AS null_surface,
            COUNT(*) FILTER (WHERE latitude IS NULL)       AS null_coords,
            COUNT(*) FILTER (WHERE real_value_uf IS NULL)  AS null_value,
            ROUND(AVG(data_confidence)::numeric, 4)        AS mean_confidence
        FROM transactions_clean
    """, engine)
    scores = pd.read_sql(f"""
        SELECT
            COUNT(*) AS total_scored,
            ROUND(AVG(opportunity_score)::numeric, 4) AS mean_score,
            COUNT(*) FILTER (WHERE opportunity_score > 0.7) AS high_opp
        FROM model_scores
        WHERE model_version = '{MODEL_VERSION}'
    """, engine)
    return quality.iloc[0], scores.iloc[0]


@st.cache_data(ttl=600)
def load_comparables(score_id, county_name, project_type, limit=5):
    engine = get_engine()
    return pd.read_sql(f"""
        SELECT score_id, county_name, uf_m2_building, predicted_uf_m2,
               gap_pct, opportunity_score, surface_m2, year
        FROM v_opportunities
        WHERE county_name = '{county_name}'
          AND project_type = '{project_type}'
          AND model_version = '{MODEL_VERSION}'
          AND score_id != {score_id}
        ORDER BY opportunity_score DESC
        LIMIT {limit}
    """, engine)


@st.cache_data(ttl=600)
def load_commune_enrichment():
    try:
        from src.features.commune_context import load_ine_census, load_crime_index, load_commune_growth
        growth = load_commune_growth()
        ine = load_ine_census()
        crime = load_crime_index()
        df = growth.merge(ine, on='county_name', how='left')
        df = df.merge(crime[['county_name', 'crime_index', 'crime_tier']], on='county_name', how='left')
        return df
    except Exception as e:
        return pd.DataFrame()


# ── Map builder ───────────────────────────────────────────────────────────────

def build_map(df: pd.DataFrame) -> folium.Map:
    m = folium.Map(location=MAP_CENTER, zoom_start=MAP_ZOOM, tiles="CartoDB positron")

    if df.empty:
        return m

    heat_data = [
        [r["latitude"], r["longitude"], r["opportunity_score"]]
        for _, r in df.iterrows()
        if pd.notna(r["latitude"]) and pd.notna(r["opportunity_score"])
    ]
    if heat_data:
        from folium.plugins import HeatMap
        HeatMap(
            heat_data,
            name="Heatmap de oportunidad",
            min_opacity=0.3,
            radius=15,
            blur=20,
            gradient={0.2: "blue", 0.5: "yellow", 0.8: "orange", 1.0: "red"},
        ).add_to(m)

    for ptype in df["project_type"].unique():
        sub   = df[df["project_type"] == ptype].head(2000)
        color = TYPOLOGY_COLORS.get(ptype, "#9E9E9E")
        fg    = folium.FeatureGroup(name=f"{ptype.title()}", show=True)

        for _, row in sub.iterrows():
            shap_html = ""
            _shap_val = row.get("shap_top_features")
            if _shap_val is not None and not (isinstance(_shap_val, float) and pd.isna(_shap_val)):
                try:
                    drivers = json.loads(_shap_val)
                    shap_html = "<b>Drivers:</b><ul>" + "".join(
                        f"<li>{d['feature']}: {d['shap']:+.3f} ({d['direction']})</li>"
                        for d in drivers
                    ) + "</ul>"
                except Exception:
                    pass

            popup_html = f"""
            <div style="font-family:sans-serif;min-width:180px;font-size:12px">
              <b>{ptype.title()}</b> — {row['county_name']}<br>
              <b>Score:</b> {row['opportunity_score']:.3f}<br>
              <b>Gap:</b> {row['gap_pct']*100:+.1f}%<br>
              <b>UF/m²:</b> {row['uf_m2_building']:.1f} vs {row['predicted_uf_m2']:.1f} pred<br>
              {shap_html}
            </div>"""

            radius = 4 + row["opportunity_score"] * 6
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=radius,
                color=color,
                fill=True,
                fill_opacity=0.65,
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"Score: {row['opportunity_score']:.3f}",
            ).add_to(fg)
        fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ── Sidebar ───────────────────────────────────────────────────────────────────

PROFILE_DESCRIPTIONS = {
    "default":   "Estándar: subvaloración 70% + confianza 30%",
    "location":  "Ubicación: prioriza accesibilidad y zona",
    "growth":    "Crecimiento: prioriza comunas con expansión demográfica",
    "liquidity": "Liquidez: prioriza mercados con alto volumen de transacciones",
    "custom":    "Personalizado: define tus propios pesos",
}


def render_sidebar():
    st.sidebar.title("Filtros")
    st.sidebar.markdown(f"**Modelo:** `{MODEL_VERSION}`")

    try:
        all_types    = load_typologies()
        all_communes = load_communes()
    except Exception as e:
        st.sidebar.error(f"Error de conexión: {e}")
        return [], [], [], 0.0, None

    sel_types = st.sidebar.multiselect(
        "Tipología", all_types, default=all_types
    )
    sel_communes = st.sidebar.multiselect(
        "Comunas", all_communes, default=all_communes[:10]
    )
    city_zones = st.sidebar.multiselect(
        "Zona ciudad",
        options=["centro_norte", "este", "oeste", "sur"],
        default=[],
        help="Filtro por zona territorial de Santiago RM"
    )
    min_score = st.sidebar.slider(
        "Score mínimo", min_value=0.0, max_value=1.0, value=0.5, step=0.05
    )

    # ── Scoring Profile ────────────────────────────────────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Perfil de Scoring")

    profile_choice = st.sidebar.selectbox(
        "Modo de ponderación",
        options=list(PROFILE_DESCRIPTIONS.keys()),
        format_func=lambda k: PROFILE_DESCRIPTIONS[k],
        index=0,
    )

    scoring_profile = None
    if profile_choice == "custom":
        st.sidebar.markdown("**Pesos personalizados** *(se normalizan automáticamente)*")
        w_underval  = st.sidebar.slider("Subvaloración",           0.0, 1.0, 0.70, 0.05, key="w_uv")
        w_location  = st.sidebar.slider("Ubicación",               0.0, 1.0, 0.00, 0.05, key="w_loc")
        w_growth    = st.sidebar.slider("Crecimiento demográfico",  0.0, 1.0, 0.00, 0.05, key="w_gro")
        w_volume    = st.sidebar.slider("Volumen / liquidez",       0.0, 1.0, 0.00, 0.05, key="w_vol")
        w_conf      = st.sidebar.slider("Confianza de datos",       0.0, 1.0, 0.30, 0.05, key="w_conf")

        total = w_underval + w_location + w_growth + w_volume + w_conf
        if total == 0:
            st.sidebar.warning("Al menos un peso debe ser > 0")
            scoring_profile = None
        else:
            # Normalize and display effective weights
            eff = {
                "Subvaloración":  w_underval / total,
                "Ubicación":      w_location / total,
                "Crecimiento":    w_growth   / total,
                "Liquidez":       w_volume   / total,
                "Confianza":      w_conf     / total,
            }
            active = {k: v for k, v in eff.items() if v > 0.001}
            st.sidebar.markdown("**Pesos efectivos:**")
            for dim, w in sorted(active.items(), key=lambda x: -x[1]):
                st.sidebar.markdown(f"- {dim}: `{w*100:.1f}%`")

            from src.scoring.scoring_profile import ScoringProfile
            scoring_profile = ScoringProfile.custom(
                undervaluation = w_underval,
                confidence     = w_conf,
                location       = w_location,
                growth         = w_growth,
                volume         = w_volume,
            )
    else:
        from src.scoring.scoring_profile import ScoringProfile
        try:
            scoring_profile = ScoringProfile.from_name(profile_choice)
            st.sidebar.caption(PROFILE_DESCRIPTIONS[profile_choice])
            st.sidebar.markdown("**Pesos:**")
            for dim, w in sorted(scoring_profile.weights.items(), key=lambda x: -x[1]):
                st.sidebar.markdown(f"- `{dim}`: {w*100:.0f}%")
        except Exception:
            scoring_profile = None

    st.sidebar.markdown("---")
    st.sidebar.caption("Fuente: CBR RM 2013-2014")

    return sel_types, sel_communes, city_zones, min_score, scoring_profile


# ── Tab: Mapa ─────────────────────────────────────────────────────────────────

def render_map_tab(df: pd.DataFrame):
    st.subheader(f"Mapa de oportunidades ({len(df):,} propiedades)")
    if df.empty:
        st.warning("Sin datos para los filtros seleccionados.")
        return

    m = build_map(df)
    import streamlit.components.v1 as components
    components.html(m._repr_html_(), height=550, scrolling=False)


# ── Tab: Ranking ──────────────────────────────────────────────────────────────

def render_ranking_tab(df: pd.DataFrame):
    st.subheader("🏆 Deal Flow — Inmuebles subvalorados para ofertar")
    if df.empty:
        st.warning("Sin datos. Ajusta los filtros del sidebar.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Oportunidades encontradas", len(df))
    col2.metric("Score promedio", f"{df['opportunity_score'].mean():.1%}")
    col3.metric("Gap promedio vs mercado", f"{df['gap_pct'].mean()*100:.1f}%")
    col4.metric("Top comuna", df['county_name'].mode()[0] if len(df) else "—")

    st.info("💡 **Cómo usar:** Selecciona una fila → ve la dirección exacta y el Rol SII → busca en el CBR o contacta al vendedor registrado.")

    # ── Tabla principal orientada a acción ────────────────────────────────────
    display = df.copy()
    display["Dirección"] = display.apply(
        lambda r: f"{r.get('address','') or ''} {r.get('apartment','') or ''}".strip(),
        axis=1
    )
    display["Dirección"] = display["Dirección"].replace("", "Sin dirección")
    # Use calibrated prediction when available, fall back to raw
    pred_col = "calibrated_predicted_uf_m2" if "calibrated_predicted_uf_m2" in display.columns else "predicted_uf_m2"
    gap_col  = "calibrated_gap_pct"         if "calibrated_gap_pct"         in display.columns else "gap_pct"
    display["Gap %"]      = (display[gap_col] * 100).round(1)
    display["Score %"]    = (display["opportunity_score"] * 100).round(1)
    display["Precio UF"]  = display["real_value_uf"].round(0)
    display["UF/m² real"] = display["uf_m2_building"].round(1)
    display["UF/m² pred"] = display[pred_col].round(1)
    display["m² construido"] = display["surface_building_m2"].where(
        display["surface_building_m2"].fillna(0) > 0, other=None
    ).round(0)
    display["m² terreno"] = display["surface_land_m2"].where(
        display["surface_land_m2"].fillna(0) > 0, other=None
    ).round(0)
    display["Google Maps"] = display.apply(
        lambda r: f"https://www.google.com/maps?q={r['latitude']},{r['longitude']}"
        if pd.notna(r.get("latitude")) else "", axis=1
    )

    cols_show = ["score_id", "Dirección", "county_name", "project_type",
                 "id_role", "Precio UF", "m² construido", "m² terreno",
                 "UF/m² real", "UF/m² pred", "Gap %", "Score %", "seller_name", "year"]
    cols_show = [c for c in cols_show if c in display.columns]

    renamed = display[cols_show].rename(columns={
        "score_id":    "#",
        "county_name": "Comuna",
        "project_type":"Tipo",
        "id_role":     "Rol SII",
        "seller_name": "Vendedor CBR",
        "year":        "Año",
    })

    st.dataframe(
        renamed.head(500),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score %": st.column_config.ProgressColumn(
                "Score %", min_value=0, max_value=100, format="%.1f%%"
            ),
            "Gap %": st.column_config.NumberColumn("Gap %", format="%.1f%%"),
        },
    )

    # ── Ficha de la top oportunidad ───────────────────────────────────────────
    st.divider()
    st.markdown("### 🔍 Top oportunidad — Detalle para actuar")
    top = df.iloc[0]
    address_full = f"{top.get('address','') or 'Sin dirección'}"
    if top.get("apartment"):
        address_full += f", Depto/Lote {top['apartment']}"
    address_full += f", {top.get('county_name','')}"

    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**📍 Dirección:** {address_full}")
        st.markdown(f"**🔑 Rol SII:** `{top.get('id_role', 'N/D')}`")
        st.markdown(f"**🏷️ Tipo:** {top.get('project_type','').title()} | **Año transacción:** {int(top.get('year', 0)) if pd.notna(top.get('year')) else 'N/D'}")
        if top.get("seller_name"):
            st.markdown(f"**👤 Vendedor registrado en CBR:** {top['seller_name']}")
        gap_val    = top.get("gap_pct", 0) * 100
        price_real = top.get("uf_m2_building", 0)
        price_pred = top.get("predicted_uf_m2", 0)
        valor_total = top.get("real_value_uf", 0) or 0
        st.markdown(f"**💰 UF/m² construido:** {price_real:.1f} real | {price_pred:.1f} modelo | **Descuento:** {gap_val:+.1f}%")

        # ── Descomposición de superficie y valor (crucial para casas y terrenos) ──
        s_build = top.get("surface_building_m2") or 0
        s_land  = top.get("surface_land_m2")  or 0
        uf_land = top.get("uf_m2_land")       or 0
        ptype   = top.get("project_type", "")

        if s_build > 0 or s_land > 0:
            val_build = price_real * s_build if s_build > 0 else 0
            val_land  = uf_land * s_land     if s_land  > 0 else 0
            val_sum   = val_build + val_land
            # upside: diferencia entre lo que debería valer según modelo y lo pagado
            upside = (price_pred * s_build - price_real * s_build) if s_build > 0 else 0

            lines = []
            if s_build > 0:
                lines.append(f"🏗️ Construido: **{s_build:.0f} m²** × {price_real:.1f} UF/m² = **{val_build:,.0f} UF**")
            if s_land > 0 and ptype in ("residential", "land"):
                lines.append(f"🌿 Terreno: **{s_land:.0f} m²** × {uf_land:.1f} UF/m² = **{val_land:,.0f} UF**")
            if val_sum > 0:
                lines.append(f"📊 Valor compuesto: **{val_sum:,.0f} UF** | Precio pagado: **{valor_total:,.0f} UF**")
            if upside > 50:
                lines.append(f"⬆️ Upside estimado por modelo: **+{upside:,.0f} UF**")
            for line in lines:
                st.markdown(line)
        elif valor_total > 0:
            ahorro = (price_pred - price_real) * (valor_total / price_real if price_real > 0 else 0)
            st.markdown(f"**📐 Valor total pagado:** {valor_total:,.0f} UF | **Upside estimado:** +{max(ahorro,0):,.0f} UF")
    with c2:
        if pd.notna(top.get("latitude")) and pd.notna(top.get("longitude")):
            maps_url = f"https://www.google.com/maps?q={top['latitude']},{top['longitude']}"
            st.markdown(f"[📌 Ver en Google Maps]({maps_url})")
        st.markdown("**Próximos pasos:**")
        st.markdown(f"1. Busca Rol `{top.get('id_role','?')}` en [CBR RM](https://www.conservador.cl)")
        st.markdown("2. Verifica vigencia y cargas del inmueble")
        st.markdown("3. Contacta al vendedor o corredor de la zona")
        st.markdown("4. Ofrece con descuento sobre tasación fiscal")

    # SHAP drivers
    _shap_top = top.get("shap_top_features")
    if _shap_top is not None and not (isinstance(_shap_top, float) and pd.isna(_shap_top)):
        try:
            drivers = json.loads(_shap_top)
            st.markdown("**Por qué está subvalorada (SHAP):**")
            for d in drivers:
                arrow = "⬆️" if d["direction"] == "up" else "⬇️"
                st.markdown(f"- `{d['feature']}`: {d['shap']:+.3f} {arrow}")
        except Exception:
            pass


# ── Tab: Comunas ──────────────────────────────────────────────────────────────

def render_communes_tab(df: pd.DataFrame = None):
    st.subheader("🏘️ Ranking comunal — haz clic para ver propiedades individuales")
    try:
        stats = load_commune_stats()
    except Exception as e:
        st.error(f"Error cargando commune_stats: {e}")
        return

    if stats.empty:
        st.info("Sin datos de comunas. Ejecuta commune_ranking.py primero.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Comunas analizadas", len(stats))
    col2.metric("Score mediano promedio", f"{stats['median_score'].mean():.3f}")
    col3.metric("% Subvaloradas promedio", f"{stats['pct_subvaloradas'].mean():.1f}%")

    # Solo columnas con datos reales, nombres legibles
    keep = {
        "county_name":      "Comuna",
        "n_transactions":   "Transacciones",
        "median_score":     "Score Mediano",
        "pct_subvaloradas": "% Subvaloradas",
        "median_uf_m2":     "UF/m² Mediano",
        "median_gap_pct":   "Gap Mediano",
        "crime_tier":       "Riesgo Delictual",
        "educacion_score":  "Educación",
    }
    show_cols = [c for c in keep if c in stats.columns and stats[c].notna().any()]
    display = stats[show_cols].rename(columns={c: keep[c] for c in show_cols}).copy()
    if "Gap Mediano" in display.columns:
        display["Gap Mediano"] = (display["Gap Mediano"] * 100).round(1)
    if "Score Mediano" in display.columns:
        display["Score Mediano"] = display["Score Mediano"].round(4)

    event = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Score Mediano": st.column_config.ProgressColumn("Score Mediano", min_value=0, max_value=1, format="%.3f"),
            "% Subvaloradas": st.column_config.NumberColumn("% Subvaloradas", format="%.1f%%"),
            "Gap Mediano": st.column_config.NumberColumn("Gap Mediano %", format="%.1f%%"),
        },
    )

    # ── Drill-down: propiedades de la comuna seleccionada ────────────────────
    selected_rows = event.selection.get("rows", []) if hasattr(event, "selection") else []
    selected_commune = None
    if selected_rows:
        selected_commune = stats.iloc[selected_rows[0]]["county_name"]
    else:
        selected_commune = st.selectbox(
            "O selecciona una comuna para ver sus propiedades:",
            [""] + sorted(stats["county_name"].tolist()),
            index=0,
        ) or None

    if selected_commune:
        st.divider()
        st.markdown(f"### 📍 Propiedades subvaloradas en **{selected_commune}**")
        with st.spinner("Cargando propiedades..."):
            comm_df = load_commune_properties(selected_commune)
        if comm_df.empty:
            st.info("Sin propiedades con score calculado para esta comuna.")
        else:
            comm_df["Dirección"] = comm_df.apply(
                lambda r: f"{r.get('address','') or 'Sin dirección'}" +
                          (f" {r.get('apartment','')}" if r.get("apartment") else ""), axis=1)
            comm_df["Gap %"] = (comm_df["gap_pct"] * 100).round(1)
            comm_df["Score %"] = (comm_df["opportunity_score"] * 100).round(1)

            tbl_cols = [c for c in ["Dirección","id_role","project_type","year","surface_m2",
                                     "uf_m2_building","predicted_uf_m2","Gap %","Score %","seller_name"]
                        if c in comm_df.columns]
            tbl = comm_df[tbl_cols].rename(columns={
                "id_role":"Rol SII","project_type":"Tipo","year":"Año",
                "surface_m2":"m²","uf_m2_building":"UF/m² Real",
                "predicted_uf_m2":"UF/m² Modelo","seller_name":"Vendedor CBR",
            }).sort_values("Score %", ascending=False)

            st.markdown(f"**{len(tbl)} propiedades encontradas** — ordenadas por oportunidad:")
            st.dataframe(tbl, use_container_width=True, hide_index=True,
                         column_config={"Score %": st.column_config.ProgressColumn(
                             "Score %", min_value=0, max_value=100, format="%.1f%%")})

            # Top 1 con acción
            top = comm_df.sort_values("opportunity_score", ascending=False).iloc[0]
            st.markdown(f"**🏆 Mejor oportunidad:** {top.get('address','Sin dirección')} — "
                        f"Rol `{top.get('id_role','N/D')}` — "
                        f"Gap {top['gap_pct']*100:+.1f}% — "
                        f"Vendedor: {top.get('seller_name','N/D')}")
            if pd.notna(top.get("latitude")):
                st.markdown(f"[📌 Ver en Google Maps](https://www.google.com/maps?q={top['latitude']},{top['longitude']})")


# ── Tab: Terrenos ─────────────────────────────────────────────────────────────

def render_land_tab():
    st.subheader("🌿 Oportunidades en Terrenos — Comparable-based pricing")
    st.info(
        "Propiedades con superficie de terreno significativamente mayor al área construida, "
        "cuyo UF/m² de terreno está **por debajo de la mediana comunal** del mismo año. "
        "Scoring basado en comparables reales, no en el modelo hedónico."
    )

    try:
        df_land = load_land_opportunities(limit=2000)
    except Exception as e:
        st.error(f"Error cargando terrenos: {e}")
        return

    if df_land.empty:
        st.warning("Sin datos de terrenos. Verifica que la migración 011_land_scoring.sql fue aplicada.")
        return

    # ── KPIs ──────────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Terrenos oportunidad", f"{len(df_land):,}")
    c2.metric("Score promedio", f"{df_land['land_opportunity_score'].mean():.1%}")
    c3.metric("Gap promedio vs mediana", f"{df_land['land_gap_pct'].mean()*100:.1f}%")
    c4.metric("Comunas", df_land['county_name'].nunique())

    # ── Filters ───────────────────────────────────────────────────────────────
    col_f1, col_f2 = st.columns(2)
    communes_land = sorted(df_land['county_name'].dropna().unique())
    sel_commune = col_f1.selectbox("Filtrar por comuna", ["Todas"] + communes_land)
    min_land_score = col_f2.slider("Score mínimo", 0.55, 1.0, 0.65, 0.05)

    filtered = df_land[df_land['land_opportunity_score'] >= min_land_score]
    if sel_commune != "Todas":
        filtered = filtered[filtered['county_name'] == sel_commune]

    # ── Table ─────────────────────────────────────────────────────────────────
    display = filtered.copy()
    display["Score %"]          = (display["land_opportunity_score"] * 100).round(1)
    display["Gap vs mediana %"] = (display["land_gap_pct"] * 100).round(1)
    display["UF/m² terreno"]    = display["uf_m2_land"].round(2)
    display["Mediana comunal"]  = display["commune_median_uf_m2"].round(2)
    display["m² terreno"]       = display["surface_land_m2"].round(0)
    display["m² construido"]    = display["surface_building_m2"].where(
        display["surface_building_m2"].fillna(0) > 0, other=None
    ).round(0)
    display["Precio total UF"]  = display["real_value_uf"].round(0)
    display["Ratio sit/const"]  = display["land_ratio"].round(1)
    display["Google Maps"]      = display.apply(
        lambda r: f"https://www.google.com/maps?q={r['latitude']},{r['longitude']}"
        if pd.notna(r.get("latitude")) else "", axis=1
    )

    cols_show = ["county_name", "year", "m² terreno", "m² construido",
                 "UF/m² terreno", "Mediana comunal", "Gap vs mediana %",
                 "Score %", "Precio total UF", "Ratio sit/const", "Google Maps"]
    cols_show = [c for c in cols_show if c in display.columns]

    st.dataframe(
        display[cols_show].rename(columns={"county_name": "Comuna", "year": "Año"}),
        use_container_width=True, hide_index=True,
        column_config={
            "Score %": st.column_config.ProgressColumn("Score %", min_value=0, max_value=100, format="%.1f%%"),
            "Gap vs mediana %": st.column_config.NumberColumn("Gap vs mediana %", format="%.1f%%"),
            "Google Maps": st.column_config.LinkColumn("Maps"),
        },
    )

    # ── Top land opportunity detail ────────────────────────────────────────────
    if not filtered.empty:
        st.divider()
        st.markdown("### 🏆 Top terreno — Detalle")
        top = filtered.iloc[0]
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown(f"**📍 Comuna:** {top['county_name']} | **Año transacción:** {int(top['year'])}")
            st.markdown(f"**🌿 Terreno:** {top['surface_land_m2']:,.0f} m² | **UF/m²:** {top['uf_m2_land']:.2f}")
            st.markdown(f"**📊 Mediana comunal:** {top['commune_median_uf_m2']:.2f} UF/m² "
                       f"(P25: {top['p25_uf_m2']:.2f} | P75: {top['p75_uf_m2']:.2f})")
            gap_land = top['land_gap_pct'] * 100
            st.markdown(f"**💰 Gap vs mediana:** {gap_land:+.1f}% — precio {abs(gap_land):.1f}% {'bajo' if gap_land<0 else 'sobre'} la mediana")
            total_uf = top.get('real_value_uf', 0)
            upside_uf = (top['commune_median_uf_m2'] - top['uf_m2_land']) * top['surface_land_m2']
            st.markdown(f"**Valor total pagado:** {total_uf:,.0f} UF | **Upside potencial:** +{max(upside_uf,0):,.0f} UF")
            st.markdown(f"**Comparables usados:** {int(top['comparable_count'])} transacciones en {top['county_name']} {int(top['year'])}")
        with col2:
            if pd.notna(top.get("latitude")):
                maps_url = f"https://www.google.com/maps?q={top['latitude']},{top['longitude']}"
                st.markdown(f"[📌 Ver en Google Maps]({maps_url})")
            st.markdown("**Próximos pasos:**")
            st.markdown("1. Verificar zonificación y constructibilidad")
            st.markdown("2. Consultar PRC de la comuna")
            st.markdown("3. Estimar valor residual del suelo")
            st.markdown("4. Evaluar potencial de subdivisión o desarrollo")


# ── Tab: Ficha de activo ──────────────────────────────────────────────────────

def render_detail_tab(df: pd.DataFrame):
    st.subheader("Ficha de activo")
    if df.empty:
        st.warning("Sin propiedades. Ajusta los filtros.")
        return

    score_ids = df["score_id"].tolist()
    sel_id = st.selectbox("Selecciona propiedad (score_id)", score_ids[:100])
    row = df[df["score_id"] == sel_id].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Opp. Score", f"{row['opportunity_score']:.3f}")
    c2.metric("UF/m² Real", f"{row['uf_m2_building']:.1f}")
    c3.metric("UF/m² Predicho", f"{row['predicted_uf_m2']:.1f}")
    c4.metric("Gap", f"{row['gap_pct']*100:+.1f}%")

    st.markdown(f"**Tipología:** {row['project_type']} | **Comuna:** {row['county_name']} | **Año:** {row['year']}")
    st.markdown(f"**Superficie:** {row['surface_m2']:.0f} m² | **Confianza:** {row['data_confidence']:.2f}")

    _shap_row = row.get("shap_top_features")
    if _shap_row is not None and not (isinstance(_shap_row, float) and pd.isna(_shap_row)):
        try:
            drivers = json.loads(_shap_row)
            st.markdown("**Principales drivers del score:**")
            for d in drivers:
                arrow = "↑" if d["direction"] == "up" else "↓"
                st.markdown(f"- `{d['feature']}`: {d['shap']:+.4f} {arrow}")
        except Exception:
            pass

    # V4 characteristics section
    st.markdown("---")
    st.subheader("Características V4")
    col1, col2, col3 = st.columns(3)
    with col1:
        if pd.notna(row.get('age')):
            st.metric("Antigüedad", f"{int(row['age'])} años")
        if row.get('construction_year_bucket'):
            st.info(f"Bucket: {row['construction_year_bucket']}")
    with col2:
        if row.get('city_zone'):
            st.metric("Zona ciudad", row['city_zone'])
    with col3:
        if pd.notna(row.get('dist_metro_km')):
            st.metric("Dist. Metro", f"{row['dist_metro_km']:.2f} km")
        if pd.notna(row.get('amenities_500m')):
            st.metric("Amenidades 500m", int(row['amenities_500m']))

    # Comparables
    try:
        comps = load_comparables(sel_id, row["county_name"], row["project_type"])
        if not comps.empty:
            st.markdown("**Comparables cercanos en la misma comuna:**")
            st.dataframe(comps, use_container_width=True, hide_index=True)
    except Exception:
        pass


# ── Tab: Enriquecimiento ──────────────────────────────────────────────────────

def render_enrichment_tab(df: pd.DataFrame):
    import plotly.express as px

    st.subheader("Enriquecimiento V4 — Contexto comunal y características OSM")

    # ── a) Commune enrichment table ───────────────────────────────────────────
    st.markdown("### Contexto comunal")
    enrich_df = load_commune_enrichment()

    if enrich_df.empty:
        st.info("Datos de enriquecimiento comunal no disponibles. Ejecuta commune_context.py primero.")
    else:
        # Join commune stats for ordering
        try:
            stats = load_commune_stats()
            if not stats.empty and "county_name" in stats.columns and "median_score" in stats.columns:
                enrich_df = enrich_df.merge(
                    stats[["county_name", "median_score"]], on="county_name", how="left"
                ).sort_values("median_score", ascending=False)
        except Exception:
            pass

        display_cols = [c for c in ["county_name", "crime_index", "crime_tier",
                                     "educacion_score", "hacinamiento_score",
                                     "densidad_norm", "median_score"] if c in enrich_df.columns]
        display_enrich = enrich_df[display_cols].copy()

        def style_crime_tier(val):
            colors = {"alto": "background-color: #ffcccc", "medio": "background-color: #fff3cc",
                      "bajo": "background-color: #ccffcc"}
            return colors.get(str(val).lower(), "")

        styled = display_enrich.style.map(
            style_crime_tier, subset=["crime_tier"] if "crime_tier" in display_enrich.columns else []
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("---")

    if df.empty:
        st.info("Sin propiedades cargadas para los gráficos de enriquecimiento. Ajusta los filtros.")
        return

    # ── b) Scatter: Score vs Distancia Metro ──────────────────────────────────
    st.markdown("### Oportunidad vs Acceso Metro")
    metro_df = df.dropna(subset=["dist_metro_km", "opportunity_score"])
    if metro_df.empty:
        st.info("Sin datos de distancia metro. Ejecuta el pipeline OSM (V4.2) primero.")
    else:
        fig_metro = px.scatter(
            metro_df,
            x="dist_metro_km",
            y="opportunity_score",
            color="city_zone",
            size="surface_m2",
            hover_data=["county_name", "project_type", "age"],
            title="Oportunidad vs Acceso Metro",
            labels={"dist_metro_km": "Distancia al Metro (km)", "opportunity_score": "Score de Oportunidad"},
        )
        st.plotly_chart(fig_metro, use_container_width=True)

    st.markdown("---")

    # ── c) Histogram: Distribución de antigüedad ──────────────────────────────
    st.markdown("### Distribución de antigüedad")
    age_df = df.dropna(subset=["age"])
    if age_df.empty:
        st.info("Sin datos de antigüedad. Ejecuta el pipeline de thesis features (V4.1) primero.")
    else:
        color_col = "construction_year_bucket" if "construction_year_bucket" in age_df.columns else None
        fig_age = px.histogram(
            age_df,
            x="age",
            color=color_col,
            title="Distribución de antigüedad por bucket de año de construcción",
            labels={"age": "Antigüedad (años)", "count": "N propiedades"},
            barmode="overlay",
        )
        st.plotly_chart(fig_age, use_container_width=True)

    st.markdown("---")

    # ── d) Scatter: Score vs Edad ─────────────────────────────────────────────
    st.markdown("### Score vs Edad de la propiedad")
    age_score_df = df.dropna(subset=["age", "opportunity_score"]).copy()
    if age_score_df.empty:
        st.info("Sin datos para el scatter de edad vs score.")
    else:
        # Preparar tooltip con identificación completa
        age_score_df["Dirección"] = age_score_df.apply(
            lambda r: f"{r.get('address','') or 'Sin dirección'}" +
                      (f" {r.get('apartment','')}" if r.get('apartment') else ""), axis=1)
        age_score_df["Rol SII"] = age_score_df.get("id_role", "N/D")
        age_score_df["Vendedor"] = age_score_df.get("seller_name", "N/D")
        age_score_df["Gap %"] = (age_score_df["gap_pct"] * 100).round(1)
        age_score_df["UF/m²"] = age_score_df["uf_m2_building"].round(1)

        hover_cols = [c for c in ["county_name","Dirección","Rol SII","Vendedor","Gap %","UF/m²","surface_m2"] if c in age_score_df.columns]
        try:
            fig_age_score = px.scatter(
                age_score_df, x="age", y="opportunity_score",
                color="project_type", trendline="ols",
                hover_data=hover_cols,
                title="Score de Oportunidad vs Edad — pasa el cursor sobre un punto para ver la dirección",
                labels={"age": "Antigüedad (años)", "opportunity_score": "Score de Oportunidad", "project_type": "Tipología"},
            )
        except Exception:
            fig_age_score = px.scatter(
                age_score_df, x="age", y="opportunity_score",
                color="project_type", hover_data=hover_cols,
                title="Score de Oportunidad vs Edad — pasa el cursor sobre un punto para ver la dirección",
                labels={"age": "Antigüedad (años)", "opportunity_score": "Score de Oportunidad", "project_type": "Tipología"},
            )
        st.plotly_chart(fig_age_score, use_container_width=True)

        # Tabla accionable debajo del scatter
        st.markdown("#### Listado de propiedades — ordena y filtra para actuar")
        tbl_cols = [c for c in ["Dirección","county_name","Rol SII","project_type","age",
                                 "UF/m²","Gap %","opportunity_score","Vendedor"] if c in age_score_df.columns]
        tbl = age_score_df[tbl_cols].rename(columns={
            "county_name":"Comuna","project_type":"Tipo",
            "age":"Antigüedad","opportunity_score":"Score"}).sort_values("Score", ascending=False)
        st.dataframe(tbl.head(200), use_container_width=True, hide_index=True,
                     column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=1, format="%.3f")})


# ── Tab: Calidad de datos ─────────────────────────────────────────────────────

def render_quality_tab():
    st.subheader("Calidad de datos y cobertura del modelo")
    try:
        q, s = load_data_quality()
    except Exception as e:
        st.error(f"Error: {e}")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Ingesta y limpieza**")
        total = int(q["total_clean"]) if q["total_clean"] else 0
        st.metric("Transacciones limpias", f"{total:,}")
        st.metric("Nulos en superficie", f"{int(q['null_surface']):,} ({int(q['null_surface'])/max(total,1)*100:.1f}%)")
        st.metric("Nulos en coordenadas", f"{int(q['null_coords']):,} ({int(q['null_coords'])/max(total,1)*100:.1f}%)")
        st.metric("Nulos en valor", f"{int(q['null_value']):,} ({int(q['null_value'])/max(total,1)*100:.1f}%)")
        st.metric("Confianza media", f"{float(q['mean_confidence']):.4f}")

    with col2:
        st.markdown("**Scoring del modelo**")
        total_s = int(s["total_scored"]) if s["total_scored"] else 0
        st.metric("Propiedades scoradas", f"{total_s:,}")
        st.metric("Score medio", f"{float(s['mean_score']):.4f}")
        st.metric("Alta oportunidad (>0.7)", f"{int(s['high_opp']):,} ({int(s['high_opp'])/max(total_s,1)*100:.1f}%)")
        st.metric("Modelo version", MODEL_VERSION)

    st.markdown("---")
    st.markdown("""
**Notas sobre el dataset:**
- Fuente: Conservador de Bienes Raíces (CBR) — Región Metropolitana, 2013-2014
- Los modelos son válidos para análisis metodológico; actualizar con datos frescos para uso productivo (V2)
- Real_Value normalizado a UF (detectión automática de escala CLP/UF)
- Coordenadas validadas dentro del bounding box de Chile
    """)


# ── Tab: Alertas ─────────────────────────────────────────────────────────────

def render_alerts_tab():
    st.subheader("Alertas de oportunidades")
    st.markdown("Ejecuta una consulta en tiempo real sobre `v_opportunities` para detectar propiedades que superan los umbrales definidos.")

    min_alert_score = st.slider("Score mínimo de alerta", 0.0, 1.0, 0.75, 0.05, key="alert_min_score")
    max_gap = st.slider("Gap mínimo (%)", -100, 0, -20, 5, key="alert_max_gap",
                        help="Valores negativos = precio real < precio predicho (subvalorado)")

    if st.button("Ejecutar alertas ahora"):
        try:
            engine = get_engine()
            query = f"""
                SELECT
                    vo.score_id,
                    vo.project_type,
                    vo.county_name,
                    vo.year,
                    vo.real_value_uf,
                    vo.uf_m2_building,
                    vo.predicted_uf_m2,
                    vo.gap_pct,
                    vo.opportunity_score,
                    vo.data_confidence
                FROM v_opportunities vo
                WHERE vo.opportunity_score >= {min_alert_score}
                  AND vo.gap_pct <= {max_gap / 100.0}
                  AND vo.latitude IS NOT NULL
                ORDER BY vo.opportunity_score DESC
                LIMIT 200
            """
            alert_df = pd.read_sql(query, engine)
            if alert_df.empty:
                st.warning("Sin oportunidades que cumplan los umbrales.")
            else:
                st.success(f"{len(alert_df)} alertas encontradas")
                alert_df["gap_pct_%"] = (alert_df["gap_pct"] * 100).round(1)
                alert_df["opportunity_score"] = alert_df["opportunity_score"].round(3)
                st.dataframe(
                    alert_df.drop(columns=["gap_pct"]).rename(columns={
                        "score_id": "ID",
                        "project_type": "Tipología",
                        "county_name": "Comuna",
                        "year": "Año",
                        "real_value_uf": "Valor UF",
                        "uf_m2_building": "UF/m² Real",
                        "predicted_uf_m2": "UF/m² Pred",
                        "gap_pct_%": "Gap %",
                        "opportunity_score": "Score",
                        "data_confidence": "Confianza",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as e:
            st.error(f"Error ejecutando alertas: {e}")
            st.info("Verifica que PostgreSQL esté corriendo y la vista v_opportunities exista.")


# ── Main ──────────────────────────────────────────────────────────────────────

def _apply_profile(df: pd.DataFrame, profile) -> pd.DataFrame:
    """Re-rank df using a scoring profile (in-memory, no DB write)."""
    if profile is None or df.empty:
        return df
    try:
        from src.scoring.scoring_profile import compute_profile_score
        # Rename score_id → id so compute_profile_score can find it
        df = df.rename(columns={"score_id": "id"})
        df = compute_profile_score(df, profile)
        df = df.rename(columns={"id": "score_id"})
        df = df.sort_values("opportunity_score", ascending=False)
    except Exception as e:
        import streamlit as st
        st.warning(f"No se pudo aplicar el perfil personalizado: {e}")
    return df


def main():
    st.title("RE_CL — Detección de Inmuebles Subvalorados")
    st.markdown("*Región Metropolitana de Santiago · Modelo hedónico XGBoost + SHAP*")

    sel_types, sel_communes, city_zones, min_score, scoring_profile = render_sidebar()

    tab_map, tab_rank, tab_communes, tab_land, tab_detail, tab_enrichment, tab_quality, tab_finance, tab_alerts = st.tabs([
        "Mapa", "Ranking", "Comunas", "🌿 Terrenos", "Ficha", "Enriquecimiento", "Calidad", "Finanzas", "Alertas"
    ])

    df = pd.DataFrame()
    if sel_types and sel_communes:
        try:
            with st.spinner("Cargando datos..."):
                # Load with low min_score so profile re-ranking has enough data
                load_min = min(min_score, 0.3)
                df = load_opportunities(
                    tuple(sel_types), tuple(sel_communes), load_min,
                    city_zones=tuple(city_zones)
                )

            # Apply scoring profile in-memory
            if scoring_profile is not None:
                with st.spinner("Aplicando perfil de scoring..."):
                    df = _apply_profile(df, scoring_profile)
                # Filter by user's min_score after re-ranking
                df = df[df["opportunity_score"] >= min_score]

        except Exception as e:
            st.error(f"Error de base de datos: {e}")
            st.info("Verifica que PostgreSQL esté corriendo y las variables de entorno (.env) estén configuradas.")

    # Show active profile banner
    if scoring_profile is not None and not df.empty:
        profile_name = getattr(scoring_profile, "name", "custom")
        st.info(f"Perfil activo: **{profile_name}** — scores recalculados en memoria con pesos personalizados.")

    with tab_map:
        render_map_tab(df)

    with tab_rank:
        render_ranking_tab(df)

    with tab_communes:
        render_communes_tab(df)

    with tab_land:
        render_land_tab()

    with tab_detail:
        render_detail_tab(df)

    with tab_enrichment:
        render_enrichment_tab(df)

    with tab_quality:
        render_quality_panel(get_engine())

    with tab_alerts:
        render_alerts_tab()

    with tab_finance:
        selected_row = None
        if not df.empty:
            score_ids = df["score_id"].tolist()
            fin_col, _ = st.columns([3, 1])
            with fin_col:
                sel_fin_id = st.selectbox(
                    "Propiedad de referencia (opcional)",
                    options=[None] + score_ids[:100],
                    format_func=lambda x: "— Sin selección (modo standalone) —" if x is None else str(x),
                    key="fin_selected_id",
                )
            if sel_fin_id is not None:
                selected_row = df[df["score_id"] == sel_fin_id].iloc[0].to_dict()

        render_financial_panel(property_row=selected_row)


if __name__ == "__main__":
    main()
