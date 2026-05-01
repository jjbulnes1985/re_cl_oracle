@echo off
REM Nightly Data Inmobiliaria scraper — auto-orchestrator con IP rotation
REM Scheduled via Windows Task Scheduler at 06:00 daily (wake from sleep)
REM
REM run_di_auto.py:
REM   1. Verifica quota en cada cuenta
REM   2. Scrapea con cuenta disponible
REM   3. Si todas agotadas, intenta Cloudflare WARP automaticamente
REM   4. Loguea todo en data\logs\di_auto.log

cd /d "c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl"

echo [%date% %time%] DI auto-orchestrator start >> data\logs\di_nightly.log 2>&1

py scripts\run_di_auto.py >> data\logs\di_nightly.log 2>&1

echo [%date% %time%] Done >> data\logs\di_nightly.log 2>&1
