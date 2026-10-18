@echo off
rem Starts the UrbanSolarCarver browser app. Double-click this file, or run it
rem from a terminal with usc ui options, for example:
rem   start-urbansolarcarver.bat --port 8780
rem The first run installs UrbanSolarCarver with setup_env.py. To use an
rem environment made elsewhere (setup_env.py --venv-dir), set USC_VENV to it.
setlocal
title UrbanSolarCarver
set "USC_REPOSITORY=%~dp0"
set "USC_REPOSITORY=%USC_REPOSITORY:~0,-1%"

rem Labels and goto rather than if (...) blocks: a ")" in a path, as in
rem "Program Files (x86)", would end such a block early.
if defined USC_VENV goto use_given_environment
call :find_environment
if defined USC_PYTHON goto start
goto install

:use_given_environment
set "USC_PYTHON=%USC_VENV%\Scripts\python.exe"
if exist "%USC_PYTHON%" goto start
echo No Python environment was found at USC_VENV:
echo %USC_VENV%
echo Unset USC_VENV to use the one in this folder, or point it at an environment made by setup_env.py.
goto fail

:install
echo UrbanSolarCarver is not installed yet. Installing it now with setup_env.py; this takes several minutes.
set "USC_SYSTEM_PYTHON="
where py >nul 2>nul && set "USC_SYSTEM_PYTHON=py -3"
if not defined USC_SYSTEM_PYTHON where python >nul 2>nul && set "USC_SYSTEM_PYTHON=python"
if not defined USC_SYSTEM_PYTHON goto no_system_python
pushd "%USC_REPOSITORY%"
%USC_SYSTEM_PYTHON% setup_env.py
set "USC_INSTALL_RESULT=%errorlevel%"
popd
if not "%USC_INSTALL_RESULT%"=="0" goto install_failed
call :find_environment
if defined USC_PYTHON goto start
goto install_failed

:no_system_python
echo Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH"), then run this file again.
goto fail

:install_failed
echo The installation did not finish. Read the messages above, then run this file again.
goto fail

:start
set "PYTHONPATH=%USC_REPOSITORY%\src"
echo Starting UrbanSolarCarver. Your browser opens when it is ready.
echo Keep this window open while you work; close it to stop UrbanSolarCarver.
"%USC_PYTHON%" -m urbansolarcarver.carver_cli ui %*
if errorlevel 1 goto fail
exit /b 0

:fail
pause
exit /b 1

rem The environments setup_env.py makes: .venv in this folder, or ~/.usc-venv
rem when this folder's path is too long for Windows.
:find_environment
set "USC_PYTHON="
if exist "%USC_REPOSITORY%\.venv\Scripts\python.exe" set "USC_PYTHON=%USC_REPOSITORY%\.venv\Scripts\python.exe" & exit /b 0
if exist "%USERPROFILE%\.usc-venv\Scripts\python.exe" set "USC_PYTHON=%USERPROFILE%\.usc-venv\Scripts\python.exe"
exit /b 0
