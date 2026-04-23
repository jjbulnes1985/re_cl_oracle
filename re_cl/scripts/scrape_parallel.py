"""
scrape_parallel.py
------------------
Orquestador multiagente para scraping paralelo máximo.

Arquitectura:
  - 8 workers base (2 fuentes × 4 tipos), cada uno un proceso independiente
  - Con --split-pages N divide cada combo en N workers de páginas disjuntas
  - Total máximo: 8 × N workers simultáneos (ej. --split-pages 2 → 16 workers)
  - Cada worker tiene su propio browser Playwright + conexión DB
  - Escritura idempotente: upsert por (source, external_id) → sin colisiones

Uso:
    py scripts/scrape_parallel.py                          # 8 workers, 100 pág c/u
    py scripts/scrape_parallel.py --max-pages 200          # 200 pág por worker
    py scripts/scrape_parallel.py --split-pages 2          # 16 workers, 50 pág c/u
    py scripts/scrape_parallel.py --split-pages 4          # 32 workers, 25 pág c/u
    py scripts/scrape_parallel.py --workers 4              # limitar concurrencia
    py scripts/scrape_parallel.py --source portal          # solo Portal Inmobiliario
    py scripts/scrape_parallel.py --source toctoc          # solo Toctoc
    py scripts/scrape_parallel.py --dry-run                # preview sin scraping real
"""

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Configuración de workers ──────────────────────────────────────────────────

SOURCES = {
    "portal": ["portal_inmobiliario"],
    "toctoc": ["toctoc"],
    "all":    ["portal_inmobiliario", "toctoc"],
}

PROPERTY_TYPES = ["apartments", "residential", "land", "retail"]


@dataclass
class WorkerJob:
    source:        str   # "portal_inmobiliario" | "toctoc"
    property_type: str
    start_page:    int
    max_pages:     int
    db_url:        str

    def label(self) -> str:
        end = self.start_page + self.max_pages - 1
        return f"{self.source}|{self.property_type}|p{self.start_page}-{end}"


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


# ── Función de worker (corre en proceso separado) ─────────────────────────────

def _run_worker(job: WorkerJob) -> tuple[str, int, str]:
    """
    Ejecuta un job de scraping en un proceso independiente.
    Retorna (label, n_listings, error_msg).
    Cada proceso tiene su propio event loop + browser Playwright.
    """
    # Re-importar dentro del proceso hijo
    import os
    import sys
    from pathlib import Path as P

    # Asegurar path en proceso hijo
    root = str(P(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)

    from dotenv import load_dotenv
    load_dotenv(P(root) / ".env")

    from loguru import logger as log
    from sqlalchemy import create_engine

    try:
        engine = create_engine(job.db_url, pool_pre_ping=True, pool_size=1, max_overflow=0)

        if job.source == "portal_inmobiliario":
            from src.scraping.portal_inmobiliario import PortalInmobiliarioScraper
            scraper = PortalInmobiliarioScraper(engine=engine)
        elif job.source == "toctoc":
            from src.scraping.toctoc import ToctocScraper
            scraper = ToctocScraper(engine=engine)
        else:
            return job.label(), 0, f"Unknown source: {job.source}"

        n = scraper.run(
            max_pages=job.max_pages,
            start_page=job.start_page,
            property_type=job.property_type,
        )
        return job.label(), n, ""

    except Exception as e:
        return job.label(), 0, str(e)


# ── Construcción de jobs ──────────────────────────────────────────────────────

def build_jobs(
    sources: list[str],
    total_pages: int,
    split_pages: int,
    db_url: str,
) -> list[WorkerJob]:
    """
    Genera la lista de WorkerJobs.

    Con split_pages=1: 1 job por (source, type) → 8 jobs total
    Con split_pages=2: 2 jobs por combo → 16 jobs (cada uno cubre mitad de páginas)
    Con split_pages=4: 4 jobs por combo → 32 jobs
    """
    jobs = []
    pages_per_worker = max(1, total_pages // split_pages)

    for source in sources:
        for ptype in PROPERTY_TYPES:
            for i in range(split_pages):
                start = i * pages_per_worker + 1
                jobs.append(WorkerJob(
                    source        = source,
                    property_type = ptype,
                    start_page    = start,
                    max_pages     = pages_per_worker,
                    db_url        = db_url,
                ))

    return jobs


# ── Ejecución paralela ────────────────────────────────────────────────────────

def run_parallel(
    jobs: list[WorkerJob],
    max_workers: int,
) -> dict:
    """Ejecuta jobs en paralelo con ProcessPoolExecutor."""
    results  = {}
    errors   = {}
    t_start  = time.time()

    logger.info(f"Lanzando {len(jobs)} workers (concurrencia máx: {max_workers})")
    logger.info(f"Workers: {[j.label() for j in jobs]}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_worker, job): job for job in jobs}

        for future in as_completed(futures):
            job = futures[future]
            try:
                label, n, err = future.result(timeout=3600)
                results[label] = n
                if err:
                    errors[label] = err
                    logger.warning(f"[{label}] ERROR: {err}")
                else:
                    logger.success(f"[{label}] DONE: {n:,} listings")
            except Exception as e:
                errors[job.label()] = str(e)
                logger.error(f"[{job.label()}] CRASH: {e}")

    elapsed = time.time() - t_start
    total   = sum(results.values())

    return {
        "total":   total,
        "results": results,
        "errors":  errors,
        "elapsed": elapsed,
    }


# ── Reporte final ─────────────────────────────────────────────────────────────

def print_report(report: dict, db_url: str) -> None:
    elapsed = report["elapsed"]
    total   = report["total"]
    errors  = report["errors"]

    logger.info("=" * 70)
    logger.info("SCRAPING PARALELO — REPORTE FINAL")
    logger.info(f"  Tiempo total: {elapsed/60:.1f} min")
    logger.info(f"  Listings escritos (esta sesión): {total:,}")
    if errors:
        logger.warning(f"  Workers con error: {len(errors)}")
        for label, err in errors.items():
            logger.warning(f"    {label}: {err}")

    logger.info("\nPor worker:")
    for label, n in sorted(report["results"].items()):
        logger.info(f"  {label:<55} {n:>6,}")

    # Totales en DB
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT source, project_type, COUNT(*) as n "
                "FROM scraped_listings "
                "GROUP BY source, project_type "
                "ORDER BY source, project_type"
            )).mappings().all()
            total_db = conn.execute(
                text("SELECT COUNT(*) FROM scraped_listings")
            ).scalar()

        logger.info(f"\nTotales en DB (acumulado):")
        for r in row:
            logger.info(f"  {r['source']:<30} {r['project_type']:<15} {r['n']:>6,}")
        logger.info(f"  {'TOTAL':<45} {total_db:>6,}")
    except Exception as e:
        logger.warning(f"No se pudo consultar DB para totales: {e}")

    logger.info("=" * 70)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scraping paralelo multiagente — Portal Inmobiliario + Toctoc"
    )
    parser.add_argument(
        "--max-pages",   type=int, default=100,
        help="Páginas totales por combo (source, type). Default: 100"
    )
    parser.add_argument(
        "--split-pages", type=int, default=1,
        help="Dividir páginas en N workers por combo. 1=sin split, 2=2 workers/combo. Default: 1"
    )
    parser.add_argument(
        "--workers",     type=int, default=None,
        help="Máximo de procesos simultáneos. Default: total de jobs (sin límite)"
    )
    parser.add_argument(
        "--source",      type=str, default="all",
        choices=list(SOURCES.keys()),
        help="Fuente a scrapear. Default: all"
    )
    parser.add_argument(
        "--dry-run",     action="store_true",
        help="Solo mostrar jobs que se lanzarían, sin scraping real"
    )
    args = parser.parse_args()

    db_url  = _build_db_url()
    sources = SOURCES[args.source]
    jobs    = build_jobs(
        sources     = sources,
        total_pages = args.max_pages,
        split_pages = args.split_pages,
        db_url      = db_url,
    )

    # Concurrencia: por defecto todos los jobs en paralelo
    max_workers = args.workers or len(jobs)

    logger.info("=" * 70)
    logger.info("SCRAPING PARALELO MULTIAGENTE")
    logger.info(f"  Fuentes:       {sources}")
    logger.info(f"  Tipos:         {PROPERTY_TYPES}")
    logger.info(f"  Páginas/combo: {args.max_pages}")
    logger.info(f"  Split:         {args.split_pages}x  ({len(jobs)} workers total)")
    logger.info(f"  Concurrencia:  {max_workers} procesos simultáneos")
    logger.info(f"  Estimado max:  ~{len(jobs) * (args.max_pages // args.split_pages) * 48:,} listings")
    logger.info("=" * 70)

    if args.dry_run:
        logger.info("[DRY RUN] Jobs que se lanzarían:")
        for job in jobs:
            logger.info(f"  {job.label()}")
        logger.info(f"Total jobs: {len(jobs)}")
        return

    report = run_parallel(jobs, max_workers=max_workers)
    print_report(report, db_url)

    # Scoring automático post-scraping
    logger.info("\nEjecutando scraped_to_scored.py para puntuar los nuevos listings...")
    try:
        from src.scoring.scraped_to_scored import main as score_main
        n_scored = score_main()
        logger.success(f"Scoring completado: {n_scored:,} listings puntuados")
    except Exception as e:
        logger.warning(f"Scoring falló (no es crítico): {e}")
        logger.warning("Ejecutar manualmente: py src/scoring/scraped_to_scored.py")


if __name__ == "__main__":
    main()
