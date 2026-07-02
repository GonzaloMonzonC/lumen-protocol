@echo off
REM PDB CLI wrapper for cmd.exe
set PDB_DIR=%~dp0
python "%PDB_DIR%pdb_cli.py" %*
