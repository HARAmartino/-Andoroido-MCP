plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.android.mcp.agent"
    compileSdk = 35

    defaultConfig {
        minSdk = 26  // Android 8+ required for foreground service notification channel
        targetSdk = 35
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // OkHttp for network interception (includes WebSocket support)
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // Kotlin coroutines for async operations on the Foreground Service
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Lifecycle / ViewModel (provided by the host app; compileOnly avoids bundling)
    compileOnly("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    compileOnly("androidx.lifecycle:lifecycle-livedata-ktx:2.8.7")
}
