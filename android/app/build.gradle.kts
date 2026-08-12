import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release 簽章金鑰（todo010-1）：從一個不進 git 的 keystore.properties 讀，
// 格式見 README。故意不把 keystore/密碼放進版控——每個建置者（含你自己）
// 用自己的 keytool 產生一把即可，不影響原始碼本身可完整公開建置。
val keystorePropertiesFile = file("keystore.properties")
val hasKeystoreProperties = keystorePropertiesFile.exists()
val keystoreProperties = Properties().apply {
    if (hasKeystoreProperties) {
        load(FileInputStream(keystorePropertiesFile))
    }
}

android {
    namespace = "com.phonespeaker.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.phonespeaker.app"
        // M1-A 範圍：優先 SDK 內建元件（NsdManager/AudioTrack/Foreground Service），
        // minSdk 26 依 SPEC3.md §13。
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        // todo010-1：WiFi + U1 + U2 三種傳輸與雙語都已驗收完成，改用正式版號
        // （不再用開發階段代號），跟 PC 端 installer.iss 的版本對齊。
        // todo011：onTaskRemoved 生命週期 bug 修正（fix）＋ U1 主動偵測
        // 新功能（feat）合併成本次一版，MINOR bump（使用者確認合併一版）。
        versionName = "1.1.0"
    }

    signingConfigs {
        if (hasKeystoreProperties) {
            create("release") {
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            if (hasKeystoreProperties) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

// keystore.properties 不存在時，assembleRelease/bundleRelease 明確失敗並提示
// 怎麼補（而不是默默生出一個沒簽章、裝不上真機的 APK）。用
// taskGraph.whenReady（不是單一 task 的 doFirst）：整個 task graph 排好、
// 任何 task 真正開始執行之前就先擋下來，不會被 release 建置鏈上其他更早
// 執行的 task（例如 lint）蓋掉這個訊息。不影響 assembleDebug／一般
// sync／compileDebugKotlin（todo010 已驗證過的路徑）。
gradle.taskGraph.whenReady {
    if (!hasKeystoreProperties && allTasks.any { it.name == "assembleRelease" || it.name == "bundleRelease" }) {
        throw GradleException(
            "Missing android/keystore.properties — release builds must be signed. " +
                "See README for the keytool command to generate one."
        )
    }
}

dependencies {
    // M1 範圍刻意不引入第三方音訊庫（§13）；只用 AndroidX 基本元件。
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
