@echo off
REM ===========================================================================
REM LUMEN -> Hermes Agent MCP setup (Windows)
REM
REM Registra los 4 MCP servers de lumen-protocol (filesystem, web, thinking,
REM pdb) en Hermes Agent via JSON-RPC stdio (la ruta verificada con el cliente
REM MCP de Hermes). Crea el venv e instala lumen-mcp si hace falta.
REM
REM Uso:   scripts\setup_hermes_mcp.bat
REM ===========================================================================
setlocal
set "REPO=%~dp0.."
set "VENV_PY=%REPO%\.venv\Scripts\python.exe"

echo LUMEN - Hermes MCP setup
echo   repo: %REPO%

REM ---- 1) venv ----
if not exist "%VENV_PY%" (
    echo Creando venv...
    python -m venv "%REPO%\.venv"
)
if not exist "%VENV_PY%" (
    echo ERROR: no se pudo crear el venv. Instala Python 3.10+ y asegurate de que 'python' este en el PATH.
    exit /b 1
)
echo   venv python: %VENV_PY%

REM ---- 2) lumen-mcp (editable) ----
"%VENV_PY%" -c "import lumen" >nul 2>&1
if errorlevel 1 (
    echo Instalando lumen-mcp (editable^)...
    "%VENV_PY%" -m pip install -e "%REPO%\implementations\python"
)

REM ---- 3) hermes CLI ----
where hermes >nul 2>&1
if errorlevel 1 (
    echo ERROR: 'hermes' no esta en el PATH. Instala Hermes Agent primero:
    echo   curl -fsSL https://hermes-agent.nousresearch.com/install.sh ^| bash
    exit /b 1
)

REM ---- 4) registrar los 4 servers (idempotente) ----
for %%S in (filesystem web thinking pdb) do (
    hermes mcp list 2>nul | findstr /C:"lumen-%%S" >nul
    if errorlevel 1 (
        echo Registrando lumen-%%S...
        hermes mcp add "lumen-%%S" --command "%VENV_PY%" --args "%REPO%\implementations\mcp-servers\%%S\server.py"
    ) else (
        echo lumen-%%S ya registrado
    )
)

REM ---- 5) verificacion ----
echo.
echo Verificacion:
hermes mcp list
echo.
echo Listo. Reinicia Hermes (/reset o sesion nueva) para cargar las
echo 115 tools (buscalas como mcp__lumen_*).
endlocal
