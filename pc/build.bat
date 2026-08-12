@echo off
REM build.bat -- PC packaging into a distributable portable zip (todo010-2;
REM PyInstaller onedir + adb + zip. todo010-1 originally paired this with an
REM Inno Setup installer -- installer\ is kept in the repo as a future
REM option, see installer\installer.iss, but this script's own end product
REM is now the portable zip: no installer, no admin/UAC, no release keys).
REM
REM Usage: double-click from pc\, or run `cd pc && build.bat` from a shell.
REM Output: pc\dist\PhoneSpeaker-PC-portable-vX.Y.Z.zip (unzip anywhere,
REM double-click PhoneSpeaker.exe inside -- no installation).
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

REM todo011: U2 前置狀態主動偵測（新功能，feat）MINOR bump（使用者確認合併一版）。
set VERSION=1.1.0
set ZIPNAME=PhoneSpeaker-PC-portable-v%VERSION%.zip

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

REM NOTE (todo010-4 incident): this used to be `rmdir /s /q dist build`, which
REM wiped the ENTIRE dist\ folder every run -- including previously delivered
REM zips from earlier versions (e.g. PhoneSpeaker-PC-portable-v1.0.0.zip),
REM with no Recycle Bin/git safety net since dist\ is gitignored. Never
REM delete old delivered files: only clean the PyInstaller intermediates
REM (build\) and the unzipped onedir tree (dist\PhoneSpeaker\) that this
REM script regenerates from scratch every time -- leave any *.zip already
REM sitting in dist\ (older versions) untouched.
echo Cleaning previous build (keeping previously delivered zips in dist\)...
rmdir /s /q build 2>nul
rmdir /s /q dist\PhoneSpeaker 2>nul

echo Building (onedir)...
REM --collect-all customtkinter: theme json / font assets (customtkinter's
REM own PyInstaller hook usually covers this; kept explicit as a safety net).
REM --collect-all pyaudiowpatch: bundles the underlying portaudio DLL (C extension).
.venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir ^
  --name PhoneSpeaker ^
  --collect-all customtkinter ^
  --collect-all pyaudiowpatch ^
  main.py

if not exist dist\PhoneSpeaker\PhoneSpeaker.exe (
    echo Build FAILED - see output above.
    pause
    exit /b 1
)

REM Bundle adb (Apache-2.0, redistribution allowed -- see
REM THIRD_PARTY_NOTICES.md) next to the exe, in the same adb\ subfolder
REM usb_adb.py's _find_adb_executable() looks for first (todo010-1). This
REM is the same resources\adb\ the Inno Setup installer uses; portable zip
REM users get the same "no separate adb install" benefit for U2.
REM
REM NOTE: using goto/labels here, not a parenthesized if/else block -- a
REM stray ")" inside an echoed line (e.g. "AdbWinUsbApi.dll)") closes a
REM parenthesized block early under cmd.exe's parser, which is a second,
REM different ASCII-only-adjacent batch-file gotcha found while testing
REM this script (see also the REM-encoding note near the top of this file).
if exist ..\installer\resources\adb\adb.exe goto :bundle_adb
echo WARNING: installer\resources\adb\adb.exe not found - portable zip will be built WITHOUT bundled adb.
echo   U2 will only work if the end user has adb on their own PATH.
echo   See todo010-1 for how to stage installer\resources\adb\ from your local Android SDK platform-tools.
goto :after_adb
:bundle_adb
echo Bundling adb into the portable package...
xcopy /y /i ..\installer\resources\adb\*.* dist\PhoneSpeaker\adb\ >nul
:after_adb

echo Zipping portable package...
REM -Force overwrites dist\%ZIPNAME% in place if it already exists (rebuilding
REM the same version) -- no separate `del` step, so this script never deletes
REM a *different* version's zip sitting in dist\.
powershell -NoProfile -Command "Compress-Archive -Path 'dist\PhoneSpeaker' -DestinationPath 'dist\%ZIPNAME%' -Force"

if not exist dist\%ZIPNAME% (
    echo Zipping FAILED - see output above.
    pause
    exit /b 1
)
echo Done! Portable zip is dist\%ZIPNAME%
pause
