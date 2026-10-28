@echo off
rem Launcher do instalador visual: contorna a politica de execucao do
rem PowerShell para o usuario nao precisar mexer em nada.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Instalador-Media-Server-Windows.ps1"
