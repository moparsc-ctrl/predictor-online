@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if "%~1"=="" (
    echo === Analisis pre-partido - TheStatsAPI ===
    echo.
    set /p HOME_TEAM="Equipo local: "
    set /p AWAY_TEAM="Equipo visitante: "
    set /p MATCH_DATE="Fecha aproximada YYYY-MM-DD (opcional, Enter para omitir): "

    set "ARGS=--home "!HOME_TEAM!" --away "!AWAY_TEAM!""
    if not "!MATCH_DATE!"=="" (
        set "ARGS=!ARGS! --date "!MATCH_DATE!""
    )

    python prematch_analysis.py !ARGS!
) else (
    python prematch_analysis.py %*
)

echo.
pause
endlocal
