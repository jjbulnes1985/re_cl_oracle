"""
heatmap.py
----------
Generates an interactive Folium heatmap of opportunity scores.

Features:
  - HeatMap layer colored by opportunity_score
  - LayerControl to toggle by typology (Apartments, Residential, Land)
  - CircleMarker popups with property details + top SHAP drivers
  - Exports to data/exports/heatmap_vX.html

Usage:
    python src/maps/heatmap.py
    python src/maps/heatmap.py --output data/exports/mi_mapa.html
"""

import argparse
import json
import os
import sys
from pathlib import Path

import folium
from folium.plugins import HeatMap, HeatMapWithTime
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

EXPORTS_DIR   = Path(os.getenv("EXPORTS_DIR", "data/exports"))
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")

# Santiago RM center
MAP_CENTER = [-33.45, -70.67]
MAP_ZOOM   = 11

TYPOLOGY_COLORS = {
    "apartments": "#2196F3",   # blue
    "residential": "#4CAF50",  # green
    "land":       "#FF9800",   # orange
    "retail":     "#9C27B0",   # purple
    "unknown":    "#9E9E9E",   # grey
}


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB",   "re_cl")
    user = os.getenv("POSTGRES_USER", "re_cl_user")
    pwd  = os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"


def load_scored_data(engine) -> pd.DataFrame:
    """Load opportunity scores joined with geographic and property data."""
    query = f"""
        SELECT
            v.score_id,
            v.project_type,
            v.county_name,
            v.year,
            v.real_value_uf,
            v.surface_m2,
            v.uf_m2_building,
            v.opportunity_score,
            v.undervaluation_score,
            v.gap_pct,
            v.gap_percentile,
            v.predicted_uf_m2,
            v.data_confidence,
            v.shap_top_features,
            v.latitude,
            v.longitude,
            v.model_version
        FROM v_opportunities v
        WHERE v.model_version = '{MODEL_VERSION}'
          AND v.latitude IS NOT NULL
          AND v.longitude IS NOT NULL
          AND v.opportunity_score IS NOT NULL
        ORDER BY v.opportunity_score DESC
        LIMIT 50000
    """
    df = pd.read_sql(query, engine)
    logger.info(f"Loaded {len(df):,} scored properties for heatmap")
    return df


def build_heatmap(df: pd.DataFrame, output_path: Path) -> None:
    """Build and export the interactive Folium map."""
    m = folium.Map(
        location=MAP_CENTER,
        zoom_start=MAP_ZOOM,
        tiles="CartoDB positron",
    )

    # ── Global heatmap layer (all typologies) ──────────────────────────────────
    heat_data = [
        [row["latitude"], row["longitude"], row["opportunity_score"]]
        for _, row in df.iterrows()
        if pd.notna(row["latitude"]) and pd.notna(row["opportunity_score"])
    ]
    HeatMap(
        heat_data,
        name="Opportunity Heatmap (all)",
        min_opacity=0.3,
        radius=15,
        blur=20,
        gradient={0.2: "blue", 0.5: "yellow", 0.8: "orange", 1.0: "red"},
    ).add_to(m)

    # ── Per-typology feature groups with circle markers ────────────────────────
    typologies = df["project_type"].unique()
    for ptype in sorted(typologies):
        sub = df[df["project_type"] == ptype].head(5000)  # cap per layer
        color = TYPOLOGY_COLORS.get(ptype, "#9E9E9E")
        fg = folium.FeatureGroup(name=f"{ptype.title()} ({len(sub):,})", show=False)

        for _, row in sub.iterrows():
            shap_html = ""
            shap_val = row.get("shap_top_features")
            if shap_val is not None and not (isinstance(shap_val, float) and pd.isna(shap_val)):
                try:
                    drivers = json.loads(row["shap_top_features"])
                    shap_html = "<b>Top drivers:</b><ul>" + "".join(
                        f"<li>{d['feature']}: {d['shap']:+.3f} ({d['direction']})</li>"
                        for d in drivers
                    ) + "</ul>"
                except Exception:
                    pass

            popup_html = f"""
            <div style="font-family:sans-serif;min-width:200px">
              <b>{ptype.title()}</b> — {row['county_name']}<br>
              <b>Opportunity Score:</b> {row['opportunity_score']:.3f}<br>
              <b>Gap vs model:</b> {row['gap_pct']*100:+.1f}%<br>
              <b>Actual UF/m²:</b> {row['uf_m2_building']:.1f}<br>
              <b>Predicted UF/m²:</b> {row['predicted_uf_m2']:.1f}<br>
              <b>Confidence:</b> {row['data_confidence']:.2f}<br>
              {shap_html}
            </div>
            """

            radius = 4 + row["opportunity_score"] * 6  # 4-10px by score
            folium.CircleMarker(
                location=[row["latitude"], row["longitude"]],
                radius=radius,
                color=color,
                fill=True,
                fill_opacity=0.6,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{ptype} | score={row['opportunity_score']:.3f}",
            ).add_to(fg)

        fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # ── Legend ─────────────────────────────────────────────────────────────────
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;
                background:white;padding:10px;border-radius:5px;
                border:1px solid #ccc;font-family:sans-serif;font-size:12px">
      <b>Opportunity Score</b><br>
      <span style="color:red">■</span> 0.8–1.0 Alta<br>
      <span style="color:orange">■</span> 0.6–0.8 Media-Alta<br>
      <span style="color:#FFD700">■</span> 0.4–0.6 Media<br>
      <span style="color:blue">■</span> 0.0–0.4 Baja<br>
      <hr style="margin:5px 0">
      <small>Modelo: {version} | {n} propiedades</small>
    </div>
    """.format(version=MODEL_VERSION, n=f"{len(df):,}")
    m.get_root().html.add_child(folium.Element(legend_html))

    # ── Export ─────────────────────────────────────────────────────────────────
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    logger.info(f"Heatmap saved: {output_path}")


def main(output: str = None) -> None:
    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    df     = load_scored_data(engine)

    if df.empty:
        logger.error("No scored data. Run opportunity_score.py first.")
        sys.exit(1)

    n_communes = df["county_name"].nunique()
    logger.info(f"Communes with data: {n_communes} | Typologies: {df['project_type'].nunique()}")

    if n_communes < 5:
        logger.warning(f"Only {n_communes} communes with data (expected >= 5)")

    out_path = Path(output) if output else EXPORTS_DIR / f"heatmap_{MODEL_VERSION}.html"
    build_heatmap(df, out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()
    main(output=args.output)
