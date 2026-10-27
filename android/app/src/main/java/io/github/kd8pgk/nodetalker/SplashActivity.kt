package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper

@SuppressLint("CustomSplashScreen")
class SplashActivity : Activity() {
    private val ui = Handler(Looper.getMainLooper())
    private val next = Runnable {
        startActivity(Intent(this, NodesActivity::class.java))
        finish()
        @Suppress("DEPRECATION")
        overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_splash)
        ui.postDelayed(next, SPLASH_MS)
    }

    override fun onDestroy() {
        ui.removeCallbacks(next)
        super.onDestroy()
    }

    companion object {
        private const val SPLASH_MS = 3000L
    }
}
