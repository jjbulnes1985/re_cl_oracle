@echo off
REM Nightly Data Inmobiliaria scraper — multi-account rotation (3 cuentas)
REM Scheduled via Windows Task Scheduler at 06:00 daily (wake from sleep)
REM Run 'py scripts/setup_datainmobiliaria_task.py' to register the task

cd /d "c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl"

echo [%date% %time%] Starting DI nightly bulk scrape  >> data\logs\di_nightly.log 2>&1

py scripts\run_di_bulk_multi.py --min-year 2019 --max-pages 100 >> data\logs\di_nightly.log 2>&1

echo [%date% %time%] Done >> data\logs\di_nightly.log 2>&1
