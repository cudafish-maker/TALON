@echo off
REM install.bat — T.A.L.O.N. installer for Windows
REM
REM Automatically detects and installs all prerequisites:
REM   - Python 3.12 (via winget)
REM   - Visual Studio Build Tools / C++ compiler (via winget)
REM   - SQLCipher DLL (downloaded from GitHub)
REM   - All Python dependencies
REM
REM Usage:
REM   install.bat              Install everything (client + server)
REM   install.bat --dev        Include development tools (pytest, pyinstaller)
REM
REM NOTE: Run this from an Administrator command prompt if you need
REM       system-level installs (Python, Build Tools). If already
REM       installed, admin is not required.

setlocal enabledelayedexpansion

echo.
echo ============================================
echo   T.A.L.O.N. Installer — Windows
echo ============================================
echo.

REM ---------------------------------------------------------------
REM Check for winget (Windows Package Manager)
REM Available on Windows 10 1709+ and all Windows 11
REM ---------------------------------------------------------------
set HAS_WINGET=false
where winget >nul 2>&1 && set HAS_WINGET=true

if "%HAS_WINGET%"=="true" (
    echo [  OK ] winget found — will use for system installs
) else (
    echo [WARN] winget not found — install App Installer from the Microsoft Store
    echo [WARN] Falling back to manual install instructions where needed
)

REM ---------------------------------------------------------------
REM Check / Install Python
REM ---------------------------------------------------------------
echo.
echo [TALON] Checking Python...

set PYTHON_OK=false
where python >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set PYVER=%%v
    if defined PYVER (
        for /f "tokens=1 delims=." %%a in ("!PYVER!") do set PYMAJOR=%%a
        for /f "tokens=2 delims=." %%a in ("!PYVER!") do set PYMINOR=%%a
        if !PYMAJOR! GEQ 3 if !PYMINOR! GEQ 10 set PYTHON_OK=true
    )
)

if "%PYTHON_OK%"=="true" (
    echo [  OK ] Python !PYVER! found
) else (
    echo [    ] Python 3.10+ not found
    if "%HAS_WINGET%"=="true" (
        echo [TALON] Installing Python 3.12 via winget...
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [FAIL] Python install failed. Download manually from https://python.org
            exit /b 1
        )
        echo [  OK ] Python 3.12 installed
        echo.
        echo [WARN] *** You must restart this command prompt for Python to be on PATH ***
        echo [WARN] *** Close this window, open a new command prompt, and run install.bat again ***
        echo.
        pause
        exit /b 0
    ) else (
        echo [FAIL] Python 3.10+ required. Download from https://python.org/downloads/
        echo [FAIL] During install, CHECK "Add Python to PATH"
        exit /b 1
    )
)

REM ---------------------------------------------------------------
REM Check / Install Visual Studio Build Tools (C++ compiler)
REM Required by: pynacl, sqlcipher3, argon2-cffi, cryptography
REM ---------------------------------------------------------------
echo.
echo [TALON] Checking C++ build tools...

set HAS_COMPILER=false

REM Check for cl.exe (MSVC compiler)
where cl >nul 2>&1 && set HAS_COMPILER=true

REM Also check common VS install paths
if "%HAS_COMPILER%"=="false" (
    if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" (
        for /f "tokens=*" %%p in ('"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -property installationPath 2^>nul') do (
            if exist "%%p\VC\Tools\MSVC" set HAS_COMPILER=true
        )
    )
)

REM Check for Build Tools specifically
if "%HAS_COMPILER%"=="false" (
    if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools" set HAS_COMPILER=true
    if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2019\BuildTools" set HAS_COMPILER=true
    if exist "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools" set HAS_COMPILER=true
)

if "%HAS_COMPILER%"=="true" (
    echo [  OK ] C++ build tools found
) else (
    echo [    ] C++ build tools not found
    if "%HAS_WINGET%"=="true" (
        echo [TALON] Installing Visual Studio Build Tools via winget...
        echo [TALON] This may take several minutes on first install...
        winget install -e --id Microsoft.VisualStudio.2022.BuildTools --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended" --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [WARN] Build Tools install may have failed.
            echo [WARN] If Python package compilation fails later, install manually:
            echo [WARN] https://visualstudio.microsoft.com/visual-cpp-build-tools/
            echo [WARN] Select "Desktop development with C++" workload
        ) else (
            echo [  OK ] Visual Studio Build Tools installed
            echo [WARN] You may need to restart this command prompt for compiler to be found
        )
    ) else (
        echo [WARN] C++ Build Tools required for compiling native extensions
        echo [WARN] Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/
        echo [WARN] Select "Desktop development with C++" workload
        echo.
        set /p CONTINUE="Continue anyway? (y/N): "
        if /i not "!CONTINUE!"=="y" exit /b 1
    )
)

REM ---------------------------------------------------------------
REM Check / Install Git (needed for kivy_garden)
REM ---------------------------------------------------------------
echo.
echo [TALON] Checking Git...

where git >nul 2>&1
if not errorlevel 1 (
    echo [  OK ] Git found
) else (
    echo [    ] Git not found
    if "%HAS_WINGET%"=="true" (
        echo [TALON] Installing Git via winget...
        winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
        if errorlevel 1 (
            echo [WARN] Git install failed — mapview may not install
        ) else (
            echo [  OK ] Git installed
        )
    ) else (
        echo [WARN] Git not found. Install from https://git-scm.com
    )
)

REM ---------------------------------------------------------------
REM Check / Download SQLCipher DLL
REM ---------------------------------------------------------------
echo.
echo [TALON] Checking SQLCipher...

set SQLCIPHER_OK=false

REM Check if sqlcipher3 can already import
python -c "import sqlcipher3" >nul 2>&1 && set SQLCIPHER_OK=true

if "%SQLCIPHER_OK%"=="true" (
    echo [  OK ] SQLCipher already available
) else (
    REM Check if DLL exists in project or system
    set DLL_FOUND=false
    if exist "%~dp0sqlcipher.dll" set DLL_FOUND=true
    if exist "%~dp0deps\sqlcipher.dll" set DLL_FOUND=true
    where sqlcipher.dll >nul 2>&1 && set DLL_FOUND=true

    if "!DLL_FOUND!"=="true" (
        echo [  OK ] SQLCipher DLL found
    ) else (
        echo [    ] SQLCipher DLL not found — downloading...

        REM Create deps directory
        if not exist "%~dp0deps" mkdir "%~dp0deps"

        REM Download prebuilt SQLCipher for Windows
        REM Using curl (available on Windows 10+)
        where curl >nul 2>&1
        if not errorlevel 1 (
            echo [TALON] Downloading SQLCipher from GitHub...
            curl -sL "https://github.com/nicehash/sqlcipher-windows/releases/download/v4.5.6/sqlcipher-x64.zip" -o "%~dp0deps\sqlcipher.zip"
            if errorlevel 1 (
                echo [WARN] Download failed. Install SQLCipher manually:
                echo [WARN] https://github.com/nicehash/sqlcipher-windows/releases
                echo [WARN] Place sqlcipher.dll in the deps\ folder
            ) else (
                echo [TALON] Extracting SQLCipher...
                REM Use PowerShell to extract (available on all modern Windows)
                powershell -Command "Expand-Archive -Path '%~dp0deps\sqlcipher.zip' -DestinationPath '%~dp0deps\sqlcipher' -Force" 2>nul
                if errorlevel 1 (
                    echo [WARN] Extraction failed — extract deps\sqlcipher.zip manually
                ) else (
                    REM Copy DLL to project root so Python can find it
                    if exist "%~dp0deps\sqlcipher\sqlcipher.dll" (
                        copy "%~dp0deps\sqlcipher\sqlcipher.dll" "%~dp0deps\" >nul
                        echo [  OK ] SQLCipher DLL downloaded to deps\
                    ) else (
                        REM Try to find it in subdirectories
                        for /r "%~dp0deps\sqlcipher" %%f in (sqlcipher.dll) do (
                            copy "%%f" "%~dp0deps\" >nul
                            echo [  OK ] SQLCipher DLL downloaded to deps\
                            goto :sqlcipher_done
                        )
                        echo [WARN] DLL not found in archive — check deps\sqlcipher\ manually
                    )
                )
                :sqlcipher_done
                del "%~dp0deps\sqlcipher.zip" 2>nul
            )
        ) else (
            echo [WARN] curl not found — cannot auto-download SQLCipher
            echo [WARN] Download manually from:
            echo [WARN]   https://github.com/nicehash/sqlcipher-windows/releases
            echo [WARN] Place sqlcipher.dll in the deps\ folder
        )
    )

    REM Add deps dir to PATH for this session so sqlcipher3 can find the DLL
    set "PATH=%~dp0deps;%PATH%"
)

REM ---------------------------------------------------------------
REM Create virtual environment
REM ---------------------------------------------------------------
echo.
echo [TALON] Setting up virtual environment...

if not exist .venv (
    echo [TALON] Creating virtual environment...
    python -m venv .venv
    echo [  OK ] Virtual environment created
) else (
    echo [TALON] Virtual environment already exists
)

call .venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip setuptools wheel -q
echo [  OK ] pip/setuptools/wheel upgraded

REM ---------------------------------------------------------------
REM Install Python packages
REM ---------------------------------------------------------------
echo.
echo [TALON] Installing T.A.L.O.N. Python packages...

REM Make sure deps\ DLLs are findable during compilation
set "PATH=%~dp0deps;%PATH%"

pip install -e . -q
if errorlevel 1 (
    echo [WARN] Some packages may have failed to install
    echo [WARN] If you see errors about sqlcipher3, ensure the DLL is in deps\
    echo [WARN] If you see errors about pynacl, ensure Build Tools are installed
) else (
    echo [  OK ] Core dependencies installed
)

echo [TALON] Installing map tile support...
pip install "mapview>=1.0.6" -q 2>nul
if errorlevel 1 (
    echo [WARN] mapview install failed — map tiles will be unavailable
) else (
    echo [  OK ] mapview installed
)

REM Check for --dev flag
set INSTALL_DEV=false
for %%a in (%*) do (
    if "%%a"=="--dev" set INSTALL_DEV=true
)

if "%INSTALL_DEV%"=="true" (
    echo [TALON] Installing development tools...
    pip install -e ".[dev]" -q
    echo [  OK ] Dev tools installed
)

REM ---------------------------------------------------------------
REM Verify installation
REM ---------------------------------------------------------------
echo.
echo [TALON] Verifying installation...
echo.

set ERRORS=0

python -c "import RNS" 2>nul
if errorlevel 1 (echo [WARN] MISSING: Reticulum ^(rns^) & set /a ERRORS+=1) else (echo [  OK ] Reticulum)

python -c "import LXMF" 2>nul
if errorlevel 1 (echo [WARN] MISSING: LXMF & set /a ERRORS+=1) else (echo [  OK ] LXMF)

python -c "import nacl" 2>nul
if errorlevel 1 (echo [WARN] MISSING: PyNaCl — reinstall Build Tools and retry & set /a ERRORS+=1) else (echo [  OK ] PyNaCl)

python -c "import argon2" 2>nul
if errorlevel 1 (echo [WARN] MISSING: argon2-cffi & set /a ERRORS+=1) else (echo [  OK ] argon2-cffi)

python -c "import yaml" 2>nul
if errorlevel 1 (echo [WARN] MISSING: PyYAML & set /a ERRORS+=1) else (echo [  OK ] PyYAML)

python -c "import serial" 2>nul
if errorlevel 1 (echo [WARN] MISSING: pyserial & set /a ERRORS+=1) else (echo [  OK ] pyserial)

python -c "import kivy" 2>nul
if errorlevel 1 (echo [WARN] MISSING: Kivy & set /a ERRORS+=1) else (echo [  OK ] Kivy)

python -c "import kivymd" 2>nul
if errorlevel 1 (echo [WARN] MISSING: KivyMD & set /a ERRORS+=1) else (echo [  OK ] KivyMD)

python -c "import sqlcipher3" 2>nul
if errorlevel 1 (echo [WARN] MISSING: SQLCipher3 — check deps\sqlcipher.dll & set /a ERRORS+=1) else (echo [  OK ] SQLCipher3)

python -c "import talon.server.app" 2>nul
if errorlevel 1 (echo [WARN] MISSING: talon.server & set /a ERRORS+=1) else (echo [  OK ] talon.server)

python -c "import talon.client.app" 2>nul
if errorlevel 1 (echo [WARN] MISSING: talon.client & set /a ERRORS+=1) else (echo [  OK ] talon.client)

python -c "import talon.net.link_manager" 2>nul
if errorlevel 1 (echo [WARN] MISSING: talon.net & set /a ERRORS+=1) else (echo [  OK ] talon.net)

REM ---------------------------------------------------------------
REM Run tests if dev tools installed
REM ---------------------------------------------------------------
if "%INSTALL_DEV%"=="true" (
    echo.
    echo [TALON] Running test suite...
    python -m pytest --tb=line -q
)

REM ---------------------------------------------------------------
REM Summary
REM ---------------------------------------------------------------
echo.
echo ============================================
if %ERRORS% EQU 0 (
    echo   T.A.L.O.N. installation complete!
) else (
    echo   T.A.L.O.N. installed with %ERRORS% warning^(s^)
)
echo ============================================
echo.
echo   Activate the environment:
echo     .venv\Scripts\activate.bat
echo.
echo   Start the server:
echo     python talon-server.py
echo.
echo   Start a client:
echo     python talon-client.py
echo.
echo   Run tests:
echo     python -m pytest
echo.

if %ERRORS% GTR 0 (
    echo   To fix warnings, try:
    echo     - Restart command prompt and run install.bat again
    echo     - Ensure Visual Studio Build Tools are installed
    echo     - Check that deps\sqlcipher.dll exists
    echo.
)

endlocal
