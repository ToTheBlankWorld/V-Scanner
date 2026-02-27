package com.vsecurity.scanner

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class VScannerApplication : Application() {
    
    override fun onCreate() {
        super.onCreate()
        // Initialize any global components here
    }
}
