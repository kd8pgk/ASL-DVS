package io.github.kd8pgk.nodetalker

import android.app.Activity
import android.app.Application
import android.os.Bundle

class NodeTalkerApp : Application() {
    override fun onCreate() {
        super.onCreate()
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityStarted(activity: Activity) {
                ListenLog.started++
            }

            override fun onActivityStopped(activity: Activity) {
                if (ListenLog.started > 0) ListenLog.started--
            }

            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
            override fun onActivityResumed(activity: Activity) = Unit
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
        ListenLog.checkLastExit(this)
        Bluetooth.watch(this)
    }
}
