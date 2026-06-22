@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3.13 -m venv .venv
  ) else (
    python -m venv .venv
  )
)

call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -e . pyinstaller

if exist build rmdir /s /q build
if exist "dist\Busca Folios" rmdir /s /q "dist\Busca Folios"

call ".venv\Scripts\pyinstaller.exe" --clean --noconfirm BuscaFolios.spec
if errorlevel 1 exit /b 1

where iscc >nul 2>nul
if %errorlevel%==0 (
  iscc installer\BuscaFolios.iss
) else if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer\BuscaFolios.iss
) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles%\Inno Setup 6\ISCC.exe" installer\BuscaFolios.iss
) else (
  echo Inno Setup no esta en PATH. Instala Inno Setup o ejecuta installer\BuscaFolios.iss manualmente.
)

endlocal
