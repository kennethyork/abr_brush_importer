@echo off
REM ──────────────────────────────────────────────────────────────
REM Install ABR Brush Importer plugin for Krita (Windows)
REM ──────────────────────────────────────────────────────────────

set "KRITA_PYKRITA=%APPDATA%\krita\pykrita"

echo ╔══════════════════════════════════════════╗
echo ║   ABR Brush Importer — Krita Plugin      ║
echo ║   (Windows)                               ║
echo ╚══════════════════════════════════════════╝
echo.
echo Installing to: %KRITA_PYKRITA%
echo.

REM Create target directories
if not exist "%KRITA_PYKRITA%\abr_brush_importer" mkdir "%KRITA_PYKRITA%\abr_brush_importer"

REM Create the abr_brushes drop folder for automatic import
if not exist "%APPDATA%\krita\abr_brushes" mkdir "%APPDATA%\krita\abr_brushes"

REM Copy the .desktop manifest (sits alongside the package)
copy /Y "abr_brush_importer.desktop" "%KRITA_PYKRITA%\" >nul

REM Copy the Python package
copy /Y "abr_brush_importer\__init__.py"        "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\abr_parser.py"      "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\auto_import.py"     "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\bundle_writer.py"   "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\gbr_writer.py"      "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\import_db.py"       "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\import_pipeline.py" "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\importer_dialog.py" "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\kpp_writer.py"      "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\krita_resource_db.py" "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\net_utils.py"       "%KRITA_PYKRITA%\abr_brush_importer\" >nul
copy /Y "abr_brush_importer\utils.py"           "%KRITA_PYKRITA%\abr_brush_importer\" >nul

echo Files copied.
echo.
echo Next steps:
echo   1. Open Krita
echo   2. Go to  Settings -^> Configure Krita -^> Python Plugin Manager
echo   3. Enable 'ABR Brush Importer'
echo   4. Restart Krita
echo   5. Use it via  Tools -^> Scripts -^> Import ABR Brushes...
echo.
echo Done!
pause
