package io.github.kd8pgk.nodetalker

import android.app.Application

class NodeTalkerApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Bluetooth.watch(this)
    }
}
