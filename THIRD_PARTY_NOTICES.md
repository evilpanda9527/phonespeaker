# Third-Party Notices

PhoneSpeaker itself is licensed under the [MIT License](LICENSE). This file
lists the third-party software it bundles or depends on, and their licenses.

## Bundled with the PC portable release

**Android SDK Platform-Tools (`adb.exe`, `AdbWinApi.dll`, `AdbWinUsbApi.dll`)**
— copied into the PC portable zip's `adb\` folder at build time so U2 (USB
adb) works without a separate Platform-Tools install.
License: **Apache License 2.0**. Full upstream NOTICE text:
[`installer/resources/adb/NOTICE.txt`](installer/resources/adb/NOTICE.txt).

## PC (Python, `pc/requirements.txt`)

| Package | Version | License |
|---|---|---|
| [PyAudioWPatch](https://pypi.org/project/PyAudioWPatch/) | 0.2.12.8 | MIT |
| [pycaw](https://pypi.org/project/pycaw/) | 20251023 | MIT |
| [comtypes](https://pypi.org/project/comtypes/) | 1.4.16 | MIT |
| [customtkinter](https://pypi.org/project/customtkinter/) | 6.0.0 | MIT |
| [zeroconf](https://pypi.org/project/zeroconf/) | 0.150.0 | LGPL-2.1 |
| [darkdetect](https://pypi.org/project/darkdetect/) | 0.8.0 | BSD-3-Clause |
| [ifaddr](https://pypi.org/project/ifaddr/) | 0.2.0 | MIT |
| [packaging](https://pypi.org/project/packaging/) | 26.3 | Apache-2.0 OR BSD-2-Clause |
| [psutil](https://pypi.org/project/psutil/) | (transitive, via pycaw) | BSD-3-Clause |

`zeroconf` is LGPL-2.1 and used unmodified as an ordinary PyPI dependency
(imported at runtime, not statically bundled into a single binary); its
source is available from the link above. All other packages are permissively
licensed (MIT/BSD/Apache-2.0), no additional obligations beyond preserving
their own license/copyright notices.

## Android (Gradle, `android/app/build.gradle.kts`)

| Dependency | Version | License |
|---|---|---|
| androidx.core:core-ktx | 1.13.1 | Apache-2.0 |
| androidx.appcompat:appcompat | 1.7.0 | Apache-2.0 |
| com.google.android.material:material | 1.12.0 | Apache-2.0 |
| androidx.constraintlayout:constraintlayout | 2.1.4 | Apache-2.0 |
| androidx.lifecycle:lifecycle-service | 2.8.4 | Apache-2.0 |

All AndroidX / Material Components libraries above, and the Kotlin standard
library / Gradle plugin used to build the app, are licensed under the
**Apache License 2.0** (Google / JetBrains).

---

This list reflects the direct dependencies declared in `pc/requirements.txt`
and `android/app/build.gradle.kts` at the time of writing. If you add or
upgrade a dependency, please keep this file in sync.
