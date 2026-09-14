@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM LUMEN Dashboard — lanzador para Windows (2026-09-11)
REM
REM Ejecutar ESTE .bat FUERA de Hermes (doble clic, o desde una consola normal).
REM Motivo: lanzado desde dentro de Hermes el proceso muere en silencio al
REM cabo de 1-2 minutos (parece que el gestor de procesos de Hermes reapea
REM cualquier `server.py`, que es el mismo ejecutable que el MCP de thinking).
REM ─────────────────────────────────────────────────────────────────────────
setlocal
set THINKING=C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking
set PY=C:\Users\gonzalo\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
set PDB_PATH=C:\Users\gonzalo\pdb-data\lumen-pdb.db

if not exist "%PY%" (
  echo [ERROR] No encuentro el python del venv: %PY%
  pause
  exit /b 1
)

cd /d "%THINKING%" || (echo [ERROR] No encuentro %THINKING% & pause & exit /b 1)

echo.
echo   LUMEN Dashboard -^> http://localhost:9876/
echo   (deja esta ventana abierta; cerrarla para el dashboard)
echo.

"%PY%" -u server.py --dashboard 9876 --standalone

echo.
echo Dashboard detenido.
pause
