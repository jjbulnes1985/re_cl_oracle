"""
generate_report.py
------------------
Generates a self-contained HTML report of top opportunity properties for RE_CL.

Report sections:
  1. Header          — RE_CL logo text, report date, model version
  2. Executive Summary — key metrics (total scored, mean score, top commune, model R²)
  3. Top Opportunities — top-N properties with score badge, commune, type, UF/m², gap%
  4. Commune Rankings  — top 10 communes by opportunity score with mini bar visualization
  5. Model Validation  — if backtesting_report.json exists: R², RMSE, MAE, OLS vs XGBoost
  6. Map thumbnail     — SVG scatter plot of properties colored by score

CLI:
    python src/reports/generate_report.py
    python src/reports/generate_report.py --top-n 50
    python src/reports/generate_report.py --profile location
    python src/reports/generate_report.py --output custom_name.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent.parent          # re_cl/
EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", str(_ROOT / "data" / "exports")))
REPORT_PATH = _ROOT / "data" / "exports" / "backtesting_report.json"
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1.0")

# Santiago RM bounding box for SVG map
_LAT_RANGE = (-33.65, -33.30)
_LON_RANGE = (-70.85, -70.45)


# ── DB helpers ────────────────────────────────────────────────────────────────

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


def _get_engine():
    try:
        from sqlalchemy import create_engine
        return create_engine(_build_db_url(), pool_pre_ping=True, connect_args={"connect_timeout": 5})
    except Exception as e:
        logger.warning(f"Could not create DB engine: {e}")
        return None


# ── Data loading ──────────────────────────────────────────────────────────────

def load_top_properties(engine, top_n: int, profile: str) -> pd.DataFrame:
    """Load top-N opportunity properties from v_opportunities view."""
    from sqlalchemy import text

    # Score column may vary by profile (future: profile-specific score columns)
    query = text(f"""
        SELECT
            v.raw_id,
            v.county_name,
            v.project_type,
            ROUND(v.opportunity_score::numeric, 4)    AS opportunity_score,
            ROUND(v.undervaluation_score::numeric, 4) AS undervaluation_score,
            ROUND(v.uf_m2_building::numeric, 2)       AS uf_m2_building,
            ROUND(v.gap_pct::numeric, 4)              AS gap_pct,
            ROUND(v.data_confidence::numeric, 4)      AS data_confidence,
            v.latitude,
            v.longitude,
            tf.city_zone,
            tf.dist_metro_km
        FROM v_opportunities v
        LEFT JOIN transactions_clean tc ON tc.raw_id = v.raw_id
        LEFT JOIN transaction_features tf ON tf.clean_id = tc.id
        WHERE v.model_version = :mv
          AND v.opportunity_score IS NOT NULL
        ORDER BY v.opportunity_score DESC
        LIMIT :n
    """)
    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"mv": MODEL_VERSION, "n": top_n})
        logger.info(f"Loaded {len(df):,} top properties (profile={profile})")
        return df
    except Exception as e:
        logger.error(f"Failed to load properties: {e}")
        return pd.DataFrame()


def load_summary_stats(engine) -> dict:
    """Load aggregate score statistics."""
    from sqlalchemy import text
    query = text("""
        SELECT
            COUNT(*)                                         AS total_scored,
            ROUND(AVG(opportunity_score)::numeric, 4)        AS mean_score,
            COUNT(*) FILTER (WHERE opportunity_score > 0.7)  AS high_opp_count
        FROM model_scores
        WHERE model_version = :mv
    """)
    try:
        with engine.connect() as conn:
            row = conn.execute(query, {"mv": MODEL_VERSION}).mappings().first()
        return dict(row) if row else {}
    except Exception as e:
        logger.error(f"Failed to load summary stats: {e}")
        return {}


def load_commune_stats(engine) -> pd.DataFrame:
    """Load top 10 communes by median opportunity score."""
    from sqlalchemy import text
    query = text("""
        SELECT
            county_name,
            n_transactions,
            ROUND(median_score::numeric, 4)          AS median_score,
            ROUND(pct_subvaloradas::numeric, 2)      AS pct_subvaloradas,
            ROUND(median_uf_m2::numeric, 2)          AS median_uf_m2,
            ROUND(median_gap_pct::numeric, 4)        AS median_gap_pct
        FROM commune_stats
        WHERE model_version = :mv
        ORDER BY median_score DESC
        LIMIT 10
    """)
    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params={"mv": MODEL_VERSION})
        logger.info(f"Loaded commune stats: {len(df)} communes")
        return df
    except Exception as e:
        logger.error(f"Failed to load commune stats: {e}")
        return pd.DataFrame()


def load_backtesting_report() -> Optional[dict]:
    """Load backtesting report JSON if available."""
    if not REPORT_PATH.exists():
        logger.info(f"Backtesting report not found at {REPORT_PATH}")
        return None
    try:
        with open(REPORT_PATH) as f:
            report = json.load(f)
        logger.info(f"Loaded backtesting report from {REPORT_PATH}")
        return report
    except Exception as e:
        logger.warning(f"Could not load backtesting report: {e}")
        return None


# ── Mock data for offline/demo mode ──────────────────────────────────────────

def _mock_properties(top_n: int) -> pd.DataFrame:
    """Generate realistic mock data for demo/offline mode."""
    import random
    random.seed(42)

    communes = [
        "Santiago", "Providencia", "Las Condes", "Ñuñoa", "Maipú",
        "La Florida", "Vitacura", "San Miguel", "Independencia", "Recoleta",
    ]
    types = ["Departamento", "Casa", "Oficina", "Local Comercial"]
    zones = ["Centro", "Oriente", "Poniente", "Norte", "Sur"]

    rows = []
    for i in range(min(top_n, 50)):
        score = round(0.95 - i * 0.015 + random.uniform(-0.02, 0.02), 4)
        score = max(0.0, min(1.0, score))
        lat = round(random.uniform(-33.60, -33.35), 6)
        lon = round(random.uniform(-70.80, -70.50), 6)
        rows.append({
            "clean_id":            i + 1,
            "county_name":         random.choice(communes),
            "project_type":        random.choice(types),
            "opportunity_score":   score,
            "undervaluation_score": round(score + random.uniform(-0.1, 0.1), 4),
            "uf_m2_building":      round(random.uniform(30, 150), 2),
            "gap_pct":             round(random.uniform(-0.4, -0.05), 4),
            "data_confidence":     round(random.uniform(0.65, 1.0), 4),
            "latitude":            lat,
            "longitude":           lon,
            "city_zone":           random.choice(zones),
            "dist_metro_km":       round(random.uniform(0.1, 3.5), 2),
        })
    return pd.DataFrame(rows)


def _mock_summary() -> dict:
    return {
        "total_scored": 45230,
        "mean_score":   0.4821,
        "high_opp_count": 6834,
    }


def _mock_communes() -> pd.DataFrame:
    data = [
        ("Providencia",    8240, 0.7823, 34.2, 95.4,  -0.18),
        ("Ñuñoa",          6120, 0.7541, 31.8, 88.2,  -0.15),
        ("Santiago",      12850, 0.7212, 28.5, 72.1,  -0.12),
        ("San Miguel",     4310, 0.6987, 26.1, 68.3,  -0.11),
        ("Independencia",  2840, 0.6754, 24.8, 65.9,  -0.10),
        ("Recoleta",       3560, 0.6521, 23.4, 62.4,  -0.09),
        ("Las Condes",     9870, 0.6234, 21.2, 58.7,  -0.08),
        ("La Florida",     7230, 0.5987, 19.8, 56.1,  -0.07),
        ("Maipú",          8940, 0.5712, 17.5, 52.3,  -0.06),
        ("Vitacura",       3120, 0.5234, 15.1, 48.9,  -0.05),
    ]
    return pd.DataFrame(data, columns=[
        "county_name", "n_transactions", "median_score",
        "pct_subvaloradas", "median_uf_m2", "median_gap_pct"
    ])


# ── SVG map generator ─────────────────────────────────────────────────────────

def generate_map_svg(props_df: pd.DataFrame, width: int = 800, height: int = 400) -> str:
    """Generate an SVG scatter plot of properties colored by opportunity score."""
    lat_range = _LAT_RANGE
    lon_range = _LON_RANGE

    def to_svg(lat: float, lon: float):
        x = (lon - lon_range[0]) / (lon_range[1] - lon_range[0]) * width
        y = (1 - (lat - lat_range[0]) / (lat_range[1] - lat_range[0])) * height
        return x, y

    circles = []
    for _, row in props_df.iterrows():
        lat = row.get("latitude")
        lon = row.get("longitude")
        if pd.isna(lat) or pd.isna(lon):
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (ValueError, TypeError):
            continue
        # Only plot within Santiago bounding box
        if not (lat_range[0] <= lat <= lat_range[1] and lon_range[0] <= lon <= lon_range[1]):
            continue

        x, y = to_svg(lat, lon)
        score = float(row.get("opportunity_score", 0) or 0)
        color = (
            "#ef4444" if score >= 0.8 else
            "#f97316" if score >= 0.6 else
            "#eab308" if score >= 0.4 else
            "#3b82f6"
        )
        r = round(3 + score * 5, 1)
        tooltip = (
            f"{row.get('county_name', '')} | "
            f"Score: {score:.2f} | "
            f"UF/m²: {row.get('uf_m2_building', '')}"
        )
        circles.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" '
            f'fill="{color}" opacity="0.7">'
            f'<title>{tooltip}</title></circle>'
        )

    # Grid lines for reference
    grid_lines = []
    for i in range(1, 4):
        gx = width * i / 4
        gy = height * i / 4
        grid_lines.append(f'<line x1="{gx:.0f}" y1="0" x2="{gx:.0f}" y2="{height}" stroke="#374151" stroke-width="0.5"/>')
        grid_lines.append(f'<line x1="0" y1="{gy:.0f}" x2="{width}" y2="{gy:.0f}" stroke="#374151" stroke-width="0.5"/>')

    # Compass
    compass = (
        f'<text x="{width - 20}" y="20" fill="#6b7280" font-size="12" '
        f'font-family="monospace" text-anchor="middle">N↑</text>'
    )

    # Legend
    legend_items = [
        ("#ef4444", "≥ 0.8 Alta"),
        ("#f97316", "≥ 0.6 Media-Alta"),
        ("#eab308", "≥ 0.4 Media"),
        ("#3b82f6", "< 0.4 Baja"),
    ]
    legend_parts = []
    for idx, (lc, lt) in enumerate(legend_items):
        lx, ly = width - 130, 40 + idx * 20
        legend_parts.append(
            f'<circle cx="{lx}" cy="{ly - 4}" r="5" fill="{lc}" opacity="0.8"/>'
            f'<text x="{lx + 12}" y="{ly}" fill="#9ca3af" font-size="10" font-family="sans-serif">{lt}</text>'
        )

    # Labels
    label_w = f'<text x="4" y="{height - 4}" fill="#6b7280" font-size="9" font-family="monospace">W {lon_range[0]}</text>'
    label_e = f'<text x="{width - 4}" y="{height - 4}" fill="#6b7280" font-size="9" font-family="monospace" text-anchor="end">E {lon_range[1]}</text>'
    label_n = f'<text x="4" y="12" fill="#6b7280" font-size="9" font-family="monospace">N {lat_range[1]}</text>'
    label_s = f'<text x="4" y="{height - 14}" fill="#6b7280" font-size="9" font-family="monospace">S {lat_range[0]}</text>'

    count_txt = f'<text x="{width // 2}" y="{height - 4}" fill="#6b7280" font-size="10" font-family="sans-serif" text-anchor="middle">{len(circles)} propiedades graficadas</text>'

    svg_parts = (
        grid_lines
        + [compass]
        + legend_parts
        + [label_w, label_e, label_n, label_s]
        + circles
        + [count_txt]
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'style="background:#111827;border-radius:8px;display:block;margin:0 auto">'
        + "".join(svg_parts)
        + "</svg>"
    )


# ── HTML section builders ─────────────────────────────────────────────────────

def _score_badge(score: float) -> str:
    if score >= 0.8:
        cls = "badge-red"
        label = "ALTA"
    elif score >= 0.6:
        cls = "badge-orange"
        label = "MEDIA-ALTA"
    elif score >= 0.4:
        cls = "badge-yellow"
        label = "MEDIA"
    else:
        cls = "badge-blue"
        label = "BAJA"
    return f'<span class="badge {cls}">{score:.3f} {label}</span>'


def _fmt(val, fmt=".2f", fallback="—") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return fallback
    try:
        return format(float(val), fmt)
    except (ValueError, TypeError):
        return str(val)


def _pct(val, fallback="—") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return fallback
    try:
        return f"{float(val) * 100:+.1f}%"
    except (ValueError, TypeError):
        return str(val)


def build_header(report_date: str, profile: str) -> str:
    return f"""
    <header>
        <div class="logo">
            <span class="logo-re">RE</span><span class="logo-cl">_CL</span>
        </div>
        <div class="header-meta">
            <h1>Reporte de Oportunidades Inmobiliarias</h1>
            <div class="header-pills">
                <span class="pill">Fecha: {report_date}</span>
                <span class="pill">Modelo: {MODEL_VERSION}</span>
                <span class="pill">Perfil: {profile}</span>
                <span class="pill">Región: RM Santiago</span>
            </div>
        </div>
    </header>
    """


def build_executive_summary(stats: dict, communes_df: pd.DataFrame, backtest: Optional[dict]) -> str:
    total = stats.get("total_scored", "—")
    mean  = _fmt(stats.get("mean_score"), ".4f")
    high  = stats.get("high_opp_count", "—")
    top_commune = communes_df["county_name"].iloc[0] if not communes_df.empty else "—"

    r2_str = "—"
    if backtest:
        try:
            r2_str = f"{backtest.get('temporal_split', {}).get('xgboost', {}).get('r2', backtest.get('r2', '—')):.4f}"
        except Exception:
            r2_str = "—"

    pct_high = "—"
    if isinstance(total, (int, float)) and total > 0 and isinstance(high, (int, float)):
        pct_high = f"{high / total * 100:.1f}%"

    total_fmt = f"{total:,}" if isinstance(total, int) else str(total)
    high_fmt  = f"{high:,}"  if isinstance(high, int)  else str(high)

    return f"""
    <section class="section">
        <h2 class="section-title">Resumen Ejecutivo</h2>
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-value">{total_fmt}</div>
                <div class="kpi-label">Propiedades Evaluadas</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{mean}</div>
                <div class="kpi-label">Score Medio Oportunidad</div>
            </div>
            <div class="kpi-card kpi-highlight">
                <div class="kpi-value">{high_fmt}</div>
                <div class="kpi-label">Oportunidades Alta (score &gt; 0.7) · {pct_high}</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{top_commune}</div>
                <div class="kpi-label">Comuna Top</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{r2_str}</div>
                <div class="kpi-label">R² Modelo XGBoost</div>
            </div>
        </div>
    </section>
    """


def build_properties_table(props_df: pd.DataFrame, top_n: int) -> str:
    if props_df.empty:
        return '<section class="section"><p class="empty-msg">Sin datos de propiedades disponibles.</p></section>'

    rows_html = []
    for i, (_, row) in enumerate(props_df.iterrows(), 1):
        score = float(row.get("opportunity_score", 0) or 0)
        gap   = row.get("gap_pct")
        zone  = row.get("city_zone") or "—"
        dist  = _fmt(row.get("dist_metro_km"), ".2f")
        rows_html.append(f"""
        <tr>
            <td class="rank">#{i}</td>
            <td>{_score_badge(score)}</td>
            <td>{row.get('county_name', '—')}</td>
            <td>{row.get('project_type', '—')}</td>
            <td class="num">{_fmt(row.get('uf_m2_building'), '.1f')}</td>
            <td class="num gap">{_pct(gap)}</td>
            <td>{zone}</td>
            <td class="num">{dist}</td>
            <td class="num conf">{_fmt(row.get('data_confidence'), '.2f')}</td>
        </tr>""")

    return f"""
    <section class="section">
        <h2 class="section-title">Top {top_n} Oportunidades</h2>
        <div class="table-wrapper">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Score</th>
                        <th>Comuna</th>
                        <th>Tipo</th>
                        <th>UF/m²</th>
                        <th>Gap%</th>
                        <th>Zona</th>
                        <th>Dist. Metro (km)</th>
                        <th>Confianza</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows_html)}
                </tbody>
            </table>
        </div>
    </section>
    """


def build_commune_ranking(communes_df: pd.DataFrame) -> str:
    if communes_df.empty:
        return '<section class="section"><p class="empty-msg">Sin datos de comunas disponibles.</p></section>'

    max_score = float(communes_df["median_score"].max()) if not communes_df.empty else 1.0

    rows_html = []
    for i, (_, row) in enumerate(communes_df.iterrows(), 1):
        score = float(row.get("median_score", 0) or 0)
        bar_pct = round(score / max_score * 100, 1) if max_score > 0 else 0
        color = (
            "#ef4444" if score >= 0.8 else
            "#f97316" if score >= 0.6 else
            "#eab308" if score >= 0.4 else
            "#3b82f6"
        )
        rows_html.append(f"""
        <tr>
            <td class="rank">#{i}</td>
            <td class="commune-name">{row.get('county_name', '—')}</td>
            <td>
                <div class="bar-wrap">
                    <div class="bar" style="width:{bar_pct}%;background:{color}"></div>
                    <span class="bar-label">{score:.4f}</span>
                </div>
            </td>
            <td class="num">{int(row.get('n_transactions', 0)):,}</td>
            <td class="num">{_fmt(row.get('pct_subvaloradas'), '.1f')}%</td>
            <td class="num">{_fmt(row.get('median_uf_m2'), '.1f')}</td>
            <td class="num gap">{_pct(row.get('median_gap_pct'))}</td>
        </tr>""")

    return f"""
    <section class="section">
        <h2 class="section-title">Ranking de Comunas (Top 10)</h2>
        <div class="table-wrapper">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Comuna</th>
                        <th>Score Mediano</th>
                        <th>N° Transacciones</th>
                        <th>% Subvaloradas</th>
                        <th>UF/m² Mediano</th>
                        <th>Gap% Mediano</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows_html)}
                </tbody>
            </table>
        </div>
    </section>
    """


def build_model_validation(backtest: Optional[dict]) -> str:
    if backtest is None:
        return f"""
    <section class="section">
        <h2 class="section-title">Validación del Modelo</h2>
        <p class="empty-msg">
            Reporte de backtesting no disponible.<br>
            Ejecutar: <code>python src/backtesting/walk_forward.py</code>
        </p>
    </section>
    """

    # Extract metrics — report structure from walk_forward.py
    ts = backtest.get("temporal_split", {})
    xgb_metrics = ts.get("xgboost", ts)
    ols_metrics = ts.get("ols", {})

    xgb_r2   = _fmt(xgb_metrics.get("r2"),   ".4f")
    xgb_rmse = _fmt(xgb_metrics.get("rmse"), ".4f")
    xgb_mae  = _fmt(xgb_metrics.get("mae"),  ".4f")

    ols_r2   = _fmt(ols_metrics.get("r2"),   ".4f") if ols_metrics else "—"
    ols_rmse = _fmt(ols_metrics.get("rmse"), ".4f") if ols_metrics else "—"
    ols_mae  = _fmt(ols_metrics.get("mae"),  ".4f") if ols_metrics else "—"

    generated = backtest.get("generated_at", backtest.get("timestamp", "—"))

    rolling_section = ""
    rolling = backtest.get("rolling_quarters", [])
    if rolling:
        rolling_rows = "".join(
            f"<tr><td>{q.get('quarter','—')}</td>"
            f"<td class='num'>{_fmt(q.get('r2'), '.4f')}</td>"
            f"<td class='num'>{_fmt(q.get('rmse'), '.4f')}</td>"
            f"<td class='num'>{_fmt(q.get('n_test'), '.0f')}</td></tr>"
            for q in rolling
        )
        rolling_section = f"""
        <h3 class="sub-title">Validación Rolling por Trimestre</h3>
        <div class="table-wrapper">
            <table class="data-table">
                <thead><tr><th>Trimestre</th><th>R²</th><th>RMSE</th><th>N Test</th></tr></thead>
                <tbody>{rolling_rows}</tbody>
            </table>
        </div>"""

    return f"""
    <section class="section">
        <h2 class="section-title">Validación del Modelo</h2>
        <p class="meta-text">Backtesting generado: {generated}</p>
        <div class="validation-grid">
            <div class="validation-card">
                <h3 class="card-title">XGBoost (Hedónico)</h3>
                <div class="metric-row"><span class="metric-name">R²</span><span class="metric-val">{xgb_r2}</span></div>
                <div class="metric-row"><span class="metric-name">RMSE</span><span class="metric-val">{xgb_rmse}</span></div>
                <div class="metric-row"><span class="metric-name">MAE</span><span class="metric-val">{xgb_mae}</span></div>
            </div>
            <div class="validation-card">
                <h3 class="card-title">OLS Benchmark</h3>
                <div class="metric-row"><span class="metric-name">R²</span><span class="metric-val">{ols_r2}</span></div>
                <div class="metric-row"><span class="metric-name">RMSE</span><span class="metric-val">{ols_rmse}</span></div>
                <div class="metric-row"><span class="metric-name">MAE</span><span class="metric-val">{ols_mae}</span></div>
            </div>
        </div>
        {rolling_section}
    </section>
    """


def build_map_section(props_df: pd.DataFrame) -> str:
    svg = generate_map_svg(props_df)
    return f"""
    <section class="section">
        <h2 class="section-title">Distribución Geográfica (RM Santiago)</h2>
        <div class="map-container">
            {svg}
            <p class="map-caption">
                Puntos coloreados por score de oportunidad.
                Rojo = Alta (&ge;0.8) · Naranja = Media-Alta (&ge;0.6) · Amarillo = Media (&ge;0.4) · Azul = Baja
            </p>
        </div>
    </section>
    """


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e;
    color: #e2e8f0;
    font-size: 14px;
    line-height: 1.5;
}

/* ── Layout ── */
.page-wrapper { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }

/* ── Header ── */
header {
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 28px 32px;
    background: #16213e;
    border-radius: 12px;
    margin-bottom: 24px;
    border: 1px solid #0f3460;
}
.logo { font-size: 42px; font-weight: 900; letter-spacing: -2px; }
.logo-re { color: #e2e8f0; }
.logo-cl { color: #3b82f6; }
.header-meta h1 { font-size: 20px; font-weight: 600; color: #f1f5f9; margin-bottom: 8px; }
.header-pills { display: flex; flex-wrap: wrap; gap: 8px; }
.pill {
    background: #0f3460;
    color: #93c5fd;
    padding: 3px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 500;
}

/* ── Sections ── */
.section {
    background: #16213e;
    border-radius: 12px;
    padding: 28px 32px;
    margin-bottom: 24px;
    border: 1px solid #1e3a5f;
}
.section-title {
    font-size: 18px;
    font-weight: 700;
    color: #93c5fd;
    margin-bottom: 20px;
    padding-bottom: 10px;
    border-bottom: 1px solid #1e3a5f;
}
.sub-title {
    font-size: 15px;
    font-weight: 600;
    color: #cbd5e1;
    margin: 20px 0 12px;
}
.meta-text { color: #64748b; font-size: 12px; margin-bottom: 16px; }
.empty-msg { color: #64748b; font-style: italic; }
.empty-msg code {
    background: #0f172a;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: monospace;
    color: #93c5fd;
    font-style: normal;
}

/* ── KPI Grid ── */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
}
.kpi-card {
    background: #0f172a;
    border-radius: 10px;
    padding: 20px 16px;
    border: 1px solid #1e3a5f;
    text-align: center;
}
.kpi-card.kpi-highlight { border-color: #3b82f6; }
.kpi-value { font-size: 26px; font-weight: 800; color: #f1f5f9; line-height: 1.1; }
.kpi-label { font-size: 11px; color: #64748b; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.5px; }

/* ── Tables ── */
.table-wrapper { overflow-x: auto; }
.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.data-table thead tr { background: #0f172a; }
.data-table th {
    text-align: left;
    padding: 10px 12px;
    color: #64748b;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 1px solid #1e3a5f;
    white-space: nowrap;
}
.data-table td {
    padding: 9px 12px;
    border-bottom: 1px solid #1a2744;
    vertical-align: middle;
}
.data-table tbody tr:last-child td { border-bottom: none; }
.data-table tbody tr:hover { background: #1e3a5f22; }
.data-table td.rank { color: #64748b; font-size: 12px; font-weight: 600; }
.data-table td.num { text-align: right; font-family: 'SF Mono', 'Fira Code', monospace; color: #cbd5e1; }
.data-table td.gap { color: #f97316; }
.data-table td.conf { color: #94a3b8; }
.data-table td.commune-name { font-weight: 600; color: #f1f5f9; }

/* ── Score Badges ── */
.badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 700;
    font-family: monospace;
    white-space: nowrap;
}
.badge-red    { background: #450a0a; color: #fca5a5; border: 1px solid #ef4444; }
.badge-orange { background: #431407; color: #fdba74; border: 1px solid #f97316; }
.badge-yellow { background: #422006; color: #fde047; border: 1px solid #eab308; }
.badge-blue   { background: #172554; color: #93c5fd; border: 1px solid #3b82f6; }

/* ── Bar chart (commune ranking) ── */
.bar-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 160px;
}
.bar {
    height: 12px;
    border-radius: 3px;
    min-width: 2px;
    flex-shrink: 0;
}
.bar-label {
    font-family: monospace;
    font-size: 12px;
    color: #cbd5e1;
    white-space: nowrap;
}

/* ── Model Validation ── */
.validation-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.validation-card {
    background: #0f172a;
    border-radius: 10px;
    padding: 20px;
    border: 1px solid #1e3a5f;
}
.card-title { font-size: 14px; font-weight: 700; color: #93c5fd; margin-bottom: 14px; }
.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
    border-bottom: 1px solid #1a2744;
}
.metric-row:last-child { border-bottom: none; }
.metric-name { color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.metric-val { font-family: monospace; font-weight: 700; color: #f1f5f9; font-size: 15px; }

/* ── Map ── */
.map-container { text-align: center; }
.map-caption { color: #64748b; font-size: 12px; margin-top: 12px; }

/* ── Footer ── */
footer {
    text-align: center;
    color: #334155;
    font-size: 11px;
    padding: 20px;
    margin-top: 8px;
}

/* ── Print ── */
@media print {
    body { background: #fff; color: #111; }
    header, .section, .kpi-card, .validation-card {
        background: #f8fafc;
        border-color: #e2e8f0;
        break-inside: avoid;
    }
    .section-title, .kpi-value, .card-title { color: #0f172a; }
    .kpi-label, .meta-text, .metric-name { color: #475569; }
    .badge-red    { background: #fee2e2; color: #991b1b; }
    .badge-orange { background: #ffedd5; color: #9a3412; }
    .badge-yellow { background: #fef9c3; color: #854d0e; }
    .badge-blue   { background: #dbeafe; color: #1e40af; }
    .logo-cl { color: #2563eb; }
    .pill { background: #e2e8f0; color: #334155; }
}
"""


# ── Full HTML assembly ────────────────────────────────────────────────────────

def generate_html(
    props_df:    pd.DataFrame,
    communes_df: pd.DataFrame,
    stats:       dict,
    backtest:    Optional[dict],
    top_n:       int,
    profile:     str,
) -> str:
    report_date = date.today().isoformat()
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    header    = build_header(report_date, profile)
    summary   = build_executive_summary(stats, communes_df, backtest)
    props_tbl = build_properties_table(props_df, top_n)
    commune_r = build_commune_ranking(communes_df)
    validation = build_model_validation(backtest)
    map_sec   = build_map_section(props_df)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RE_CL — Reporte de Oportunidades {report_date}</title>
    <style>
{CSS}
    </style>
</head>
<body>
<div class="page-wrapper">
    {header}
    {summary}
    {props_tbl}
    {commune_r}
    {validation}
    {map_sec}
    <footer>
        RE_CL Platform · Modelo {MODEL_VERSION} · Perfil: {profile} · Generado: {now_ts} UTC<br>
        Región Metropolitana de Santiago — Datos CBR 2013-2014 · Uso interno
    </footer>
</div>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a self-contained HTML opportunity report for RE_CL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--top-n", type=int, default=20, metavar="N",
        help="Number of top opportunity properties to include",
    )
    parser.add_argument(
        "--profile", type=str, default="default",
        choices=["default", "location", "growth", "liquidity", "safety", "custom"],
        help="Scoring profile to use",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: data/exports/report_YYYY-MM-DD.html)",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use mock data (no DB required) — for testing/demo",
    )
    args = parser.parse_args()

    # Resolve output path
    if args.output:
        out_path = Path(args.output)
    else:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EXPORTS_DIR / f"report_{date.today().isoformat()}.html"

    # Load data
    use_mock = args.mock
    engine = None

    if not use_mock:
        engine = _get_engine()
        if engine is None:
            logger.warning("DB engine not available — falling back to mock data")
            use_mock = True
        else:
            try:
                # Quick connectivity test
                from sqlalchemy import text
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            except Exception as e:
                logger.warning(f"DB not reachable ({e}) — falling back to mock data")
                use_mock = True

    if use_mock:
        logger.info("Using mock data for report generation")
        props_df    = _mock_properties(args.top_n)
        communes_df = _mock_communes()
        stats       = _mock_summary()
    else:
        logger.info(f"Loading data from DB (profile={args.profile}, top_n={args.top_n})")
        props_df    = load_top_properties(engine, args.top_n, args.profile)
        communes_df = load_commune_stats(engine)
        stats       = load_summary_stats(engine)

        if props_df.empty:
            logger.warning("No scored properties found in DB — falling back to mock data")
            props_df    = _mock_properties(args.top_n)
            communes_df = _mock_communes()
            stats       = _mock_summary()

    backtest = load_backtesting_report()

    # Generate HTML
    html = generate_html(
        props_df    = props_df,
        communes_df = communes_df,
        stats       = stats,
        backtest    = backtest,
        top_n       = args.top_n,
        profile     = args.profile,
    )

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    logger.success(f"Report written: {out_path}  ({len(html):,} bytes)")
    print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    main()
