REM Copyright © 2026 Alen Pepa.
@echo off
setlocal
cd /d "%~dp0"
title Alen STB - LAN and iPhone connection
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 (
    py -3 local\launcher.py --lan
    goto finished
  )
)
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
  if not errorlevel 1 (
    python local\launcher.py --lan
    goto finished
  )
)
echo Python 3.10 or newer is required once on this computer.
echo Install it from https://www.python.org/downloads/windows/
echo Then open Start-Alen-STB.cmd again.
pause
exit /b 1
:finished
if errorlevel 1 (
  echo The local bridge could not start. See the message above.
  pause
)
endlocal
