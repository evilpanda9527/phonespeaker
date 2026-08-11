@echo off
REM build.bat -- PC packaging into a distributable exe (todo010-1, PyInstaller onedir).
REM
REM Usage: double-click from pc\, or run `cd pc && build.bat` from a shell.
REM Output: pc\dist\PhoneSpeaker\PhoneSpeaker.exe (plus its _internal\ deps),
REM which installer\installer.iss later packs whole into the Inno Setup installer.
REM
REM NOTE: keep this file ASCII-only. cmd.exe's codepage handling can mis-tokenize
REM non-ASCII (e.g. Traditional Chinese) text inside REM comments, producing
REM bogus "not recognized as an internal or external command" errors even
REM though the actual build commands still run fine -- confusing for anyone
REM double-clicking this. See todo010-1 build log for a reproduction.
REM
REM onedir (not onefile): faster startup (no self-extraction each run) and
REM less likely to trip Windows SmartScreen / antivirus heuristics, which
REM commonly flag onefile's self-extracting bootloader.

if not exist .venv\Scripts\python.exe (
    echo .venv not found. Please create it first per README:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Installing dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller

echo Cleaning previous build...
rmdir /s /q dist build 2>nul

echo Building (onedir)...
REM --collect-all customtkinter: theme json / font assets (customtkinter's
REM own PyInstaller hook usually covers this; kept explicit as a safety net).
REM --collect-all pyaudiowpatch: bundles the underlying portaudio DLL (C extension).
.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir ^
  --name PhoneSpeaker ^
  --collect-all customtkinter ^
  --collect-all pyaudiowpatch ^
  main.py

if exist dist\PhoneSpeaker\PhoneSpeaker.exe (
    echo Done! Output is in dist\PhoneSpeaker\
) else (
    echo Build FAILED - see output above.
)
pause
