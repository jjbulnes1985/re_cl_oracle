"""
quality_panel.py
----------------
Comprehensive data quality panel for the RE_CL Streamlit dashboard.

Tabs:
  1. Cobertura    — pipeline row counts + null rates for key columns
  2. Distribuciones — score/gap/confidence/year-bucket distributions
  3. Validación Modelo — backtesting metrics + commune calibration
  4. OSM Coverage — fraction of properties with each OSM feature
"""

import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ── Cached queries ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_pipeline_counts(_engine):
    """Row counts for each stage of the pipeline."""
    query = """
        SELECT
            (SELECT COUNT(*) FROM transactions_raw)                              AS raw_count,
            (SELECT COUNT(*) FROM transactions_clean)                            AS clean_count,
            (SELECT COUNT(*) FROM transactions_clean WHERE is_outlier = FALSE)   AS clean_valid,
            (SELECT COUNT(*) FROM transaction_features)                          AS features_count,
            (SELECT COUNT(*) FROM model_scores)                                  AS scores_count,
            (SELECT COUNT(*) FROM scraped_listings)                              AS scraped_count
    """
    row = pd.read_sql(query, _engine).iloc[0]
    return {k: int(v) if v is not None else 0 for k, v in row.items()}


@st.cache_data(ttl=300)
def _load_null_rates(_engine):
    """Null rates for key columns in transactions_clean."""
    query = """
        SELECT
            COUNT(*)                                                AS total,
            COUNT(*) FILTER (WHERE latitude IS NULL)               AS null_latitude,
            COUNT(*) FILTER (WHERE longitude IS NULL)              AS null_longitude,
            COUNT(*) FILTER (WHERE construction_year IS NULL)      AS null_construction_year,
            COUNT(*) FILTER (WHERE surface_m2 IS NULL)             AS null_surface_m2,
            COUNT(*) FILTER (WHERE uf_m2_building IS NULL)         AS null_uf_m2_building
        FROM transactions_clean
    """
    row = pd.read_sql(query, _engine).iloc[0]
    total = int(row["total"]) if row["total"] else 1
    cols = ["latitude", "longitude", "construction_year", "surface_m2", "uf_m2_building"]
    result = []
    for col in cols:
        null_n = int(row[f"null_{col}"])
        result.append({
            "Columna": col,
            "Nulos": null_n,
            "Cobertura %": round((total - null_n) / total * 100, 2),
        })
    return pd.DataFrame(result), total


@st.cache_data(ttl=300)
def _load_score_distribution(_engine):
    """opportunity_score distribution."""
    query = """
        SELECT opportunity_score
        FROM model_scores
        WHERE opportunity_score IS NOT NULL
    """
    return pd.read_sql(query, _engine)


@st.cache_data(ttl=300)
def _load_gap_by_type(_engine):
    """gap_pct by project_type from transaction_features + model_scores."""
    query = """
        SELECT
            tc.project_type AS project_type,
            tf.gap_pct
        FROM transaction_features tf
        JOIN transactions_clean tc ON tc.id = tf.clean_id
        WHERE tf.gap_pct IS NOT NULL
          AND tc.project_type IS NOT NULL
    """
    return pd.read_sql(query, _engine)


@st.cache_data(ttl=300)
def _load_confidence_vs_score(_engine):
    """data_confidence vs opportunity_score for scatter plot."""
    query = """
        SELECT
            tc.data_confidence,
            ms.opportunity_score
        FROM model_scores ms
        JOIN transactions_clean tc ON tc.id = ms.clean_id
        WHERE ms.opportunity_score IS NOT NULL
          AND tc.data_confidence IS NOT NULL
        LIMIT 20000
    """
    return pd.read_sql(query, _engine)


@st.cache_data(ttl=300)
def _load_year_bucket_dist(_engine):
    """Distribution of construction_year_bucket."""
    query = """
        SELECT
            construction_year_bucket,
            COUNT(*) AS n
        FROM transaction_features
        WHERE construction_year_bucket IS NOT NULL
        GROUP BY construction_year_bucket
        ORDER BY construction_year_bucket
    """
    return pd.read_sql(query, _engine)


@st.cache_data(ttl=300)
def _load_osm_coverage(_engine):
    """Fraction of properties with each OSM feature."""
    query = """
        SELECT
            COUNT(*) FILTER (WHERE dist_metro_km IS NOT NULL)    AS has_metro,
            COUNT(*) FILTER (WHERE dist_school_km IS NOT NULL)   AS has_school,
            COUNT(*) FILTER (WHERE amenities_500m IS NOT NULL)   AS has_amenities,
            COUNT(*)                                             AS total
        FROM transaction_features
    """
    row = pd.read_sql(query, _engine).iloc[0]
    total = int(row["total"]) if row["total"] else 1
    features = ["has_metro", "has_school", "has_amenities"]
    labels = ["Metro", "Colegio", "Amenidades 500m"]
    result = []
    for feat, label in zip(features, labels):
        n = int(row[feat])
        result.append({
            "Feature": label,
            "N propiedades": n,
            "Cobertura %": round(n / total * 100, 2),
        })
    return pd.DataFrame(result), total


@st.cache_data(ttl=300)
def _load_osm_distributions(_engine):
    """Distributions for dist_metro_km and amenities_500m."""
    metro_query = """
        SELECT dist_metro_km
        FROM transaction_features
        WHERE dist_metro_km IS NOT NULL
        LIMIT 50000
    """
    amenities_query = """
        SELECT amenities_500m
        FROM transaction_features
        WHERE amenities_500m IS NOT NULL
        LIMIT 50000
    """
    metro_df = pd.read_sql(metro_query, _engine)
    amenities_df = pd.read_sql(amenities_query, _engine)
    return metro_df, amenities_df


# ── Tab renderers ──────────────────────────────────────────────────────────────

def render_coverage_tab(engine):
    """Pipeline flow diagram + null rates."""
    st.subheader("Cobertura del pipeline")

    # 1. Pipeline flow
    try:
        counts = _load_pipeline_counts(engine)
    except Exception as e:
        st.error(f"Error cargando conteos: {e}")
        counts = {}

    if counts:
        stages = [
            ("transactions_raw",    "Raw",           counts.get("raw_count", 0),      "#90CAF9"),
            ("transactions_clean",  "Clean (total)", counts.get("clean_count", 0),     "#80DEEA"),
            ("clean (sin outliers)","Clean (validos)",counts.get("clean_valid", 0),    "#A5D6A7"),
            ("transaction_features","Features",      counts.get("features_count", 0),  "#FFF176"),
            ("model_scores",        "Scores",        counts.get("scores_count", 0),    "#FFAB91"),
            ("scraped_listings",    "Scraped",       counts.get("scraped_count", 0),   "#CE93D8"),
        ]

        cols = st.columns(len(stages))
        for i, (table, label, val, color) in enumerate(stages):
            with cols[i]:
                st.markdown(
                    f"""
                    <div style="background:{color};border-radius:8px;padding:12px;text-align:center;">
                      <div style="font-size:11px;color:#333;font-weight:600">{label}</div>
                      <div style="font-size:22px;font-weight:700;color:#111">{val:,}</div>
                      <div style="font-size:10px;color:#555">{table}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if i < len(stages) - 1:
                    # Arrow rendered between columns via caption below
                    pass

        # Retention rates
        raw = counts.get("raw_count", 1) or 1
        st.markdown("---")
        ret_cols = st.columns(4)
        with ret_cols[0]:
            retention = counts.get("clean_count", 0) / raw * 100
            st.metric("Retención raw → clean", f"{retention:.1f}%")
        with ret_cols[1]:
            ret2 = counts.get("clean_valid", 0) / max(counts.get("clean_count", 1), 1) * 100
            st.metric("Clean sin outliers", f"{ret2:.1f}%")
        with ret_cols[2]:
            ret3 = counts.get("features_count", 0) / max(counts.get("clean_valid", 1), 1) * 100
            st.metric("Con features", f"{ret3:.1f}%")
        with ret_cols[3]:
            ret4 = counts.get("scores_count", 0) / max(counts.get("features_count", 1), 1) * 100
            st.metric("Scorados", f"{ret4:.1f}%")

    st.markdown("---")

    # 2. Null rates
    st.subheader("Tasas de nulos en transactions_clean")
    try:
        null_df, total = _load_null_rates(engine)
        st.caption(f"Total registros en transactions_clean: **{total:,}**")

        fig = px.bar(
            null_df,
            x="Columna",
            y="Cobertura %",
            color="Cobertura %",
            color_continuous_scale=["#EF5350", "#FFA726", "#66BB6A"],
            range_color=[0, 100],
            text="Cobertura %",
            title="Cobertura por columna clave (% registros no nulos)",
        )
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(yaxis_range=[0, 105], coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(null_df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Error cargando tasas de nulos: {e}")


def render_distributions_tab(engine):
    """Score, gap, confidence, and year-bucket distributions."""
    st.subheader("Distribuciones")

    # 1. Opportunity score histogram
    st.markdown("### Distribución de opportunity_score")
    try:
        score_df = _load_score_distribution(engine)
        if score_df.empty:
            st.info("Sin scores disponibles.")
        else:
            fig = px.histogram(
                score_df,
                x="opportunity_score",
                nbins=20,
                title="Distribución de Opportunity Scores",
                color_discrete_sequence=["#3b82f6"],
                template="plotly_dark",
            )
            fig.update_layout(bargap=0.1)
            fig.add_vline(x=score_df["opportunity_score"].median(), line_dash="dash",
                          line_color="orange", annotation_text=f"Mediana: {score_df['opportunity_score'].median():.3f}")
            fig.add_vline(x=0.7, line_dash="dot", line_color="red",
                          annotation_text="Umbral >0.7")
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Error cargando distribución de scores: {e}")

    st.markdown("---")

    # 2. Box plot gap_pct by project_type
    st.markdown("### Box plot: gap_pct por tipología")
    try:
        gap_df = _load_gap_by_type(engine)
        if gap_df.empty:
            st.info("Sin datos de gap_pct por tipología.")
        else:
            fig2 = px.box(
                gap_df,
                x="project_type",
                y="gap_pct",
                color="project_type",
                title="Distribución de gap_pct por tipo de proyecto",
                labels={"project_type": "Tipología", "gap_pct": "Gap % (brecha precio)"},
            )
            fig2.update_layout(showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)
    except Exception as e:
        st.error(f"Error cargando gap por tipo: {e}")

    st.markdown("---")

    # 3. Scatter: data_confidence vs opportunity_score
    st.markdown("### Confianza de datos vs Score de oportunidad")
    try:
        conf_df = _load_confidence_vs_score(engine)
        if conf_df.empty:
            st.info("Sin datos para el scatter de confianza vs score.")
        else:
            fig3 = px.scatter(
                conf_df.sample(min(5000, len(conf_df)), random_state=42),
                x="data_confidence",
                y="opportunity_score",
                opacity=0.35,
                title="data_confidence vs opportunity_score",
                labels={
                    "data_confidence": "Confianza de datos",
                    "opportunity_score": "Opportunity Score",
                },
                color_discrete_sequence=["#00897B"],
            )
            st.plotly_chart(fig3, use_container_width=True)
    except Exception as e:
        st.error(f"Error cargando scatter de confianza: {e}")

    st.markdown("---")

    # 4. Bar chart: construction_year_bucket
    st.markdown("### Distribución por bucket de año de construcción")
    try:
        bucket_df = _load_year_bucket_dist(engine)
        if bucket_df.empty:
            st.info("Sin datos de construction_year_bucket. Ejecuta las features de thesis (V4.1).")
        else:
            fig4 = px.bar(
                bucket_df,
                x="construction_year_bucket",
                y="n",
                title="Propiedades por bucket de año de construcción",
                labels={"construction_year_bucket": "Bucket de año", "n": "N propiedades"},
                color="n",
                color_continuous_scale="Blues",
            )
            fig4.update_layout(coloraxis_showscale=False)
            st.plotly_chart(fig4, use_container_width=True)
    except Exception as e:
        st.error(f"Error cargando distribución de year_bucket: {e}")


def render_model_validation_tab():
    """Backtesting metrics and commune calibration."""
    st.subheader("Validación del modelo (backtesting walk-forward)")

    # Resolve path relative to repo root (works both locally and in Docker /app)
    # quality_panel.py lives at <repo>/src/dashboard/quality_panel.py → parents[2] = repo root
    _repo_root = Path(os.getenv("REPO_ROOT", Path(__file__).resolve().parents[2]))
    report_path = _repo_root / "data" / "exports" / "backtesting_report.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as e:
            st.error(f"Error leyendo backtesting_report.json: {e}")
            return

        temporal = report.get("temporal", {})

        # Main metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            r2_val = temporal.get("r2")
            st.metric("R² (test 2014)", f"{r2_val:.3f}" if r2_val is not None else "N/A")
        with col2:
            rmse_val = temporal.get("rmse")
            st.metric("RMSE (UF/m²)", f"{rmse_val:.2f}" if rmse_val is not None else "N/A")
        with col3:
            mae_val = temporal.get("mae")
            st.metric("MAE (UF/m²)", f"{mae_val:.2f}" if mae_val is not None else "N/A")

        # Extra metrics if available
        extra_keys = [k for k in temporal if k not in ("r2", "rmse", "mae")]
        if extra_keys:
            st.markdown("**Métricas adicionales**")
            extra_cols = st.columns(min(len(extra_keys), 4))
            for i, key in enumerate(extra_keys[:4]):
                val = temporal[key]
                extra_cols[i].metric(key, f"{val:.4f}" if isinstance(val, float) else str(val))

        # OLS comparison if present
        ols = report.get("ols_comparison")
        if ols:
            st.markdown("---")
            st.markdown("### Comparación XGBoost vs OLS")
            ols_data = []
            for model_name, metrics in ols.items():
                row = {"Modelo": model_name}
                row.update(metrics)
                ols_data.append(row)
            if ols_data:
                st.dataframe(pd.DataFrame(ols_data), use_container_width=True, hide_index=True)

        st.markdown("---")

        # Commune calibration
        calib_path = _repo_root / "data" / "exports" / "commune_calibration.csv"
        if calib_path.exists():
            try:
                calib_df = pd.read_csv(calib_path)
                st.subheader("Calibración por comuna (Top 10 sesgos)")

                if "abs_bias_pct" in calib_df.columns:
                    top10 = calib_df.sort_values("abs_bias_pct", ascending=False).head(10)
                else:
                    top10 = calib_df.head(10)

                st.dataframe(top10, use_container_width=True, hide_index=True)

                # Bar chart of commune bias
                if "abs_bias_pct" in calib_df.columns and "county_name" in calib_df.columns:
                    fig = px.bar(
                        top10,
                        x="county_name",
                        y="abs_bias_pct",
                        title="Top 10 comunas con mayor sesgo de calibración",
                        labels={"county_name": "Comuna", "abs_bias_pct": "Sesgo absoluto (%)"},
                        color="abs_bias_pct",
                        color_continuous_scale="RdYlGn_r",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"Error leyendo commune_calibration.csv: {e}")
        else:
            st.info("Sin commune_calibration.csv. Ejecuta: `py src/backtesting/walk_forward.py --commune`")

        # Full report JSON expander
        with st.expander("Ver reporte completo (JSON)"):
            st.json(report)

    else:
        st.info("No se encontró backtesting_report.json.")
        st.code("py src/backtesting/walk_forward.py", language="bash")
        st.markdown("""
**Qué genera el backtesting:**
- Entrenamiento en datos 2013 → predicción en 2014
- Métricas: R², RMSE, MAE para el modelo XGBoost
- Comparación con benchmark OLS (regresión lineal)
- Calibración por comuna: sesgo sistemático por zona geográfica
        """)


def render_osm_coverage_tab(engine):
    """OSM feature coverage and distributions."""
    st.subheader("Cobertura OSM")

    # 1. Coverage percentages
    try:
        osm_df, total = _load_osm_coverage(engine)
        st.caption(f"Total propiedades en transaction_features: **{total:,}**")

        if osm_df["N propiedades"].sum() == 0:
            st.info(
                "Sin datos OSM. Ejecuta el pipeline de enriquecimiento OSM (V4.2): "
                "`py src/features/build_features.py`"
            )
        else:
            # Percentage bars
            fig = px.bar(
                osm_df,
                x="Feature",
                y="Cobertura %",
                color="Cobertura %",
                color_continuous_scale=["#EF5350", "#FFA726", "#66BB6A"],
                range_color=[0, 100],
                text="Cobertura %",
                title="Cobertura de features OSM (% propiedades con dato)",
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(yaxis_range=[0, 110], coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

            col1, col2, col3 = st.columns(3)
            for i, row in osm_df.iterrows():
                target_col = [col1, col2, col3][i % 3]
                with target_col:
                    st.metric(row["Feature"], f"{row['Cobertura %']:.1f}%", f"{row['N propiedades']:,} props")

    except Exception as e:
        st.error(f"Error cargando cobertura OSM: {e}")

    st.markdown("---")

    # 2. Distributions
    try:
        metro_df, amenities_df = _load_osm_distributions(engine)

        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("### Distribución: distancia al metro (km)")
            if metro_df.empty:
                st.info("Sin datos de dist_metro_km.")
            else:
                fig_metro = px.histogram(
                    metro_df,
                    x="dist_metro_km",
                    nbins=40,
                    title="Distancia al metro (km)",
                    labels={"dist_metro_km": "Distancia al Metro (km)", "count": "N propiedades"},
                    color_discrete_sequence=["#1565C0"],
                )
                fig_metro.add_vline(
                    x=metro_df["dist_metro_km"].median(), line_dash="dash", line_color="orange",
                    annotation_text=f"Mediana: {metro_df['dist_metro_km'].median():.2f} km"
                )
                st.plotly_chart(fig_metro, use_container_width=True)

                c1, c2, c3 = st.columns(3)
                c1.metric("Mediana", f"{metro_df['dist_metro_km'].median():.2f} km")
                c2.metric("P25", f"{metro_df['dist_metro_km'].quantile(0.25):.2f} km")
                c3.metric("P75", f"{metro_df['dist_metro_km'].quantile(0.75):.2f} km")

        with col_right:
            st.markdown("### Distribución: amenidades en 500m")
            if amenities_df.empty:
                st.info("Sin datos de amenities_500m.")
            else:
                fig_amenities = px.histogram(
                    amenities_df,
                    x="amenities_500m",
                    nbins=30,
                    title="Amenidades en radio de 500m",
                    labels={"amenities_500m": "N amenidades", "count": "N propiedades"},
                    color_discrete_sequence=["#2E7D32"],
                )
                st.plotly_chart(fig_amenities, use_container_width=True)

                c1, c2, c3 = st.columns(3)
                c1.metric("Mediana", f"{amenities_df['amenities_500m'].median():.0f}")
                c2.metric("P25", f"{amenities_df['amenities_500m'].quantile(0.25):.0f}")
                c3.metric("P75", f"{amenities_df['amenities_500m'].quantile(0.75):.0f}")

    except Exception as e:
        st.error(f"Error cargando distribuciones OSM: {e}")


# ── Main entry point ───────────────────────────────────────────────────────────

def render_quality_panel(engine):
    """Main data quality dashboard — call from app.py tab block."""
    st.header("Calidad de Datos")

    qtab1, qtab2, qtab3, qtab4 = st.tabs([
        "Cobertura", "Distribuciones", "Validacion Modelo", "OSM Coverage"
    ])

    with qtab1:
        render_coverage_tab(engine)
    with qtab2:
        render_distributions_tab(engine)
    with qtab3:
        render_model_validation_tab()
    with qtab4:
        render_osm_coverage_tab(engine)
