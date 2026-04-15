@echo off
REM 5sec_video Windows .exe 빌드 스크립트
REM 사용: build.bat (가상환경 활성화 상태 또는 .venv 자동 사용)

setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pyinstaller.exe" (
    set "PYI=.venv\Scripts\pyinstaller.exe"
) else (
    set "PYI=pyinstaller"
)

echo [build] cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [build] running PyInstaller...
%PYI% --clean --noconfirm 5sec_video.spec
if errorlevel 1 (
    echo [build] FAILED
    exit /b 1
)

echo.
echo [build] DONE: dist\5sec_video.exe
echo.
endlocal
