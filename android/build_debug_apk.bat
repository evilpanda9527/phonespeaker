@echo off
REM build_debug_apk.bat -- Android packaging into a distributable debug APK
REM (todo010-2: simplest release path, no release keystore needed).
REM
REM Usage: double-click from android\, or run `cd android && build_debug_apk.bat`.
REM Output: android\dist\PhoneSpeaker-Android-debug-vX.Y.Z.apk (sideload this
REM onto a phone; Settings must allow "install from unknown sources").
REM
REM NOTE: keep this file ASCII-only -- see pc\build.bat for why (cmd.exe can
REM mis-tokenize non-ASCII text in REM comments and inside parenthesized
REM if/else blocks, producing confusing bogus errors even when the real
REM commands still run fine).
REM
REM This is the debug build, not release: build.gradle.kts's release
REM signingConfig (todo010-1) is kept in the repo as a future "proper
REM release" option, but is NOT used here -- no keystore.properties needed
REM for this script to work.

set VERSION=1.0.0
set APKNAME=PhoneSpeaker-Android-debug-v%VERSION%.apk

if not exist gradlew.bat (
    echo gradlew.bat not found. Run this from the android\ directory.
    pause
    exit /b 1
)

echo Building debug APK...
REM Explicit ".\" prefix, not a bare filename: some environments disable
REM cmd.exe's implicit "search current directory" behaviour
REM (NoDefaultCurrentDirectoryInPath), which makes a bare `gradlew.bat`
REM fail with a misleading "not recognized" error even though the file is
REM right here. A path with a directory separator always resolves.
call .\gradlew.bat assembleDebug
if errorlevel 1 (
    echo Build FAILED - see output above.
    pause
    exit /b 1
)

if not exist app\build\outputs\apk\debug\app-debug.apk (
    echo Build reported success but app-debug.apk was not found - see output above.
    pause
    exit /b 1
)

if not exist dist mkdir dist
copy /y app\build\outputs\apk\debug\app-debug.apk dist\%APKNAME% >nul

echo Done! Debug APK is dist\%APKNAME%
pause
