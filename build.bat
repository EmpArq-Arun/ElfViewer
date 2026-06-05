@echo off
REM =========================================================================
REM  Linker MemMap Viewer — Windows EXE builder
REM  Double-click this file, or run from Command Prompt inside the lmv\ folder
REM =========================================================================

echo.
echo  Linker MemMap Viewer — Building EXE
echo  =====================================
echo.

REM Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

REM Install / upgrade dependencies
echo  [1/3] Installing dependencies...
pip install bottle pyinstaller --quiet --upgrade
if errorlevel 1 (
    echo  [ERROR] pip install failed
    pause
    exit /b 1
)

REM Clean previous build
echo  [2/3] Cleaning previous build...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

REM Build the exe
echo  [3/3] Building exe (this takes 30-60 seconds)...
pyinstaller linker_memmap.spec --noconfirm
if errorlevel 1 (
    echo  [ERROR] PyInstaller build failed — see output above
    pause
    exit /b 1
)

echo.
echo  =========================================
echo   BUILD COMPLETE
echo   Output: dist\LinkerMemMap.exe
echo   Size:   (see above)
echo  =========================================
echo.
echo  Test it now? Press any key to run it.
pause
dist\LinkerMemMap.exe
