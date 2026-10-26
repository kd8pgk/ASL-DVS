package io.github.kd8pgk.nodetalker

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.http.SslError
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.os.Build
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import java.io.IOException

class TalkerActivity : Activity() {
    private lateinit var node: Node
    private lateinit var web: WebView
    private lateinit var error: View
    private lateinit var tabs: TabBar
    private var listenTab: ListenTab? = null
    private lateinit var router: TabRouter
    private var renderGone = false
    private var micRequest: PermissionRequest? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var pendingDownload: String? = null
    private var certDialog: AlertDialog? = null
    private val pushState: () -> Unit = { runOnUiThread { sendState() } }
    private val pushTalk: (String) -> Unit = { ev -> runOnUiThread { sendTalk(ev) } }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val n = NodeStore.get(this, intent.getStringExtra(EXTRA_NODE))
        if (n == null) {
            finish()
            return
        }
        node = n
        title = node.title
        setContentView(R.layout.activity_talker)
        NodesActivity.fitInsets(findViewById(R.id.root))
        if (NodeStore.keepScreenOn(this)) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        web = findViewById(R.id.web)
        error = findViewById(R.id.error)
        router = TabRouter(object : TabRouter.Io {
            override fun clickPage(name: String) {
                web.evaluateJavascript(TabBar.clickJs(name), null)
            }

            override fun select(name: String) {
                tabs.select(name)
            }

            override fun showNative() {
                listenTab?.show()
            }

            override fun hideNative() {
                listenTab?.hide()
            }

            override fun nativeAllowed(): Boolean =
                Compat.useNative("listen", Compat.seen(node.id)) && NodeStore.audio(this@TalkerActivity).app
        })
        tabs = TabBar(findViewById(R.id.tabbar)) { name -> router.pick(name) }
        listenTab = ListenTab(this, findViewById(R.id.listen_view), object : ListenTab.Host {
            override val node: Node
                get() = this@TalkerActivity.node

            override fun readPage(js: String, done: (String?) -> Unit) {
                web.evaluateJavascript(js) { done(it) }
            }

            override fun openTalk(): Boolean = openTalkChannel()

            override fun startListen(): Boolean = startListening()
        })
        findViewById<Button>(R.id.retry).setOnClickListener { if (renderGone) reopen() else load() }
        findViewById<Button>(R.id.back).setOnClickListener { finish() }
        setup()
        if (savedInstanceState == null || web.restoreState(savedInstanceState) == null) load()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val n = NodeStore.get(this, intent.getStringExtra(EXTRA_NODE)) ?: return
        if (n.id == node.id) return
        setIntent(intent)
        node = n
        title = node.title
        listenTab?.reset()
        load()
    }

    override fun onResume() {
        super.onResume()
        listenTab?.resume()
        Listen.listeners.add(pushState)
        Talk.listeners.add(pushTalk)
        sendState()
    }

    override fun onPause() {
        listenTab?.pause()
        Listen.listeners.remove(pushState)
        Talk.listeners.remove(pushTalk)
        super.onPause()
    }

    private fun sendTalk(ev: String) {
        if (!::web.isInitialized || (Talk.nodeId != null && Talk.nodeId != node.id)) return
        web.evaluateJavascript("window.ntAppTalk && window.ntAppTalk($ev)", null)
    }

    private fun sendState() {
        if (!::web.isInitialized) return
        val st = if (Listen.nodeId == null || Listen.nodeId == node.id) Listen.json() else "{\"state\":\"off\"}"
        web.evaluateJavascript("window.ntAppEvent && window.ntAppEvent($st)", null)
    }

    inner class Bridge {
        @JavascriptInterface
        fun version(): String = BuildConfig.VERSION_NAME

        @JavascriptInterface
        fun audioMode(): String = NodeStore.audio(this@TalkerActivity).mode

        @JavascriptInterface
        fun listenStart(): Boolean = startListening()

        @JavascriptInterface
        fun listenStop() = Listen.stop(this@TalkerActivity)

        @JavascriptInterface
        fun listenState(): String =
            if (Listen.nodeId == null || Listen.nodeId == node.id) Listen.json() else "{\"state\":\"off\"}"

        @JavascriptInterface
        fun talkOpen(): Boolean = openTalkChannel()

        @JavascriptInterface
        fun talkKey(opts: String): Boolean {
            val o = try {
                org.json.JSONObject(opts)
            } catch (e: org.json.JSONException) {
                org.json.JSONObject()
            }
            val s = Talk.svc ?: return false
            return s.key(o.optDouble("guard", 0.0), o.optDouble("gain", 0.0))
        }

        @JavascriptInterface
        fun talkUnkey() {
            Talk.svc?.unkey()
        }

        @JavascriptInterface
        fun talkState(): String =
            if (Talk.nodeId == null || Talk.nodeId == node.id) Talk.json() else "{\"open\":false,\"talking\":false}"

        @JavascriptInterface
        fun tabChanged(name: String) {
            runOnUiThread { router.onPage(if (name in TabBar.NAMES) name else "") }
        }

        @JavascriptInterface
        fun rxMute(on: Boolean) {
            Listen.muted = on
        }

        @JavascriptInterface
        fun setVolume(v: Double) {
            Listen.volume = v.toFloat().coerceIn(0f, 1f)
        }
    }

    private fun startListening(): Boolean {
        val n = node
        askNotifications()
        return try {
            Listen.start(this, n)
            true
        } catch (e: IllegalStateException) {
            false
        } catch (e: SecurityException) {
            false
        }
    }

    private fun openTalkChannel(): Boolean {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            runOnUiThread {
                Toast.makeText(this, R.string.mic_needed, Toast.LENGTH_LONG).show()
                requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_TALK_MIC)
            }
            return false
        }
        askNotifications()
        return try {
            Talk.open(this, node)
            true
        } catch (e: IllegalStateException) {
            false
        } catch (e: SecurityException) {
            false
        }
    }

    private fun askNotifications() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        runOnUiThread { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFY) }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onDestroy() {
        listenTab?.hide()
        certDialog?.dismiss()
        if (isFinishing && ::node.isInitialized && Talk.nodeId == node.id) Talk.close(this)
        if (::web.isInitialized) {
            web.stopLoading()
            web.destroy()
        }
        super.onDestroy()
    }

    private fun load() {
        error.visibility = View.GONE
        router.reset()
        web.loadUrl(node.origin + "/")
    }

    private fun reopen() {
        val again = Intent(this, TalkerActivity::class.java).putExtra(EXTRA_NODE, node.id)
        finish()
        startActivity(again)
    }

    private fun handshake() {
        val n = node
        Thread {
            val v = try {
                NodeApi(n).health().optString("version")
            } catch (e: IOException) {
                return@Thread
            }
            Compat.remember(n.id, v)
            runOnUiThread { router.reevaluate() }
        }.start()
    }

    private fun showError(text: String) {
        router.reset()
        findViewById<TextView>(R.id.error_text).text = getString(R.string.load_failed, node.origin, text)
        error.visibility = View.VISIBLE
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setup() {
        CookieManager.getInstance().setAcceptCookie(true)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
            allowContentAccess = false
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = true
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = "$userAgentString NodeTalkerApp/${BuildConfig.VERSION_NAME}"
        }
        web.addJavascriptInterface(Bridge(), "NodeTalkerApp")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame || node.sameOrigin(request.url)) return false
                if (node.httpsUpgrade(request.url)) {
                    node = (NodeStore.get(this@TalkerActivity, node.id) ?: node).copy(https = true, pin = "")
                    NodeStore.put(this@TalkerActivity, node)
                    return false
                }
                openExternal(request.url)
                return true
            }

            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, err: SslError) {
                checkCert(handler, err)
            }

            override fun onPageFinished(view: WebView, url: String?) {
                view.evaluateJavascript(TabBar.HIDE_PAGE_NAV_JS, null)
                sendState()
                handshake()
            }

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                renderGone = true
                showError(getString(R.string.page_stopped))
                return true
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, err: WebResourceError) {
                if (request.isForMainFrame) showError(err.description.toString())
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                runOnUiThread { askMic(request) }
            }

            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                return try {
                    @Suppress("DEPRECATION")
                    startActivityForResult(params.createIntent(), REQ_FILE)
                    true
                } catch (e: ActivityNotFoundException) {
                    fileCallback = null
                    false
                }
            }
        }
        web.setDownloadListener { url, _, disposition, mime, _ ->
            val uri = Uri.parse(url)
            if (!node.sameOrigin(uri)) {
                openExternal(uri)
                return@setDownloadListener
            }
            pendingDownload = url
            val name = URLUtil.guessFileName(url, disposition, mime)
            val pick = Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(mime?.takeIf { it.isNotBlank() } ?: "application/octet-stream")
                .putExtra(Intent.EXTRA_TITLE, name)
            @Suppress("DEPRECATION")
            startActivityForResult(pick, REQ_SAVE)
        }
    }

    private fun checkCert(handler: SslErrorHandler, err: SslError) {
        if (!node.sameOrigin(Uri.parse(err.url))) {
            handler.cancel()
            return
        }
        val der = Certs.der(err.certificate)
        if (der == null) {
            handler.cancel()
            showError(getString(R.string.cert_unreadable))
            return
        }
        val fp = Certs.fingerprint(der)
        val current = NodeStore.get(this, node.id) ?: node
        if (current.pin == fp) {
            handler.proceed()
            return
        }
        val first = current.pin.isEmpty()
        certDialog?.dismiss()
        certDialog = AlertDialog.Builder(this)
            .setTitle(if (first) R.string.cert_first_title else R.string.cert_changed_title)
            .setMessage(getString(if (first) R.string.cert_first_body else R.string.cert_changed_body, node.title, Certs.pretty(fp)))
            .setCancelable(false)
            .setPositiveButton(if (first) R.string.trust else R.string.trust_new) { _, _ ->
                node = current.copy(pin = fp)
                NodeStore.put(this, node)
                handler.proceed()
            }
            .setNegativeButton(R.string.cancel) { _, _ ->
                handler.cancel()
                showError(getString(R.string.cert_refused))
            }
            .show()
    }

    private fun openExternal(uri: Uri) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(this, getString(R.string.no_browser, uri.toString()), Toast.LENGTH_LONG).show()
        }
    }

    private fun askMic(request: PermissionRequest) {
        val wantsMic = PermissionRequest.RESOURCE_AUDIO_CAPTURE in request.resources
        if (!wantsMic || !node.sameOrigin(request.origin)) {
            request.deny()
            return
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            request.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
            return
        }
        micRequest?.deny()
        micRequest = request
        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_MIC)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_TALK_MIC) {
            if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
                web.evaluateJavascript("window.ntAppTalk && window.ntAppTalk({ev:'retry'})", null)
                listenTab?.micGranted()
            }
            return
        }
        if (requestCode != REQ_MIC) return
        val r = micRequest ?: return
        micRequest = null
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            r.grant(arrayOf(PermissionRequest.RESOURCE_AUDIO_CAPTURE))
        } else {
            r.deny()
            Toast.makeText(this, R.string.mic_denied, Toast.LENGTH_LONG).show()
        }
    }

    @Deprecated("Activity result API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        when (requestCode) {
            REQ_FILE -> {
                fileCallback?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
                fileCallback = null
            }
            REQ_SAVE -> {
                val url = pendingDownload
                pendingDownload = null
                val dest = data?.data
                if (resultCode == RESULT_OK && url != null && dest != null) saveTo(url, dest)
            }
        }
    }

    private fun saveTo(url: String, dest: Uri) {
        val path = Uri.parse(url).let { (it.encodedPath ?: "/") + (it.encodedQuery?.let { q -> "?$q" } ?: "") }
        val cookie = CookieManager.getInstance().getCookie(node.origin)
        val n = node
        Thread {
            val msg = try {
                val c = NodeHttp.open(n, path, cookie)
                try {
                    if (c.responseCode != 200) throw IOException("HTTP ${c.responseCode}")
                    val out = contentResolver.openOutputStream(dest) ?: throw IOException("can't write there")
                    out.use { o -> c.inputStream.use { it.copyTo(o) } }
                } finally {
                    c.disconnect()
                }
                getString(R.string.saved_file, dest.lastPathSegment ?: "")
            } catch (e: IOException) {
                getString(R.string.save_failed, e.message ?: e.javaClass.simpleName)
            }
            runOnUiThread { Toast.makeText(this, msg, Toast.LENGTH_LONG).show() }
        }.start()
    }

    companion object {
        const val EXTRA_NODE = "node"
        private const val REQ_MIC = 1
        private const val REQ_FILE = 2
        private const val REQ_SAVE = 3
        private const val REQ_NOTIFY = 4
        private const val REQ_TALK_MIC = 5
    }
}
