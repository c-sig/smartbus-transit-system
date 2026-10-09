@echo off
title SmartBus Intercity Terminal Management and Standby Queue System
echo ====================================================================
echo Starting SmartBus POS and Terminal Operations Desktop App (PITX)...
echo ====================================================================
python "%~dp0smartbus_app.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with an error code.
    pause
)
