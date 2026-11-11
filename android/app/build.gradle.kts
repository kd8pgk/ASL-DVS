import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val appVersion = "0.10.38"

val releaseKeystore = System.getenv("NODETALKER_KEYSTORE")?.let { file(it) }?.takeIf { it.isFile }
val releaseStorePassword = System.getenv("NODETALKER_KEYSTORE_PASSWORD")
val releaseKeyAlias = System.getenv("NODETALKER_KEY_ALIAS")
val releaseKeyPassword = System.getenv("NODETALKER_KEY_PASSWORD")
val privateKey = releaseKeystore != null &&
    !releaseStorePassword.isNullOrEmpty() &&
    !releaseKeyAlias.isNullOrEmpty() &&
    !releaseKeyPassword.isNullOrEmpty()

android {
    namespace = "io.github.kd8pgk.nodetalker"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.kd8pgk.nodetalker"
        minSdk = 26
        targetSdk = 36
        versionName = appVersion
        versionCode = appVersion.split(".").map { it.toInt() }.let { it[0] * 1000000 + it[1] * 1000 + it[2] }
    }

    signingConfigs {
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
        if (privateKey) {
            create("release") {
                storeFile = releaseKeystore
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (privateKey) "release" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }

    lint {
        abortOnError = true
        checkReleaseBuilds = false
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
