# %% [markdown]
# # RE_CL — Análisis Exploratorio de Datos
#
# Plataforma de detección de inmuebles subvalorados en Chile (RM Santiago, CBR 2013-2014).
#
# **Ejecutar desde:** directorio `re_cl/` (para que los imports `src.*` funcionen)
#
# ```bash
# cd re_cl
# python notebooks/01_exploratory_analysis.py
# # O en VS Code: abrir con la extensión Jupyter, correr celda por celda
# ```
#
# **Secciones:**
# 1. Setup & DB Connection
# 2. Resumen del dataset
# 3. Distribución de precios
# 4. Geografía
# 5. Análisis por comuna
# 6. Gap analysis
# 7. Features del modelo (correlación)
# 8. Score analysis + SHAP
# 9. Antigüedad
# 10. OSM coverage

# %% [markdown]
# ## 1. Setup & DB Connection

# %%
import os
import sys
import warnings

warnings.filterwarnings("ignore")

# Si ejecutas desde notebooks/, agrega re_cl/ al path
# Si ejecutas desde re_cl/, esto es un no-op
_nb_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else os.getcwd()
_root = os.path.dirname(_nb_dir) if os.path.basename(_nb_dir) == "notebooks" else _nb_dir
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv

# Busca .env en re_cl/ independientemente de desde dónde se ejecuta
_env_path = os.path.join(_root, ".env")
load_dotenv(_env_path)
print(f"[setup] Cargando .env desde: {_env_path}")
print(f"[setup] DATABASE_URL presente: {'DATABASE_URL' in os.environ or 'POSTGRES_PASSWORD' in os.environ}")

# %%
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import seaborn as sns

# Configuración de visualización
matplotlib.rcParams["figure.figsize"] = (12, 5)
matplotlib.rcParams["figure.dpi"] = 100
matplotlib.rcParams["font.size"] = 11
sns.set_theme(style="whitegrid", palette="muted")

print(f"[setup] pandas {pd.__version__}, numpy {np.__version__}, matplotlib {matplotlib.__version__}")

# %%
from sqlalchemy import create_engine, text

def build_database_url() -> str:
    """
    Construye la URL de conexion a PostgreSQL desde variables de entorno.
    Prioridad: DATABASE_URL completa > variables individuales POSTGRES_*.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pw   = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"

DATABASE_URL = build_database_url()
# Ocultar contraseña en el print
_safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
print(f"[db] Conectando a: ...@{_safe_url}")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Test de conexion
try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version()")).scalar()
    print(f"[db] OK — {result[:60]}...")
except Exception as e:
    print(f"[db] ERROR de conexion: {e}")
    print("     Asegurate de tener docker-compose up -d y .env configurado.")
    raise

# %% [markdown]
# ## 2. Resumen del Dataset

# %%
# Conteo de filas por tabla principal
TABLES = [
    "transactions_raw",
    "transactions_clean",
    "transaction_features",
    "model_scores",
    "commune_stats",
    "scraped_listings",
]

print("=" * 55)
print(f"{'Tabla':<30} {'Filas':>12} {'Estado'}")
print("=" * 55)

table_counts = {}
for tbl in TABLES:
    try:
        with engine.connect() as conn:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        table_counts[tbl] = n
        bar = "#" * min(int(n / max(1, max(table_counts.values()) / 20)), 20)
        print(f"  {tbl:<28} {n:>12,}  {bar}")
    except Exception as ex:
        table_counts[tbl] = 0
        print(f"  {tbl:<28} {'N/A':>12}  (tabla no existe o vacia)")

print("=" * 55)

# %%
# Rangos temporales y comunas cubiertas
with engine.connect() as conn:
    temporal = conn.execute(text("""
        SELECT
            MIN(inscription_date)       AS fecha_min,
            MAX(inscription_date)       AS fecha_max,
            COUNT(DISTINCT year)        AS n_anios,
            COUNT(DISTINCT county_name) AS n_comunas,
            COUNT(DISTINCT project_type) AS n_tipos
        FROM transactions_clean
    """)).fetchone()

print("\n--- Cobertura temporal y geografica ---")
print(f"  Fecha minima   : {temporal[0]}")
print(f"  Fecha maxima   : {temporal[1]}")
print(f"  Anos cubiertos : {temporal[2]}")
print(f"  Comunas        : {temporal[3]}")
print(f"  Tipos proyecto : {temporal[4]}")

# %%
# Distribución de project_type en transacciones limpias
df_types = pd.read_sql("""
    SELECT project_type,
           COUNT(*) AS n,
           ROUND(AVG(data_confidence)::numeric, 3) AS avg_confidence
    FROM transactions_clean
    GROUP BY project_type
    ORDER BY n DESC
""", engine)

print("\n--- Tipos de proyecto ---")
print(df_types.to_string(index=False))

# %% [markdown]
# ## 3. Distribución de Precios (UF/m²)

# %%
# Cargamos muestra para exploración — limitamos a 50k para rapidez
SAMPLE_SIZE = 50_000

df = pd.read_sql(f"""
    SELECT
        tc.project_type,
        tc.county_name,
        tc.year,
        tc.quarter,
        tc.uf_m2_building,
        tc.uf_m2_land,
        tc.surface_m2,
        tc.surface_building_m2,
        tc.data_confidence,
        tc.real_value_uf,
        tc.calculated_value_uf,
        ST_X(tc.geom) AS longitude,
        ST_Y(tc.geom) AS latitude,
        ms.opportunity_score,
        ms.undervaluation_score,
        ms.gap_pct,
        ms.gap_percentile,
        ms.predicted_uf_m2
    FROM transactions_clean tc
    LEFT JOIN model_scores ms ON ms.clean_id = tc.id
    WHERE tc.is_outlier = FALSE
      AND tc.has_valid_coords = TRUE
      AND tc.has_valid_price = TRUE
      AND tc.uf_m2_building IS NOT NULL
    ORDER BY RANDOM()
    LIMIT {SAMPLE_SIZE}
""", engine)

print(f"[datos] Muestra cargada: {len(df):,} filas")
df.head()

# %%
# Histograma de UF/m² con estadísticas
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Panel izquierdo: histograma general
ax = axes[0]
data_plot = df["uf_m2_building"].dropna()
data_plot = data_plot[data_plot.between(data_plot.quantile(0.01), data_plot.quantile(0.99))]
ax.hist(data_plot, bins=60, color="#2196F3", alpha=0.8, edgecolor="white", linewidth=0.4)
ax.axvline(data_plot.median(), color="#E53935", linestyle="--", linewidth=1.5, label=f"Mediana: {data_plot.median():.1f}")
ax.axvline(data_plot.mean(),   color="#FF6F00", linestyle=":",  linewidth=1.5, label=f"Media: {data_plot.mean():.1f}")
ax.set_xlabel("UF/m² construido")
ax.set_ylabel("Frecuencia")
ax.set_title("Distribución global de precio (UF/m²)\n(p1–p99, outliers excluidos)")
ax.legend()

# Panel derecho: box plot por project_type
ax2 = axes[1]
top_types = df["project_type"].value_counts().head(5).index.tolist()
df_box = df[df["project_type"].isin(top_types)].copy()
df_box = df_box[df_box["uf_m2_building"].between(
    df_box["uf_m2_building"].quantile(0.02),
    df_box["uf_m2_building"].quantile(0.98)
)]
df_box.boxplot(column="uf_m2_building", by="project_type", ax=ax2, notch=False,
               patch_artist=True,
               boxprops=dict(facecolor="#90CAF9", color="#1565C0"),
               medianprops=dict(color="#E53935", linewidth=2))
ax2.set_xlabel("Tipo de proyecto")
ax2.set_ylabel("UF/m²")
ax2.set_title("Precio por tipo de proyecto (p2–p98)")
plt.suptitle("")
plt.tight_layout()
plt.savefig(os.path.join(_root, "data/exports/eda_01_precio_distribucion.png"), dpi=100, bbox_inches="tight")
plt.show()
print("[ok] Guardado: data/exports/eda_01_precio_distribucion.png")

# %%
# Estadísticas descriptivas por tipo
print("--- Estadísticas de UF/m² por project_type ---")
stats = (
    df.groupby("project_type")["uf_m2_building"]
    .agg(["count", "median", "mean", "std",
          lambda x: x.quantile(0.25),
          lambda x: x.quantile(0.75)])
    .rename(columns={
        "count": "n",
        "median": "mediana",
        "mean": "media",
        "std": "desv_est",
        "<lambda_0>": "p25",
        "<lambda_1>": "p75",
    })
    .sort_values("mediana", ascending=False)
    .round(2)
)
print(stats.to_string())

# %% [markdown]
# ## 4. Geografía — Scatter lat/lon por Opportunity Score

# %%
# Filtramos solo filas con score calculado y coordenadas válidas
df_geo = df.dropna(subset=["latitude", "longitude", "opportunity_score"]).copy()

# Validar rango coordenadas RM Santiago
df_geo = df_geo[
    df_geo["latitude"].between(-34.4, -33.0) &
    df_geo["longitude"].between(-71.2, -70.4)
]
print(f"[geo] Filas con score y coords válidas en RM: {len(df_geo):,}")

# %%
fig, ax = plt.subplots(figsize=(10, 10))

# Colormap: azul=bajo score, rojo=alto score (oportunidad)
cmap = plt.cm.RdYlGn_r   # verde=bajo score, rojo=alto score
scatter = ax.scatter(
    df_geo["longitude"],
    df_geo["latitude"],
    c=df_geo["opportunity_score"],
    cmap=cmap,
    s=2,
    alpha=0.5,
    vmin=0,
    vmax=1,
)

cbar = plt.colorbar(scatter, ax=ax, fraction=0.03, pad=0.02)
cbar.set_label("Opportunity Score (0=bajo, 1=alto)", fontsize=10)

ax.set_xlabel("Longitud")
ax.set_ylabel("Latitud")
ax.set_title(f"Propiedades RM Santiago — Coloreadas por Opportunity Score\n(muestra {len(df_geo):,} props)")
ax.set_aspect("equal")

plt.tight_layout()
plt.savefig(os.path.join(_root, "data/exports/eda_02_mapa_scatter.png"), dpi=120, bbox_inches="tight")
plt.show()
print("[ok] Guardado: data/exports/eda_02_mapa_scatter.png")

# %% [markdown]
# ## 5. Análisis por Comuna

# %%
# Top 15 comunas por score mediano (solo comunas con >= 50 propiedades con score)
df_comunas = pd.read_sql("""
    SELECT
        tc.county_name                                    AS comuna,
        COUNT(ms.id)                                      AS n_scored,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP
              (ORDER BY ms.opportunity_score)::numeric, 4) AS score_mediano,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP
              (ORDER BY tc.uf_m2_building)::numeric, 2)    AS uf_m2_mediano,
        ROUND(AVG(tc.data_confidence)::numeric, 3)        AS avg_confidence,
        ROUND(100.0 * SUM(CASE WHEN ms.gap_pct < -0.10 THEN 1 ELSE 0 END)
              / COUNT(ms.id), 1)                           AS pct_subvaloradas
    FROM transactions_clean tc
    JOIN model_scores ms ON ms.clean_id = tc.id
    WHERE tc.is_outlier = FALSE
      AND tc.has_valid_price = TRUE
    GROUP BY tc.county_name
    HAVING COUNT(ms.id) >= 50
    ORDER BY score_mediano DESC
    LIMIT 20
""", engine)

print(f"[comunas] {len(df_comunas)} comunas con >= 50 propiedades scoradas")
print(df_comunas.to_string(index=False))

# %%
# Bar chart top 10 comunas por score mediano
top10 = df_comunas.head(10).sort_values("score_mediano")

fig, axes = plt.subplots(1, 2, figsize=(16, 6))

# Panel izq: score mediano
ax = axes[0]
colors = plt.cm.RdYlGn(np.linspace(0.2, 0.8, len(top10)))[::-1]
bars = ax.barh(top10["comuna"], top10["score_mediano"], color=colors, edgecolor="white")
ax.set_xlabel("Opportunity Score mediano")
ax.set_title("Top 10 Comunas por Score Mediano")
ax.set_xlim(0, 1)
for bar, val in zip(bars, top10["score_mediano"]):
    ax.text(val + 0.01, bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}", va="center", fontsize=9)

# Panel der: % propiedades subvaloradas
ax2 = axes[1]
top10_sorted = top10.sort_values("pct_subvaloradas")
bars2 = ax2.barh(top10_sorted["comuna"], top10_sorted["pct_subvaloradas"],
                  color="#EF5350", alpha=0.8, edgecolor="white")
ax2.set_xlabel("% Propiedades subvaloradas (gap < -10%)")
ax2.set_title("% Subvaloradas por Comuna (Top 10 por Score)")
for bar, val in zip(bars2, top10_sorted["pct_subvaloradas"]):
    ax2.text(val + 0.3, bar.get_y() + bar.get_height() / 2,
             f"{val:.1f}%", va="center", fontsize=9)

plt.tight_layout()
plt.savefig(os.path.join(_root, "data/exports/eda_03_comunas_ranking.png"), dpi=100, bbox_inches="tight")
plt.show()
print("[ok] Guardado: data/exports/eda_03_comunas_ranking.png")

# %% [markdown]
# ## 6. Gap Analysis — Brecha precio real vs. valor calculado

# %%
# gap_pct = (real - calculado) / calculado
# Negativo = propiedad transada por MENOS que su valor calculado = subvalorada
df_gap = df.dropna(subset=["gap_pct"]).copy()
print(f"[gap] Filas con gap_pct: {len(df_gap):,}")
print(f"  Subvaloradas (gap < 0)   : {(df_gap['gap_pct'] < 0).sum():,} ({100*(df_gap['gap_pct'] < 0).mean():.1f}%)")
print(f"  Subvaloradas fuerte(<-10%): {(df_gap['gap_pct'] < -0.10).sum():,} ({100*(df_gap['gap_pct'] < -0.10).mean():.1f}%)")
print(f"  Sobrevaloradas (gap > 0) : {(df_gap['gap_pct'] > 0).sum():,} ({100*(df_gap['gap_pct'] > 0).mean():.1f}%)")
print(f"\n  Media gap_pct  : {df_gap['gap_pct'].mean():.4f}")
print(f"  Mediana gap_pct: {df_gap['gap_pct'].median():.4f}")
print(f"  p10 / p90      : {df_gap['gap_pct'].quantile(0.10):.4f} / {df_gap['gap_pct'].quantile(0.90):.4f}")

# %%
fig, axes = plt.subplots(1, 2, figsize=(16, 5))

# Panel izq: histograma gap_pct
ax = axes[0]
gap_data = df_gap["gap_pct"].clip(-1.5, 1.5)
n_bins = 80
ax.hist(gap_data[gap_data < 0], bins=n_bins // 2, color="#E53935", alpha=0.75,
        label="Subvaloradas (gap < 0)", density=True)
ax.hist(gap_data[gap_data >= 0], bins=n_bins // 2, color="#1E88E5", alpha=0.75,
        label="Sobrevaloradas (gap >= 0)", density=True)
ax.axvline(0, color="black", linewidth=1.5, linestyle="--")
ax.axvline(-0.10, color="#FF6F00", linewidth=1.2, linestyle=":",
           label="Umbral -10% (subvaloración significativa)")
ax.set_xlabel("gap_pct (winsorizado ±150%)")
ax.set_ylabel("Densidad")
ax.set_title("Distribución del Gap Price\n(negativo = subvalorado)")
ax.legend(fontsize=9)

# Panel der: gap_pct por tipo de proyecto
ax2 = axes[1]
top_types = df_gap["project_type"].value_counts().head(5).index.tolist()
gap_by_type = [df_gap.loc[df_gap["project_type"] == t, "gap_pct"].clip(-1, 1).dropna().values
               for t in top_types]
bp = ax2.boxplot(gap_by_type, labels=top_types, patch_artist=True,
                 notch=False,
                 boxprops=dict(facecolor="#90CAF9", color="#1565C0"),
                 medianprops=dict(color="#E53935", linewidth=2),
                 flierprops=dict(marker=".", markersize=2, alpha=0.3))
ax2.axhline(0, color="black", linewidth=1.2, linestyle="--")
ax2.axhline(-0.10, color="#FF6F00", linewidth=1, linestyle=":")
ax2.set_ylabel("gap_pct")
ax2.set_title("Gap por tipo de proyecto")
ax2.tick_params(axis="x", rotation=15)

plt.tight_layout()
plt.savefig(os.path.join(_root, "data/exports/eda_04_gap_analysis.png"), dpi=100, bbox_inches="tight")
plt.show()
print("[ok] Guardado: data/exports/eda_04_gap_analysis.png")

# %% [markdown]
# ## 7. Features del Modelo — Matriz de Correlación

# %%
# Carga features de transaction_features + scores
df_feat = pd.read_sql("""
    SELECT
        tf.gap_pct,
        tf.price_percentile_25,
        tf.price_percentile_50,
        tf.price_percentile_75,
        tf.price_vs_median,
        tf.dist_km_centroid,
        tf.cluster_id,
        tf.season_index,
        tc.surface_m2,
        tc.surface_building_m2,
        tc.surface_land_m2,
        tc.data_confidence,
        tc.year,
        tc.quarter,
        ms.opportunity_score,
        ms.undervaluation_score,
        ms.gap_percentile,
        ms.predicted_uf_m2,
        tc.uf_m2_building AS actual_uf_m2
    FROM transaction_features tf
    JOIN transactions_clean tc ON tc.id = tf.clean_id
    LEFT JOIN model_scores ms ON ms.clean_id = tf.clean_id
    WHERE tc.is_outlier = FALSE
    LIMIT 30000
""", engine)

print(f"[features] Cargadas {len(df_feat):,} filas con features completas")

# %%
# Seleccion de columnas numericas para correlacion
numeric_cols = [c for c in df_feat.columns if df_feat[c].dtype in [np.float64, np.int64]
                and df_feat[c].nunique() > 10 and c not in ["cluster_id", "quarter", "year"]]

corr = df_feat[numeric_cols].corr()

fig, ax = plt.subplots(figsize=(14, 11))
mask = np.triu(np.ones_like(corr, dtype=bool))
sns.heatmap(
    corr,
    mask=mask,
    annot=True,
    fmt=".2f",
    cmap="RdBu_r",
    center=0,
    vmin=-1,
    vmax=1,
    linewidths=0.4,
    ax=ax,
    annot_kws={"size": 8},
)
ax.set_title("Matriz de Correlación — Features del Modelo XGBoost\n(triangulo inferior)", fontsize=13)
plt.tight_layout()
plt.savefig(os.path.join(_root, "data/exports/eda_05_correlacion_features.png"), dpi=100, bbox_inches="tight")
plt.show()
print("[ok] Guardado: data/exports/eda_05_correlacion_features.png")

# Correlaciones mas altas con opportunity_score
if "opportunity_score" in corr.columns:
    print("\n--- Correlacion con opportunity_score ---")
    top_corr = (
        corr["opportunity_score"]
        .drop("opportunity_score", errors="ignore")
        .abs()
        .sort_values(ascending=False)
        .head(10)
    )
    for feat, val in top_corr.items():
        sign = "+" if corr.loc[feat, "opportunity_score"] > 0 else "-"
        print(f"  {feat:<30} {sign}{abs(val):.3f}")

# %% [markdown]
# ## 8. Score Analysis + SHAP Drivers

# %%
# Distribución del Opportunity Score
df_scores = df.dropna(subset=["opportunity_score"]).copy()
print(f"[scores] Propiedades con score calculado: {len(df_scores):,}")
print(f"  Media   : {df_scores['opportunity_score'].mean():.4f}")
print(f"  Mediana : {df_scores['opportunity_score'].median():.4f}")
print(f"  Std     : {df_scores['opportunity_score'].std():.4f}")
print(f"\n  Top 5% (score >= {df_scores['opportunity_score'].quantile(0.95):.3f}): "
      f"{(df_scores['opportunity_score'] >= df_scores['opportunity_score'].quantile(0.95)).sum():,} props")

# %%
fig, axes = plt.subplots(1, 3, figsize=(18, 5))

# Panel 1: histograma de opportunity_score
ax = axes[0]
ax.hist(df_scores["opportunity_score"], bins=50, color="#7B1FA2", alpha=0.8,
        edgecolor="white", linewidth=0.4)
ax.axvline(df_scores["opportunity_score"].quantile(0.90), color="#FF6F00", linestyle="--",
           label=f"p90: {df_scores['opportunity_score'].quantile(0.90):.2f}")
ax.axvline(df_scores["opportunity_score"].quantile(0.95), color="#E53935", linestyle="--",
           label=f"p95: {df_scores['opportunity_score'].quantile(0.95):.2f}")
ax.set_xlabel("Opportunity Score")
ax.set_ylabel("Frecuencia")
ax.set_title("Distribución Opportunity Score")
ax.legend(fontsize=9)

# Panel 2: undervaluation_score vs opportunity_score
ax2 = axes[1]
sample = df_scores.sample(min(5000, len(df_scores)), random_state=42)
sc = ax2.scatter(
    sample["undervaluation_score"],
    sample["opportunity_score"],
    c=sample["data_confidence"],
    cmap="YlOrRd",
    s=10,
    alpha=0.5,
)
cbar = plt.colorbar(sc, ax=ax2)
cbar.set_label("Data Confidence", fontsize=9)
ax2.set_xlabel("Undervaluation Score")
ax2.set_ylabel("Opportunity Score")
ax2.set_title("Undervaluation vs Opportunity Score\n(coloreado por confianza)")

# Panel 3: score por año
ax3 = axes[2]
for yr, grp in df_scores.groupby("year"):
    ax3.hist(grp["opportunity_score"], bins=40, alpha=0.6, label=str(yr),
             density=True)
ax3.set_xlabel("Opportunity Score")
ax3.set_ylabel("Densidad")
ax3.set_title("Score por Año de Transacción")
ax3.legend()

plt.tight_layout()
plt.savefig(os.path.join(_root, "data/exports/eda_06_score_analysis.png"), dpi=100, bbox_inches="tight")
plt.show()
print("[ok] Guardado: data/exports/eda_06_score_analysis.png")

# %%
# SHAP drivers: extraer top features de model_scores.shap_top_features (JSONB)
try:
    df_shap_raw = pd.read_sql("""
        SELECT shap_top_features
        FROM model_scores
        WHERE shap_top_features IS NOT NULL
        LIMIT 5000
    """, engine)

    if len(df_shap_raw) == 0:
        print("[shap] No hay datos SHAP en model_scores todavia.")
    else:
        import json as _json

        # Expandir JSONB a filas
        shap_records = []
        for row in df_shap_raw["shap_top_features"]:
            if isinstance(row, str):
                row = _json.loads(row)
            if isinstance(row, list):
                for item in row:
                    shap_records.append(item)

        df_shap = pd.DataFrame(shap_records)
        print(f"[shap] {len(df_shap):,} registros SHAP de {len(df_shap_raw):,} propiedades")

        if "feature" in df_shap.columns and "shap" in df_shap.columns:
            # Promedio del valor absoluto SHAP por feature (importancia global)
            shap_imp = (
                df_shap.groupby("feature")["shap"]
                .apply(lambda x: x.abs().mean())
                .sort_values(ascending=False)
                .head(15)
            )

            fig, ax = plt.subplots(figsize=(10, 6))
            colors_shap = ["#E53935" if v > 0 else "#1E88E5"
                           for v in shap_imp.values]
            ax.barh(shap_imp.index[::-1], shap_imp.values[::-1],
                    color="#7B1FA2", alpha=0.8)
            ax.set_xlabel("SHAP medio |valor| (importancia global)")
            ax.set_title("Top Features por Importancia SHAP\n(promedio sobre muestra de propiedades)")
            plt.tight_layout()
            plt.savefig(os.path.join(_root, "data/exports/eda_07_shap_features.png"),
                        dpi=100, bbox_inches="tight")
            plt.show()
            print("[ok] Guardado: data/exports/eda_07_shap_features.png")

except Exception as e:
    print(f"[shap] No se pudo analizar SHAP: {e}")

# %% [markdown]
# ## 9. Antigüedad — Distribución por Año de Construcción

# %%
# Usamos year_building de transactions_raw (disponible en raw, no en clean directamente)
# La vista v_opportunities no expone year_building, lo obtenemos de raw via raw_id
df_age = pd.read_sql("""
    SELECT
        tr.year_building,
        tc.project_type,
        tc.uf_m2_building,
        ms.opportunity_score
    FROM transactions_raw tr
    JOIN transactions_clean tc ON tc.raw_id = tr.id
    LEFT JOIN model_scores ms ON ms.clean_id = tc.id
    WHERE tr.year_building IS NOT NULL
      AND tr.year_building BETWEEN 1900 AND 2015
      AND tc.is_outlier = FALSE
    LIMIT 40000
""", engine)

print(f"[edad] Filas con year_building: {len(df_age):,}")
if len(df_age) > 0:
    print(f"  Rango: {int(df_age['year_building'].min())} — {int(df_age['year_building'].max())}")
    print(f"  Mediana: {int(df_age['year_building'].median())}")

# %%
if len(df_age) > 0:
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))

    # Panel izq: histograma por decada
    ax = axes[0]
    df_age["decade"] = (df_age["year_building"] // 10 * 10).astype(int)
    decade_counts = df_age["decade"].value_counts().sort_index()
    ax.bar(decade_counts.index, decade_counts.values, width=8,
           color="#1E88E5", alpha=0.8, edgecolor="white")
    ax.set_xlabel("Decada de construccion")
    ax.set_ylabel("N propiedades")
    ax.set_title("Propiedades por Decada de Construccion")

    # Panel der: UF/m2 mediano por decada
    ax2 = axes[1]
    uf_by_decade = df_age.groupby("decade")["uf_m2_building"].median().dropna()
    ax2.plot(uf_by_decade.index, uf_by_decade.values, marker="o",
             color="#E53935", linewidth=2, markersize=5)
    ax2.fill_between(uf_by_decade.index, uf_by_decade.values, alpha=0.15, color="#E53935")
    ax2.set_xlabel("Decada de construccion")
    ax2.set_ylabel("UF/m2 mediano")
    ax2.set_title("Precio mediano (UF/m2) por Decada de Construccion")

    plt.tight_layout()
    plt.savefig(os.path.join(_root, "data/exports/eda_08_antiguedad.png"), dpi=100, bbox_inches="tight")
    plt.show()
    print("[ok] Guardado: data/exports/eda_08_antiguedad.png")

    # Tabla resumen por buckets de antiguedad
    current_year = 2014  # año de los datos
    df_age["age"] = current_year - df_age["year_building"]
    bins   = [-1, 5, 15, 30, 50, 999]
    labels = ["0-5 anos", "6-15 anos", "16-30 anos", "31-50 anos", "50+ anos"]
    df_age["age_bucket"] = pd.cut(df_age["age"], bins=bins, labels=labels)
    print("\n--- UF/m2 por antiguedad del inmueble ---")
    print(
        df_age.groupby("age_bucket", observed=True)["uf_m2_building"]
        .agg(["count", "median", "mean"])
        .rename(columns={"count": "n", "median": "uf_m2_mediano", "mean": "uf_m2_media"})
        .round(2)
        .to_string()
    )
else:
    print("[edad] No hay datos de year_building disponibles.")

# %% [markdown]
# ## 10. OSM Coverage — Cobertura de Features de Proximidad

# %%
# Verificar si existen columnas OSM en transaction_features
osm_cols_check = pd.read_sql("""
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'transaction_features'
      AND column_name IN (
        'dist_metro_km', 'dist_bus_stop_km', 'dist_school_km',
        'dist_hospital_km', 'dist_park_km', 'amenities_500m',
        'amenities_1km', 'n_bus_lines_1km'
      )
    ORDER BY column_name
""", engine)

OSM_COLS = osm_cols_check["column_name"].tolist()
print(f"[osm] Columnas OSM presentes en transaction_features: {OSM_COLS}")

# %%
if not OSM_COLS:
    print("[osm] Las features OSM aun no han sido generadas.")
    print("      Ejecutar: python src/features/build_features.py  (requiere internet para Overpass API)")
    print("      O bien: python src/features/build_features.py --skip-osm  (para omitir OSM)")
else:
    # Carga cobertura OSM
    select_cols = ", ".join([f"tf.{c}" for c in OSM_COLS])
    df_osm = pd.read_sql(f"""
        SELECT {select_cols},
               tc.county_name
        FROM transaction_features tf
        JOIN transactions_clean tc ON tc.id = tf.clean_id
        WHERE tc.is_outlier = FALSE
        LIMIT 20000
    """, engine)

    print(f"[osm] Muestra cargada: {len(df_osm):,} filas")
    print(f"\n--- Cobertura de features OSM (% no-nulo) ---")
    coverage = (df_osm[OSM_COLS].notna().mean() * 100).sort_values(ascending=False)
    for col, pct in coverage.items():
        bar = "#" * int(pct / 5)
        print(f"  {col:<25} {pct:5.1f}%  {bar}")

    # Estadisticas de distancias
    dist_cols = [c for c in OSM_COLS if "dist_" in c]
    if dist_cols:
        print("\n--- Estadisticas de distancia (km) ---")
        print(df_osm[dist_cols].describe().round(3).to_string())

    # Visualizacion si hay datos suficientes
    if "dist_metro_km" in df_osm.columns and df_osm["dist_metro_km"].notna().sum() > 100:
        fig, axes = plt.subplots(1, len(dist_cols), figsize=(5 * len(dist_cols), 4))
        if len(dist_cols) == 1:
            axes = [axes]
        for ax, col in zip(axes, dist_cols):
            data = df_osm[col].dropna().clip(0, 10)
            ax.hist(data, bins=40, color="#00897B", alpha=0.8, edgecolor="white", linewidth=0.4)
            ax.set_xlabel("km")
            ax.set_title(col.replace("_", " "))
            ax.axvline(data.median(), color="#E53935", linestyle="--",
                       label=f"Mediana: {data.median():.2f}km")
            ax.legend(fontsize=8)
        plt.suptitle("Distribución de distancias OSM", fontsize=13, y=1.02)
        plt.tight_layout()
        plt.savefig(os.path.join(_root, "data/exports/eda_09_osm_coverage.png"),
                    dpi=100, bbox_inches="tight")
        plt.show()
        print("[ok] Guardado: data/exports/eda_09_osm_coverage.png")

# %% [markdown]
# ## Resumen Final

# %%
print("\n" + "=" * 65)
print("  RESUMEN EDA — RE_CL Plataforma")
print("=" * 65)

# Conteos finales
for tbl, n in table_counts.items():
    if n > 0:
        print(f"  {tbl:<30} {n:>12,} filas")

print()
if len(df_scores) > 0:
    top_n = 10
    top_props = df_scores.nlargest(top_n, "opportunity_score")[
        ["county_name", "project_type", "opportunity_score", "gap_pct", "uf_m2_building"]
    ]
    print(f"  Top {top_n} oportunidades en muestra:")
    print(top_props.to_string(index=False))

print()
print("  Graficos generados en data/exports/:")
exports = [
    "eda_01_precio_distribucion.png",
    "eda_02_mapa_scatter.png",
    "eda_03_comunas_ranking.png",
    "eda_04_gap_analysis.png",
    "eda_05_correlacion_features.png",
    "eda_06_score_analysis.png",
    "eda_07_shap_features.png",
    "eda_08_antiguedad.png",
    "eda_09_osm_coverage.png",
]
for fn in exports:
    path = os.path.join(_root, "data/exports", fn)
    status = "OK" if os.path.exists(path) else "no generado"
    print(f"    {fn:<45} [{status}]")

print("\n  EDA completo.")
print("=" * 65)
