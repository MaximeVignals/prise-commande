@echo off
rem Double-cliquer : construit la version Windows avec le vrai catalogue (voir scripts\construire.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\construire.ps1" -Cible windows
pause
