@echo off
setlocal
title Cuewand
pushd "%~dp0"
if not exist cuewand.py goto notextracted

set "PY="
rem For running from the source code. Cuewand-for-Windows.zip has .exe files instead.
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY goto nopython

%PY% cuewand.py %*
if errorlevel 1 pause
exit /b

:notextracted
echo.
echo  This file was started from inside the zip file. Extract the whole Cuewand
echo  folder first (right-click the zip, Extract All), then double-click this
echo  file in the extracted folder.
echo.
pause
exit /b 1

:nopython
echo.
echo  Cuewand needs Python, which was not found on this computer.
echo  Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo  then double-click this file again.
echo.
echo  If you use Anaconda: open "Anaconda Prompt", go to this folder and run
echo      python cuewand.py
echo.
pause
exit /b 1
