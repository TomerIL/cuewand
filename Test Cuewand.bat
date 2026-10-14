@echo off
setlocal
title Cuewand self-test
pushd "%~dp0"
if not exist cuewand.py goto notextracted

set "PY="
rem Cuewand-for-Windows.zip carries its own Python: use it first
if exist "python\python.exe" set "PY=python\python.exe"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY goto nopython

%PY% cuewand.py --selftest %*
echo.
pause
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
pause
exit /b 1
