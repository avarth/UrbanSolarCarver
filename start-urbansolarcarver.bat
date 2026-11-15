@echo off
rem Starts the UrbanSolarCarver browser app. Double-click this file, or run it
rem from a terminal with usc ui options, for example:
rem   start-urbansolarcarver.bat --port 8780
rem It runs on the environment setup-urbansolarcarver.bat made in this folder
rem (.venv), never on a system Python. To use an environment made elsewhere,
rem set USC_VENV to it.
setlocal
title UrbanSolarCarver
set "USC_REPOSITORY=%~dp0"
set "USC_REPOSITORY=%USC_REPOSITORY:~0,-1%"

rem Labels and goto rather than if (...) blocks: a ")" in a path, as in
rem "UrbanSolarCarver-main (1)", would end such a block early.
if defined USC_VENV goto use_given_environment
set "USC_PYTHON=%USC_REPOSITORY%\.venv\Scripts\python.exe"
if not exist "%USC_PYTHON%" goto not_set_up
rem After the folder is moved, .venv's python.exe still names the old folder's Python.
"%USC_PYTHON%" -c "pass" >nul 2>nul
if not "%errorlevel%"=="0" goto does_not_start
goto start

:not_set_up
echo UrbanSolarCarver is not set up in this folder yet.
echo Run setup-urbansolarcarver.bat first.
goto fail

:does_not_start
echo The Python environment in this folder does not start (was the folder moved or renamed?):
echo   "%USC_PYTHON%"
echo To repair it, run setup-urbansolarcarver.bat again.
goto fail

:use_given_environment
set "USC_PYTHON=%USC_VENV%\Scripts\python.exe"
if exist "%USC_PYTHON%" goto start
echo No Python environment was found at USC_VENV:
echo "%USC_VENV%"
echo Unset USC_VENV to use the one in this folder, or point it at another UrbanSolarCarver environment.
goto fail

:start
set "PYTHONPATH=%USC_REPOSITORY%\src"
rem Warp's compiled kernels stay in this folder, like everything the setup made.
if not defined WARP_CACHE_PATH set "WARP_CACHE_PATH=%USC_REPOSITORY%\.runtime\cache\warp"
echo Starting UrbanSolarCarver. Your browser opens when it is ready.
echo Keep this window open while you work; close it to stop UrbanSolarCarver.
"%USC_PYTHON%" -m urbansolarcarver.carver_cli ui %*
if errorlevel 1 goto fail
exit /b 0

:fail
pause
exit /b 1
