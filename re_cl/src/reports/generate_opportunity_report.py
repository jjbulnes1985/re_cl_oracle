"""
generate_opportunity_report.py
-------------------------------
Generates a self-contained HTML report of top opportunity candidates.

Usage:
  py src/reports/generate_opportunity_report.py                           # top 20 gas_station
  py src/reports/generate_opportunity_report.py --use-case as_is --top 50
  py src/reports/generate_opportunity_report.py --commune Maipú
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

EXPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "exports"


def _build_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "re_cl_user"),
        pwd=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "re_cl"),
    )


def load_top_opportunities(engine, use_case: str, commune: str | None, top_n: int) -> list[dict]:
    profile = "operator" if use_case not in ("as_is",) else "value"
    params: dict = {"use_case": use_case, "profile": profile, "top_n": top_n}
    filters = ""
    if commune:
        filters = "AND c.county_name = :commune"
        params["commune"] = commune

    rows = engine.connect().execute(text(f"""
        SELECT
            c.id, c.address, c.county_name,
            c.property_type_code, c.surface_land_m2, c.surface_building_m2,
            c.is_eriazo, c.rol_sii,
            c.last_transaction_uf, c.last_transaction_date,
            c.latitude, c.longitude,
            s.opportunity_score, s.undervaluation_score, s.use_specific_score,
            s.max_payable_uf, s.drivers,
            v.estimated_uf, v.p25_uf, v.p50_uf, v.p75_uf, v.confidence
        FROM opportunity.candidates c
        JOIN opportunity.scores s
            ON s.candidate_id = c.id
            AND s.use_case = :use_case
            AND s.investor_profile = :profile
        LEFT JOIN opportunity.valuations v
            ON v.candidate_id = c.id AND v.method = 'triangulated'
        WHERE s.opportunity_score >= 0.5 {filters}
        ORDER BY s.opportunity_score DESC
        LIMIT :top_n
    """), params).fetchall()

    return [dict(r._mapping) for r in rows]


def _fmt_uf(val) -> str:
    try:
        if val is None:
            return "—"
        v = float(val)
        if v != v:  # NaN check
            return "—"
        return f"{int(v):,} UF"
    except (TypeError, ValueError):
        return "—"


def _score_bar(score: float) -> str:
    pct = int(score * 100)
    color = "#22c55e" if score >= 0.75 else "#eab308" if score >= 0.60 else "#ef4444"
    return f"""<div style="background:#333;border-radius:4px;height:8px;width:100%">
        <div style="background:{color};width:{pct}%;height:8px;border-radius:4px"></div></div>
        <small style="color:{color}">{pct}/100</small>"""


def generate_html(rows: list[dict], use_case: str, commune: str | None) -> str:
    title = f"RE_CL Opportunity Report — {use_case.replace('_', ' ').title()}"
    if commune:
        title += f" · {commune}"
    today = date.today().isoformat()

    cards = ""
    for i, r in enumerate(rows, 1):
        drivers = r.get("drivers") or {}
        gap_pct = drivers.get("gap_pct")
        gap_str = f"{abs(float(gap_pct)):.1f}% bajo mercado" if gap_pct and float(gap_pct) < 0 else (f"{float(gap_pct):.1f}% sobre mercado" if gap_pct else "—")
        gmaps = f"https://maps.google.com/?q={r['latitude']},{r['longitude']}" if r.get('latitude') else "#"

        cards += f"""
        <div style="background:#1a1a2e;border:1px solid #333;border-radius:8px;padding:20px;margin-bottom:16px">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
                <div>
                    <h3 style="margin:0;color:#fff;font-size:16px">#{i} — {r['county_name']}</h3>
                    <p style="margin:4px 0 0;color:#888;font-size:13px">{r['property_type_code']} · {int(r['surface_land_m2'] or 0):,} m² terreno</p>
                </div>
                <div style="text-align:right">
                    {_score_bar(float(r['opportunity_score'] or 0))}
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px">
                <div style="background:#0d0d1a;padding:10px;border-radius:6px">
                    <div style="color:#888;font-size:11px;margin-bottom:4px">PRECIO ESTIMADO</div>
                    <div style="color:#fff;font-size:15px;font-weight:bold">{_fmt_uf(r.get('p50_uf') or r.get('estimated_uf'))}</div>
                    <div style="color:#666;font-size:11px">{_fmt_uf(r.get('p25_uf'))} – {_fmt_uf(r.get('p75_uf'))}</div>
                </div>
                <div style="background:#0d0d1a;padding:10px;border-radius:6px">
                    <div style="color:#888;font-size:11px;margin-bottom:4px">MÁX. PAGABLE ⚠</div>
                    <div style="color:#f59e0b;font-size:15px;font-weight:bold">{_fmt_uf(r.get('max_payable_uf'))}</div>
                    <div style="color:#666;font-size:11px">cap rate 8% proxy</div>
                </div>
                <div style="background:#0d0d1a;padding:10px;border-radius:6px">
                    <div style="color:#888;font-size:11px;margin-bottom:4px">SUBVALORACIÓN</div>
                    <div style="color:#22c55e;font-size:15px;font-weight:bold">{gap_str}</div>
                    <div style="color:#666;font-size:11px">vs. comparables zona</div>
                </div>
            </div>

            <div style="margin-bottom:12px">
                <div style="color:#888;font-size:11px;margin-bottom:6px;font-weight:bold">⚠ RIESGOS (verificar antes de actuar)</div>
                <ul style="margin:0;padding-left:16px;color:#ccc;font-size:13px">
                    {'<li>Confianza valoración baja — pocos comparables en zona</li>' if (r.get('confidence') or 0) < 0.5 else ''}
                    {'<li>Sin transacción reciente — precio estimado puede estar desactualizado</li>' if not r.get('last_transaction_date') else ''}
                    <li>Verificar zonificación PRC y uso permitido en DOM</li>
                    <li>Cap rate referencial — INFO_NO_FIDEDIGNA, validar con tasador</li>
                </ul>
            </div>

            <div style="margin-bottom:12px">
                <div style="color:#888;font-size:11px;margin-bottom:6px;font-weight:bold">✓ TESIS DE INVERSIÓN</div>
                <ul style="margin:0;padding-left:16px;color:#ccc;font-size:13px">
                    {f'<li>{gap_str} respecto al mercado comparable</li>' if gap_pct else ''}
                    {'<li>Sitio subutilizado (terreno eriazo detectado)</li>' if r.get('is_eriazo') else ''}
                    <li>{r['county_name']} — {r['property_type_code']} · {int(r['surface_land_m2'] or 0):,} m²</li>
                    {f'<li>Rol SII: {r["rol_sii"]}</li>' if r.get("rol_sii") else ''}
                </ul>
            </div>

            <div style="margin-bottom:12px">
                <div style="color:#888;font-size:11px;margin-bottom:6px;font-weight:bold">PRÓXIMOS PASOS DD</div>
                <ol style="margin:0;padding-left:16px;color:#ccc;font-size:13px">
                    <li>Verificar uso permitido en plan regulador comunal (DOM {r['county_name']})</li>
                    <li>Certificado de informaciones previas e hipotecas (CBR)</li>
                    <li>Tasación independiente (Tinsa / GPS Property)</li>
                    <li>Confirmar cap rate con corredor comercial local</li>
                </ol>
            </div>

            <div style="display:flex;gap:8px">
                <a href="{gmaps}" target="_blank" style="background:#2563eb;color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none;font-size:12px">Google Maps</a>
                {'<a href="https://www.sii.cl" target="_blank" style="background:#374151;color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none;font-size:12px">Ficha SII</a>' if r.get("rol_sii") else ''}
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d0d1a; color: #ccc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 24px; }}
  .header {{ max-width: 900px; margin: 0 auto 24px; }}
  .disclaimer {{ background: #1a1209; border: 1px solid #92400e; border-radius: 6px; padding: 12px 16px; margin-bottom: 24px; font-size: 12px; color: #d97706; }}
  .cards {{ max-width: 900px; margin: 0 auto; }}
</style>
</head>
<body>
<div class="header">
  <h1 style="color:#fff;font-size:24px;margin-bottom:8px">{title}</h1>
  <p style="color:#666;font-size:13px">Generado: {today} · RE_CL Opportunity Engine v2 · model v1.0 · {len(rows)} candidatos</p>

  <div class="disclaimer" style="margin-top:16px">
    ⚠ <strong>Disclaimer institucional:</strong> Los precios estimados y máximos pagables son aproximaciones basadas en
    comparables históricos CBR y cap rates proxy (INFO_NO_FIDEDIGNA::pendiente_validación). Banda de incertidumbre ±150 bps
    en cap rates. <strong>No tomar decisiones de inversión sin tasación independiente y due diligence legal completo.</strong>
    Fuente cap rates: proxy USA net lease + spread Chile (B+E Q4-2024).
  </div>
</div>

<div class="cards">
  {cards}
</div>

<div style="max-width:900px;margin:24px auto;padding-top:16px;border-top:1px solid #222;font-size:11px;color:#444">
  RE_CL Opportunity Engine v2 · data v3.2 · model v1.0 · {today} ·
  DUDA pendientes: zonificación PRC, road_accessibility, bank_branch OSM, cap rates validados
</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-case", default="gas_station")
    parser.add_argument("--commune",  default=None)
    parser.add_argument("--top",      type=int, default=20)
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)

    logger.info(f"Loading top {args.top} {args.use_case} opportunities...")
    rows = load_top_opportunities(engine, args.use_case, args.commune, args.top)
    logger.info(f"  {len(rows)} candidates loaded")

    html = generate_html(rows, args.use_case, args.commune)

    commune_suffix = f"_{args.commune.lower().replace(' ','_')}" if args.commune else ""
    fname = f"opportunity_{args.use_case}{commune_suffix}_{date.today()}.html"
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORTS_DIR / fname
    out.write_text(html, encoding="utf-8")
    logger.info(f"Report written: {out}")


if __name__ == "__main__":
    main()
