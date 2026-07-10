plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.chaquo.python")
}

val runtimeWebAssetsDir = layout.buildDirectory.dir("generated/runtimeWebAssets")
val syncRuntimeWebAssets by tasks.registering(Sync::class) {
    from(layout.projectDirectory.dir("../../static")) {
        include(
            "battle.html",
            "battle_login.html",
            "battle_accounts.html",
            "styles.css",
            "battle_layout.css",
            "battle_geometry_v7.css",
            "battle_app.js",
            "battle_lobby.js",
            "battle_lobby.html",
            "photon_scene.js",
            "photon_lobby.css",
            "vendor/three/**",
            "battle_accounts.js",
            "battle_table_model.js",
            "battle_table_renderer.js",
            "assets/q_dazed_drool_5s.gif",
            "assets/mahjong-tiles/**",
            "assets/battle_table/**",
        )
    }
    into(runtimeWebAssetsDir)
}

android {
    namespace = "cn.wenling.mahjong.host"
    compileSdk = 36

    defaultConfig {
        applicationId = "cn.wenling.mahjong.host"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    flavorDimensions += "device"
    productFlavors {
        create("phone") {
            dimension = "device"
            ndk {
                abiFilters += "arm64-v8a"
            }
        }
        create("emulator") {
            dimension = "device"
            ndk {
                abiFilters += "x86_64"
            }
        }
    }

    buildTypes {
        debug {}
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("main") {
            assets.srcDir(runtimeWebAssetsDir)
        }
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

tasks.named("preBuild") {
    dependsOn(syncRuntimeWebAssets)
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets {
        getByName("main") {
            srcDir("../../src")
            srcDir("../../packages/wenling_core")
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.05.01")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")
    implementation("com.google.zxing:core:3.5.3")

    debugImplementation("androidx.compose.ui:ui-tooling")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
