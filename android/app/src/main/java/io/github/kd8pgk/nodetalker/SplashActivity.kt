package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.TextView
import android.widget.Toast

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
        val call = NodeStore.callsign(this)
        val name = getString(R.string.app_name_nb)
        findViewById<TextView>(R.id.welcome).text =
            if (call.isEmpty()) getString(R.string.welcome_plain, name) else getString(R.string.welcome_call, call, name)
        findViewById<TextView>(R.id.license).apply {
            paintFlags = paintFlags or android.graphics.Paint.UNDERLINE_TEXT_FLAG
            setOnClickListener { openLicense() }
        }
        ui.postDelayed(next, SPLASH_MS)
    }

    private fun openLicense() {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(getString(R.string.license_url))))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, getString(R.string.license_url), Toast.LENGTH_LONG).show()
        }
    }

    override fun onDestroy() {
        ui.removeCallbacks(next)
        super.onDestroy()
    }

    companion object {
        private const val SPLASH_MS = 3000L
    }
}
