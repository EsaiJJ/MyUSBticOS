@echo off
REM Build vault-runner.exe on Windows.
REM Requires: Python 3.8+ and pip install pyinstaller
setlocal
cd /d "%~dp0\.."
echo >> Installing PyInstaller (if missing)
python -m pip install --quiet --upgrade pyinstaller || goto :err
echo >> Building vault-runner.exe
python -m PyInstaller --clean --noconfirm windows\vault-runner.spec || goto :err
echo.
echo Built: dist\vault-runner.exe
goto :eof
:err
echo Build failed.
exit /b 1
