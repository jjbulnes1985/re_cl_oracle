@echo off
REM Nightly Data Inmobiliaria scraper — picks next unscraped commune
REM Scheduled via Windows Task Scheduler at 01:00 daily
REM Run 'py scripts/setup_datainmobiliaria_task.py' to register the task

cd /d "c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl"

echo [%date% %time%] Starting nightly datainmobiliaria scrape >> data\logs\datainmobiliaria_nightly.log 2>&1

py src\scraping\datainmobiliaria.py --next-commune --min-year 2019 --max-pages 100 >> data\logs\datainmobiliaria_nightly.log 2>&1

echo [%date% %time%] Done >> data\logs\datainmobiliaria_nightly.log 2>&1
