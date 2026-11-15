@echo off
rem Sets up UrbanSolarCarver in this folder. Unzip the whole repository first, run
rem this once, then start the app with start-urbansolarcarver.bat. Run it again to
rem repair or update.
rem
rem What it downloads, each file checked before it is used:
rem   uv, the version below, from github.com/astral-sh/uv, against USC_UV_SHA256 below;
rem   Python, uv's own build, against the checksums built into uv;
rem   PyTorch and the other packages, against requirements-lock-hashed.txt.
rem Everything it makes stays in this folder (.runtime and .venv): nothing on PATH,
rem nothing in the registry, no administrator rights, any installed Python untouched.
rem The one exception, only if you answer Y at the end: a shortcut on the desktop.
rem PowerShell is used only for fixed commands: the checks, downloading, checking and
rem unzipping uv, and the shortcut.
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
rem "UrbanSolarCarver-main (1)", would end such a block early. Every echoed path
rem is in quotes, so an "&" in it, as in "R&D", does not split the line.

rem 1. Checks, before anything is downloaded.
set "USC_ARCHITECTURE=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "USC_ARCHITECTURE=%PROCESSOR_ARCHITEW6432%"
if /i not "%USC_ARCHITECTURE%"=="AMD64" goto not_x64
rem Run from inside the zip, Explorer copies this file alone to a temporary folder.
if not exist "%USC_FOLDER%\setup_env.py" goto not_unzipped
if not exist "%USC_FOLDER%\requirements-lock.txt" goto not_unzipped
if not exist "%USC_FOLDER%\requirements-lock-hashed.txt" goto not_unzipped
if not exist "%USC_POWERSHELL%" goto no_powershell

rem Your own pip and uv settings do not apply here: a PIP_TARGET, for example,
rem would install outside this folder. Only the ones set below count.
for /f "delims==" %%V in ('set UV_ 2^>nul') do set "%%V="
for /f "delims==" %%V in ('set PIP_ 2^>nul') do set "%%V="

rem The disk space it needs: the CUDA build of PyTorch with its download cache, or
rem the CPU build (with --cpu, or when no NVIDIA driver is found).
set "USC_NEEDED_GB=7"
set "USC_HAS_NVIDIA="
where nvidia-smi >nul 2>nul && set "USC_HAS_NVIDIA=1"
if exist "%ProgramFiles%\NVIDIA Corporation\NVSMI\nvidia-smi.exe" set "USC_HAS_NVIDIA=1"
if not defined USC_HAS_NVIDIA set "USC_NEEDED_GB=1.5"
for %%A in (%*) do if /i "%%~A"=="--cpu" set "USC_NEEDED_GB=1.5"

rem A OneDrive folder (exit 4), a path too long for PyTorch's files (exit 3), too
rem little free disk space (exit 5). A drive whose free space cannot be read, such
rem as a network share, gets a note and setup continues.
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$folder = $env:USC_FOLDER; foreach ($name in 'OneDrive', 'OneDriveConsumer', 'OneDriveCommercial') { $synced = [Environment]::GetEnvironmentVariable($name); if ($synced -and ($folder + '\').StartsWith($synced.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { exit 4 } }; $long = (Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled; if ((($folder + '\.venv').Length + 170 -gt 260) -and ($long -ne 1)) { exit 3 }; try { $free = (New-Object IO.DriveInfo([IO.Path]::GetPathRoot($folder))).AvailableFreeSpace } catch { Write-Output 'Free disk space could not be checked on this drive; setup continues.'; exit 0 }; if ($free -lt [double]$env:USC_NEEDED_GB * 1GB) { Write-Output ('Setup needs about {0} GB of free disk space on this drive; {1:N1} GB is free.' -f $env:USC_NEEDED_GB, ($free / 1GB)); exit 5 }; exit 0"
if errorlevel 5 goto low_disk
if errorlevel 4 goto onedrive
if errorlevel 3 goto path_too_long
if not exist "%USC_RUNTIME%\download" mkdir "%USC_RUNTIME%\download" 2>nul
type nul > "%USC_RUNTIME%\write-check" 2>nul
if not exist "%USC_RUNTIME%\write-check" goto not_writable
del "%USC_RUNTIME%\write-check"

rem Temporary files of this setup stay in the folder too.
if not exist "%USC_RUNTIME%\tmp" mkdir "%USC_RUNTIME%\tmp"
set "TEMP=%USC_RUNTIME%\tmp"
set "TMP=%USC_RUNTIME%\tmp"

rem 2. What it will do.
echo This sets up UrbanSolarCarver in this folder:
echo   "%USC_FOLDER%"
echo It downloads, checking each file before it is used:
echo   uv %USC_UV_VERSION%, about 16 MB, from github.com/astral-sh/uv
echo   Python %USC_PYTHON_VERSION%, about 22 MB, uv's own build, from github.com/astral-sh/python-build-standalone
echo   PyTorch from download.pytorch.org: about 2.6 GB with CUDA (NVIDIA graphics cards), about 130 MB without
echo   the other packages, about 300 MB, from pypi.org
echo It needs about %USC_NEEDED_GB% GB of free disk space.
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
rem Exactly 0 only: "if errorlevel 1" misses a crashed PowerShell's negative exit code.
if not "%errorlevel%"=="0" goto unzip_failed
echo uv %USC_UV_VERSION%: SHA-256 checked.
if exist "%USC_RUNTIME%\uv" rmdir /s /q "%USC_RUNTIME%\uv"
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:USC_DOWNLOAD -DestinationPath (Join-Path $env:USC_RUNTIME 'uv') -Force"
if errorlevel 1 goto unzip_failed
if not exist "%USC_UV%" goto unzip_failed

rem 4. Python: uv's own build in .runtime\python, for this process only. uv reads
rem no configuration file, ignores any other Python, adds nothing to PATH or the
rem registry (--no-bin, --no-registry), and trusts the certificates Windows trusts,
rem as pip does (which helps behind a company proxy).
set "UV_PYTHON_INSTALL_DIR=%USC_RUNTIME%\python"
set "UV_CACHE_DIR=%USC_RUNTIME%\cache\uv"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_NO_CONFIG=1"
set "UV_NATIVE_TLS=1"
set "VIRTUAL_ENV="
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
"%USC_UV%" python install %USC_PYTHON_VERSION% --no-bin --no-registry
if errorlevel 1 goto python_failed
rem The folder uv installs it in, built here rather than read back from uv's output:
rem cmd reads a file in the console code page, which garbles a path with, for
rem example, Greek letters.
set "USC_PYTHON=%USC_RUNTIME%\python\cpython-%USC_PYTHON_VERSION%-windows-x86_64-none\python.exe"
if not exist "%USC_PYTHON%" goto python_failed

rem 5. The environment (.venv) and the packages, every download checked.
"%USC_PYTHON%" "%USC_FOLDER%\setup_env.py" --self-contained %*
if errorlevel 1 goto setup_failed

rem 6. A desktop shortcut, only if asked (the folder may be hidden in AppData).
rem No answer within 30 seconds means N.
echo.
echo Setup finished.
choice /c YN /n /t 30 /d N /m "Make a shortcut on the desktop? [Y/N] "
if not "%errorlevel%"=="1" goto no_shortcut
"%USC_POWERSHELL%" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'UrbanSolarCarver.lnk')); $shortcut.TargetPath = Join-Path $env:USC_FOLDER 'start-urbansolarcarver.bat'; $shortcut.WorkingDirectory = $env:USC_FOLDER; $shortcut.Save()"
if errorlevel 1 goto shortcut_failed
echo Made the UrbanSolarCarver shortcut on the desktop. Deleting this folder leaves that shortcut: delete it by hand.
goto no_shortcut
:shortcut_failed
echo The shortcut could not be made.
:no_shortcut
echo Start UrbanSolarCarver with start-urbansolarcarver.bat in this folder.
echo To remove it, delete this folder: setup kept everything it made inside it.
pause
exit /b 0

:not_x64
echo This setup needs 64-bit Windows on an Intel or AMD processor (found %USC_ARCHITECTURE%).
echo PyTorch with CUDA is not made for Windows on ARM.
goto fail

:not_unzipped
echo setup-urbansolarcarver.bat is not next to the other files of UrbanSolarCarver in:
echo   "%USC_FOLDER%"
echo Unzip the whole folder first, then run setup from there.
goto fail

:no_powershell
echo Windows PowerShell was not found; setup needs it to download uv:
echo   "%USC_POWERSHELL%"
goto fail

:onedrive
echo This folder is in OneDrive:
echo   "%USC_FOLDER%"
echo Setup does not install in a synced folder: OneDrive would upload gigabytes of downloaded packages,
echo and files it locks or keeps online-only break the install.
echo Move this folder out of OneDrive, for example to
echo   "%LOCALAPPDATA%\Programs\UrbanSolarCarver"
echo and run setup again.
goto fail

:low_disk
echo Free some disk space or move this folder to another drive, then run setup again.
goto fail

:path_too_long
echo This folder's path is too long for PyTorch's files:
echo   "%USC_FOLDER%"
echo Move this folder to a shorter path, for example
echo   "%LOCALAPPDATA%\Programs\UrbanSolarCarver"
echo and run setup again.
goto fail

:not_writable
echo Setup cannot write in this folder:
echo   "%USC_FOLDER%"
echo Move it somewhere you can write, for example
echo   "%LOCALAPPDATA%\Programs\UrbanSolarCarver"
echo and run setup again.
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
echo uv could not be checked or unzipped into this folder. Run setup again:
echo   "%USC_RUNTIME%\uv"
goto fail

:python_failed
echo uv could not install Python %USC_PYTHON_VERSION% into this folder:
echo   "%USC_RUNTIME%\python"
echo Read the messages above, check the internet connection, and run setup again.
goto fail

:setup_failed
echo The setup did not finish. Read the messages above, then run setup again:
echo what was already downloaded is checked again and reused.
goto fail

:fail
pause
exit /b 1
