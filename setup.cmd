@echo off
rem Runs setup.ps1 without changing the PowerShell execution policy. Arguments pass through, e.g. setup.cmd -CheckOnly
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
