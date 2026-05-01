"""
generate_summary_report.py
--------------------------
Generates a consolidated executive HTML report across all use cases.

Usage:
  py src/reports/generate_summary_report.py
  py src/reports/generate_summary_report.py --top 10
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


def _build_db_url():
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


def _fmt_uf(val):
    try:
        v = float(val)
        if v != v: return "—"
        return f"{int(v):,} UF"
    except Exception:
        return "—"


def _score_color(score):
    s = float(score or 0)
    return "#22c55e" if s >= 0.75 else "#eab308" if s >= 0.60 else "#ef4444"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    engine = create_engine(_build_db_url(), pool_pre_ping=True)
    today = date.today().isoformat()

    use_cases = [
        ("gas_station",  "Estaciones de Servicio", "operator"),
        ("pharmacy",     "Farmacias",              "operator"),
        ("supermarket",  "Supermercados",           "operator"),
        ("bank_branch",  "Sucursales Bancarias",    "operator"),
        ("as_is",        "Oportunidades Generales", "value"),
    ]

    sections = ""
    summary_stats = []

    for use_case, label, profile in use_cases:
        with engine.connect() as conn:
            # Stats
            stats = conn.execute(text("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE opportunity_score >= 0.7),
                       ROUND(AVG(opportunity_score)::NUMERIC, 3)
                FROM opportunity.scores
                WHERE use_case = :uc AND investor_profile = :p
            """), {"uc": use_case, "p": profile}).fetchone()

            # Top N
            rows = conn.execute(text("""
                SELECT c.county_name, c.property_type_code,
                       c.surface_land_m2, c.is_eriazo,
                       s.opportunity_score, s.max_payable_uf,
                       v.estimated_uf, v.p25_uf, v.p75_uf,
                       s.drivers
                FROM opportunity.candidates c
                JOIN opportunity.scores s ON s.candidate_id = c.id
                    AND s.use_case = :uc AND s.investor_profile = :p
                LEFT JOIN opportunity.valuations v
                    ON v.candidate_id = c.id AND v.method = 'triangulated'
                WHERE s.opportunity_score >= 0.5
                ORDER BY s.opportunity_score DESC
                LIMIT :n
            """), {"uc": use_case, "p": profile, "n": args.top}).fetchall()

        total, high, avg = stats
        summary_stats.append((label, total, high, avg, use_case))

        rows_html = ""
        for r in rows:
            score = float(r[4] or 0)
            gap_pct = None
            try:
                d = r[9] or {}
                gap_pct = float(d.get("gap_pct", 0)) if d.get("gap_pct") is not None else None
            except Exception:
                pass

            gap_str = ""
            if gap_pct is not None:
                if gap_pct < 0:
                    gap_str = f'<span style="color:#22c55e">{abs(gap_pct):.1f}% bajo mercado</span>'
                else:
                    gap_str = f'<span style="color:#ef4444">{gap_pct:.1f}% sobre mercado</span>'

            rows_html += f"""
            <tr>
              <td style="padding:8px;border-bottom:1px solid #222;color:#fff">{r[0]}</td>
              <td style="padding:8px;border-bottom:1px solid #222;color:#888">{r[1]}</td>
              <td style="padding:8px;border-bottom:1px solid #222;color:#fff;font-weight:bold"
                  style="color:{_score_color(score)}">{int(score*100)}</td>
              <td style="padding:8px;border-bottom:1px solid #222;color:#aaa">{_fmt_uf(r[6])}</td>
              <td style="padding:8px;border-bottom:1px solid #222;color:#f59e0b">{_fmt_uf(r[5])}</td>
              <td style="padding:8px;border-bottom:1px solid #222">{gap_str}</td>
              <td style="padding:8px;border-bottom:1px solid #222;color:#888">{int(r[2] or 0):,} m²</td>
              <td style="padding:8px;border-bottom:1px solid #222;color:#22c55e">{'✓' if r[3] else ''}</td>
            </tr>"""

        sections += f"""
        <div style="margin-bottom:32px">
          <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:12px">
            <h2 style="color:#fff;font-size:18px;margin:0">{label}</h2>
            <span style="color:#666;font-size:12px">
              {int(total or 0):,} candidatos · {int(high or 0):,} score≥70 · avg {avg}
            </span>
          </div>
          <table style="width:100%;border-collapse:collapse;background:#1a1a2e;border-radius:6px;overflow:hidden">
            <thead>
              <tr style="background:#111">
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">COMUNA</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">TIPO</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">SCORE</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">PRECIO EST.</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">MÁX. PAGABLE ⚠</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">DESCUENTO</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">TERRENO</th>
                <th style="padding:8px;text-align:left;color:#888;font-size:11px">ERIAZO</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """

    # Summary table
    summary_html = "".join([
        f"""<tr>
          <td style="padding:10px;border-bottom:1px solid #222;color:#fff">{l}</td>
          <td style="padding:10px;border-bottom:1px solid #222;color:#aaa;text-align:right">{int(t or 0):,}</td>
          <td style="padding:10px;border-bottom:1px solid #222;color:#22c55e;text-align:right">{int(h or 0):,}</td>
          <td style="padding:10px;border-bottom:1px solid #222;color:#aaa;text-align:right">{a}</td>
        </tr>"""
        for l, t, h, a, _ in summary_stats
    ])

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>RE_CL — Reporte Ejecutivo Oportunidades {today}</title>
<style>
  * {{ box-sizing:border-box;margin:0;padding:0 }}
  body {{ background:#0d0d1a;color:#ccc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:32px }}
  h1,h2 {{ font-weight:600 }}
</style>
</head>
<body>
<div style="max-width:1100px;margin:0 auto">

  <div style="margin-bottom:32px">
    <h1 style="color:#fff;font-size:28px;margin-bottom:8px">RE_CL Opportunity Engine — Reporte Ejecutivo</h1>
    <p style="color:#666">{today} · 5 usos comerciales · model v1.0 · data v3.2</p>
  </div>

  <div style="background:#1a0a00;border:1px solid #92400e;border-radius:6px;padding:12px 16px;margin-bottom:24px;font-size:12px;color:#d97706">
    ⚠ <strong>Disclaimer:</strong> Precios estimados y máximos pagables son aproximaciones.
    Cap rates INFO_NO_FIDEDIGNA (proxy USA + spread Chile, ±150 bps).
    No tomar decisiones de inversión sin tasación independiente y due diligence legal.
  </div>

  <!-- Summary table -->
  <div style="margin-bottom:32px">
    <h2 style="color:#fff;font-size:16px;margin-bottom:12px">Resumen por uso comercial</h2>
    <table style="width:100%;border-collapse:collapse;background:#1a1a2e;border-radius:6px;overflow:hidden">
      <thead>
        <tr style="background:#111">
          <th style="padding:10px;text-align:left;color:#888;font-size:11px">USO</th>
          <th style="padding:10px;text-align:right;color:#888;font-size:11px">CANDIDATOS</th>
          <th style="padding:10px;text-align:right;color:#888;font-size:11px">SCORE≥70</th>
          <th style="padding:10px;text-align:right;color:#888;font-size:11px">SCORE PROM.</th>
        </tr>
      </thead>
      <tbody>{summary_html}</tbody>
    </table>
  </div>

  <!-- Sections per use case -->
  {sections}

  <div style="margin-top:32px;padding-top:16px;border-top:1px solid #222;font-size:11px;color:#444">
    RE_CL Opportunity Engine v2 · data v3.2 · model v1.0 · {today}
    · DUDA pendientes: zonificación PRC real, cap rates validados, bank_branch accessibility
  </div>
</div>
</body>
</html>"""

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORTS_DIR / f"executive_summary_{today}.html"
    out.write_text(html, encoding="utf-8")
    logger.info(f"Executive summary: {out}")


if __name__ == "__main__":
    main()
