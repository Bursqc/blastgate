@echo off
setlocal
cd /d "%~dp0"

echo === Blastgate GUI Build ===
echo.

rem -- use Python 3.11
set PYTHON=py -3.11

%PYTHON% -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo [ERR] pip install pyinstaller failed
    pause & exit /b 1
)

rem -- clean previous build
if exist build\Blastgate rmdir /s /q build\Blastgate
if exist dist\Blastgate  rmdir /s /q dist\Blastgate

echo Building...
%PYTHON% -m PyInstaller ^
  --clean ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --name Blastgate ^
  --collect-all ttkbootstrap ^
  --collect-all pydantic ^
  --hidden-import blastgate ^
  --hidden-import blastgate.gui ^
  --hidden-import blastgate.gui.app ^
  --hidden-import blastgate.gui.utils ^
  --hidden-import blastgate.gui.dialogs ^
  --hidden-import blastgate.gui.dialogs.connect ^
  --hidden-import blastgate.gui.dialogs.settings ^
  --hidden-import blastgate.gui.dialogs.wifi ^
  --hidden-import blastgate.gui.dialogs.node_detail ^
  --hidden-import blastgate.gui.dialogs.calibration ^
  --hidden-import blastgate.gui.dialogs.setup_wizard ^
  --hidden-import blastgate.gui.components ^
  --hidden-import blastgate.gui.components.animated_toggle ^
  --hidden-import blastgate.gui.components.dropdown_menu ^
  --hidden-import blastgate.gui.components.loading_spinner ^
  --hidden-import blastgate.gui.components.rounded_tile ^
  --hidden-import blastgate.network ^
  --hidden-import blastgate.network.client ^
  --hidden-import blastgate.network.engine ^
  --hidden-import blastgate.network.discovery ^
  --hidden-import blastgate.network.protocol ^
  --hidden-import blastgate.models ^
  --hidden-import blastgate.models.config ^
  --hidden-import blastgate.models.status ^
  --hidden-import blastgate.models.node ^
  --hidden-import blastgate.controllers ^
  --hidden-import blastgate.controllers.auto_controller ^
  --hidden-import blastgate.utils ^
  --hidden-import blastgate.utils.helpers ^
  --hidden-import blastgate.utils.validators ^
  --hidden-import blastgate.utils.errors ^
  --hidden-import blastgate.utils.firewall ^
  --hidden-import blastgate.constants ^
  --hidden-import blastgate.config ^
  --hidden-import blastgate.logging_config ^
  --hidden-import blastgate.exceptions ^
  --hidden-import PIL ^
  --hidden-import PIL.Image ^
  --hidden-import PIL.ImageTk ^
  --hidden-import PIL.ImageDraw ^
  --hidden-import PIL.ImageFont ^
  blastgate\__main__.py

if errorlevel 1 (
    echo.
    echo [ERR] Build failed!
    pause & exit /b 1
)

echo.
echo [OK] Build complete: dist\Blastgate\Blastgate.exe
echo.

rem -- copy config/logs dir structure next to exe so app finds its paths
if not exist dist\Blastgate\logs mkdir dist\Blastgate\logs

pause
