@echo off
rem Sets up UrbanSolarCarver in this folder. Run it once after unzipping, then
rem start the app with start-urbansolarcarver.bat. Run it again to repair or update.
rem
rem What it downloads, each file checked before it is used:
rem   uv, the version below, from github.com/astral-sh/uv, against USC_UV_SHA256 below;
rem   Python, uv's own build, against the checksums built into uv;
rem   PyTorch and the other packages, against requirements-lock-hashed.txt.
rem Everything it makes stays in this folder (.runtime and .venv): nothing on PATH,
rem nothing in the registry, no administrator rights, any installed Python untouched.
rem PowerShell is used only to download, check and unzip uv, with fixed commands.
rem Options go to setup_env.py, for example --cpu for the CPU build of PyTorch.
setlocal
title UrbanSolarCarver setup
set "USC_UV_VERSION=0.13.8"
set "USC_UV_SHA256=529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8"
set "USC_PYTHON_VERSION=3.14.6"

set "USC_FOLDER=%~dp0"
set "USC_FOLDER=%USC_FOLDER:~0,-1%"
set "USC_RUNTIME=%USC_FOLDER%\.runtime"
set "USC_UV_FILE=uv-x86_64-pc-windows-msvc.zip"
set "USC_UV_URL=https://github.com/astral-sh/uv/releases/download/%USC_UV_VERSION%/%USC_UV_FILE%"
set "USC_DOWNLOAD=%USC_RUNTIME%\download\%USC_UV_FILE%"
set "USC_UV=%USC_RUNTIME%\uv\uv.exe"
set "USC_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

rem Labels and goto rather than if (...) blocks: a ")" in a path, as in
rem "UrbanSolarCarver-main (1)", would end such a block early.

rem 1. Checks, before anything is downloaded.
set "USC_ARCHITECTURE=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "USC_ARCHITECTURE=%PROCESSOR_ARCHITEW6432%"
if /i not "%USC_ARCHITECTURE%"=="AMD64" goto not_x64
if not exist "%USC_POWERSHELL%" goto no_powershell
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$venv = Join-Path $env:USC_FOLDER '.venv'; $long = (Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled; if (($venv.Length + 170 -gt 260) -and ($long -ne 1)) { exit 3 }; exit 0"
if errorlevel 3 goto path_too_long
if not exist "%USC_RUNTIME%\download" mkdir "%USC_RUNTIME%\download" 2>nul
type nul > "%USC_RUNTIME%\write-check" 2>nul
if not exist "%USC_RUNTIME%\write-check" goto not_writable
del "%USC_RUNTIME%\write-check"

rem 2. What it will do.
echo This sets up UrbanSolarCarver in this folder:
echo   %USC_FOLDER%
echo It downloads, checking each file before it is used:
echo   uv %USC_UV_VERSION%, about 16 MB, from github.com/astral-sh/uv
echo   Python %USC_PYTHON_VERSION%, about 30 MB, uv's own build, from github.com/astral-sh/python-build-standalone
echo   PyTorch from download.pytorch.org: about 2.6 GB with CUDA (NVIDIA graphics cards), about 130 MB without
echo   the other packages, about 300 MB, from pypi.org
echo Everything stays in this folder: deleting the folder removes it all.
echo Press a key to start, or close this window to stop.
pause >nul

rem 3. uv: a zip already downloaded is checked again and reused.
if defined USC_UV_ZIP goto copy_given_zip
if exist "%USC_DOWNLOAD%" goto check_uv
echo Downloading uv %USC_UV_VERSION%...
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:USC_UV_URL -OutFile $env:USC_DOWNLOAD"
if errorlevel 1 goto download_failed
goto check_uv

rem For the tests only: USC_UV_ZIP names a local file that stands in for the download.
:copy_given_zip
copy /y "%USC_UV_ZIP%" "%USC_DOWNLOAD%" >nul
if errorlevel 1 goto download_failed

:check_uv
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "if ((Get-FileHash -Algorithm SHA256 -LiteralPath $env:USC_DOWNLOAD).Hash -ne $env:USC_UV_SHA256) { Remove-Item -LiteralPath $env:USC_DOWNLOAD -Force; exit 2 }; exit 0"
if errorlevel 2 goto hash_mismatch
if errorlevel 1 goto unzip_failed
echo uv %USC_UV_VERSION%: SHA-256 checked.
if exist "%USC_RUNTIME%\uv" rmdir /s /q "%USC_RUNTIME%\uv"
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:USC_DOWNLOAD -DestinationPath (Join-Path $env:USC_RUNTIME 'uv') -Force"
if errorlevel 1 goto unzip_failed
if not exist "%USC_UV%" goto unzip_failed

rem 4. Python: uv's own build in .runtime\python, for this process only. uv reads
rem no configuration file, ignores any other Python, and adds nothing to PATH or
rem the registry (--no-bin, --no-registry).
set "UV_PYTHON_INSTALL_DIR=%USC_RUNTIME%\python"
set "UV_CACHE_DIR=%USC_RUNTIME%\cache\uv"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_NO_CONFIG=1"
set "VIRTUAL_ENV="
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
"%USC_UV%" python install %USC_PYTHON_VERSION% --no-bin --no-registry
if errorlevel 1 goto python_failed
"%USC_UV%" python find --system %USC_PYTHON_VERSION% > "%USC_RUNTIME%\python-path.txt"
if errorlevel 1 goto python_failed
set "USC_PYTHON="
set /p USC_PYTHON=<"%USC_RUNTIME%\python-path.txt"
if not defined USC_PYTHON goto python_failed
if not exist "%USC_PYTHON%" goto python_failed

rem 5. The environment (.venv) and the packages, every download checked.
"%USC_PYTHON%" "%USC_FOLDER%\setup_env.py" --self-contained %*
if errorlevel 1 goto setup_failed
echo.
echo Setup finished. Start UrbanSolarCarver with start-urbansolarcarver.bat.
echo To remove it, delete this folder: setup kept everything it made inside it.
pause
exit /b 0

:not_x64
echo This setup needs 64-bit Windows on an Intel or AMD processor (found %USC_ARCHITECTURE%).
echo PyTorch with CUDA is not made for Windows on ARM.
goto fail

:no_powershell
echo Windows PowerShell was not found at %USC_POWERSHELL%; setup needs it to download uv.
goto fail

:path_too_long
echo This folder's path is too long for PyTorch's files:
echo   %USC_FOLDER%
echo Move this folder to a shorter path, for example C:\UrbanSolarCarver, and run setup again.
goto fail

:not_writable
echo Setup cannot write in this folder:
echo   %USC_FOLDER%
echo Move it somewhere you can write, for example C:\UrbanSolarCarver, and run setup again.
goto fail

:download_failed
if exist "%USC_DOWNLOAD%" del "%USC_DOWNLOAD%"
echo uv could not be downloaded from %USC_UV_URL%
echo Check the internet connection (or a proxy or antivirus that blocks it) and run setup again.
goto fail

:hash_mismatch
echo The downloaded uv does not match the SHA-256 in this script, so it was deleted and not used.
echo The download may have been cut short or changed on the way. Run setup again; if this repeats,
echo do not use this network, and report it.
goto fail

:unzip_failed
echo uv could not be checked or unzipped into %USC_RUNTIME%\uv. Run setup again.
goto fail

:python_failed
echo uv could not install Python %USC_PYTHON_VERSION% into %USC_RUNTIME%\python.
echo Read the messages above, check the internet connection, and run setup again.
goto fail

:setup_failed
echo The setup did not finish. Read the messages above, then run setup again:
echo what was already downloaded is checked again and reused.
goto fail

:fail
pause
exit /b 1
