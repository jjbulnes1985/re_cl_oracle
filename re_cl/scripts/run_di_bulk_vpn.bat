@echo off
REM Data Inmobiliaria — bulk scrape con VPN activa
REM Corre este script DESPUES de conectar ProtonVPN manualmente
REM Scrapea hasta 10 comunas seguidas (1 por "vuelta de quota")
REM Tiempo estimado: ~20-30 minutos

cd /d "c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl"
if not exist "data\logs" mkdir data\logs

echo.
echo ============================================================
echo  RE_CL - Data Inmobiliaria Bulk Scrape (con VPN)
echo ============================================================
echo.

REM Verificar estado del checkpoint antes de empezar
echo [Estado actual de comunas scrapeadas:]
py src\scraping\datainmobiliaria.py --list-status
echo.

set COMUNAS_SCRAPEADAS=0

:loop
REM Verificar si quedan comunas por scrapear
py src\scraping\datainmobiliaria.py --list-status 2>&1 | findstr "TODO" >nul
if errorlevel 1 (
    echo [LISTO] Todas las comunas ya fueron scrapeadas.
    goto :done
)

set /a COMUNAS_SCRAPEADAS+=1
echo [%date% %time%] Scrapeando comuna %COMUNAS_SCRAPEADAS%/10...
echo [%date% %time%] Comuna %COMUNAS_SCRAPEADAS% iniciada >> data\logs\datainmobiliaria_vpn.log

py src\scraping\datainmobiliaria.py --next-commune --min-year 2019 --max-pages 100 >> data\logs\datainmobiliaria_vpn.log 2>&1

if errorlevel 1 (
    echo [AVISO] Posible quota agotada o error. Revisar log.
    echo Intentando continuar en 10 segundos...
    timeout /t 10 /nobreak >nul
)

REM Despues de cada comuna, esperar 30s para ser amable con el servidor
echo [%date% %time%] Esperando 30 segundos antes de la siguiente comuna...
timeout /t 30 /nobreak >nul

REM Maximo 10 comunas por sesion VPN
if %COMUNAS_SCRAPEADAS% geq 10 (
    echo.
    echo [Limite de sesion alcanzado: 10 comunas]
    echo Puedes correr este script de nuevo para continuar.
    goto :done
)

goto :loop

:done
echo.
echo ============================================================
echo  Comunas scrapeadas en esta sesion: %COMUNAS_SCRAPEADAS%
echo ============================================================
echo.
py src\scraping\datainmobiliaria.py --list-status
echo.
echo Log completo en: data\logs\datainmobiliaria_vpn.log
echo.
pause
