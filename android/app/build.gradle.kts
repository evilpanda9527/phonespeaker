plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
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
        versionCode = 1
        versionName = "0.1.0-m1a-wifi-poc"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
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
