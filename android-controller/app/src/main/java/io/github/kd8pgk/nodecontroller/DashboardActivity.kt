package io.github.kd8pgk.nodecontroller

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.TextView
import android.widget.Toast

class DashboardActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var errorPanel: View
    private lateinit var errorText: TextView
    private lateinit var node: Node
    private var renderGone = false

    companion object {
        const val EXTRA_NODE = "node"
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_dashboard)
        val found = NodeStore.get(this, intent.getStringExtra(EXTRA_NODE))
        if (found == null) {
            finish()
            return
        }
        node = found
        web = findViewById(R.id.web)
        errorPanel = findViewById(R.id.error_panel)
        errorText = findViewById(R.id.error_text)

        findViewById<Button>(R.id.nodes_button).setOnClickListener { finish() }
        findViewById<Button>(R.id.reload_button).setOnClickListener { reloadPage() }
        findViewById<Button>(R.id.forget_button).setOnClickListener {
            CookieManager.getInstance().removeAllCookies { load() }
            Toast.makeText(this, R.string.forget_done, Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.retry).setOnClickListener { reloadPage() }

        CookieManager.getInstance().setAcceptCookie(true)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = "$userAgentString NodeControllerApp/${BuildConfig.VERSION_NAME}"
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                val u = request.url
                if (node.address.isOrigin(u.scheme, u.host, u.port)) return false
                openExternal(u)
                return true
            }

            override fun onPageFinished(view: WebView, url: String?) {
                errorPanel.visibility = View.GONE
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, err: WebResourceError) {
                if (request.isForMainFrame) showError(err.description.toString())
            }

            override fun onRenderProcessGone(view: WebView, detail: android.webkit.RenderProcessGoneDetail): Boolean {
                renderGone = true
                showError(getString(R.string.page_stopped))
                return true
            }
        }
        load()
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
    }

    override fun onPause() {
        web.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        if (::web.isInitialized) {
            web.stopLoading()
            web.destroy()
        }
        super.onDestroy()
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    private fun load() {
        errorPanel.visibility = View.GONE
        web.loadUrl(node.address.origin + "/")
    }

    private fun reloadPage() {
        if (renderGone) {
            renderGone = false
            recreate()
        } else {
            load()
        }
    }

    private fun showError(text: String) {
        errorText.text = getString(R.string.load_failed, node.address.origin, text)
        errorPanel.visibility = View.VISIBLE
    }

    private fun openExternal(u: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, u))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, R.string.no_browser, Toast.LENGTH_LONG).show()
        }
    }
}
