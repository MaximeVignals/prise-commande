@echo off
rem Double-cliquer : construit l'APK Android avec le vrai catalogue (voir scripts\construire.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\construire.ps1" -Cible apk
pause
