package io.github.kd8pgk.nullbrowser

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Message
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.PermissionRequest
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.TextView
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

class BrowserActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var addr: EditText
    private lateinit var notice: TextView
    private lateinit var askBar: View
    private lateinit var askText: TextView
    private lateinit var askOpen: Button
    private lateinit var blank: View
    private lateinit var errorView: View
    private lateinit var errorTitle: TextView
    private lateinit var errorBody: TextView
    private lateinit var errorMain: Button
    private lateinit var errorRetry: Button

    private val upgraded = mutableSetOf<String>()
    private val allowHttp = mutableSetOf<String>()
    private var editing = false
    private var pending: Pending? = null
    private var lastMainError: String? = null

    private class Pending(
        val kind: Kind,
        val name: String,
        val url: String,
        val cookie: String?,
        val userAgent: String,
    )

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_browser)

        web = findViewById(R.id.web)
        addr = findViewById(R.id.addr)
        notice = findViewById(R.id.notice)
        askBar = findViewById(R.id.askBar)
        askText = findViewById(R.id.askText)
        askOpen = findViewById(R.id.askOpen)
        blank = findViewById(R.id.blank)
        errorView = findViewById(R.id.errorView)
        errorTitle = findViewById(R.id.errorTitle)
        errorBody = findViewById(R.id.errorBody)
        errorMain = findViewById(R.id.errorMain)
        errorRetry = findViewById(R.id.errorRetry)

        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.databaseEnabled = false
        web.settings.allowFileAccess = false
        web.settings.allowContentAccess = false
        web.settings.setGeolocationEnabled(false)
        web.settings.mediaPlaybackRequiresUserGesture = true
        web.settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
        web.settings.setSupportMultipleWindows(true)
        web.settings.javaScriptCanOpenWindowsAutomatically = false

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                val url = request.url
                if (url.scheme == "http" && !isPrivateHost(url.host) && !allowHttp.contains(url.host)) {
                    val httpsUrl = url.buildUpon().scheme("https").build().toString()
                    upgraded.add(httpsUrl)
                    view.loadUrl(httpsUrl)
                    return true
                }
                if (url.scheme != "http" && url.scheme != "https") return true
                return false
            }

            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                hideError()
            }

            override fun onPageFinished(view: WebView, url: String) {
                refreshUi()
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (!request.isForMainFrame) return
                val url = request.url.toString()
                lastMainError = url
                if (upgraded.contains(url)) {
                    val plain = url.replaceFirst("https:", "http:")
                    showNoHttps(request.url.host ?: "", plain)
                } else {
                    showLoadError(error.description?.toString() ?: "It did not load.")
                }
            }

            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: android.net.http.SslError) {
                handler.cancel()
                showCertError(error.url)
            }

            override fun onRenderProcessGone(view: WebView, detail: android.webkit.RenderProcessGoneDetail): Boolean {
                showLoadError("The page stopped working.")
                return true
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onGeolocationPermissionsShowPrompt(origin: String, callback: GeolocationPermissions.Callback) {
                callback.invoke(origin, false, false)
            }

            override fun onPermissionRequest(request: PermissionRequest) {
                request.deny()
            }

            override fun onCreateWindow(view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message): Boolean {
                if (!isUserGesture) {
                    showNotice(getString(R.string.popups_off))
                    return false
                }
                val temp = WebView(this@BrowserActivity)
                temp.webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
                        web.loadUrl(request.url.toString())
                        return true
                    }
                }
                val transport = resultMsg.obj as WebView.WebViewTransport
                transport.webView = temp
                resultMsg.sendToTarget()
                return true
            }
        }

        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            val name = safeName(guessFileName(url, contentDisposition))
            val kind = classify(mimeType, name)
            if (kind == null) {
                showNotice(getString(R.string.downloads_off))
                return@setDownloadListener
            }
            if (pending != null) {
                showNotice("Answer the question about the other file first.")
                return@setDownloadListener
            }
            val cookie = CookieManager.getInstance().getCookie(url)
            val rec = Pending(kind, name, url, cookie, userAgent)
            pending = rec
            askText.text = getString(R.string.ask_open_file, name, kindLabel(kind), appLabel(kind))
            askOpen.isEnabled = true
            findViewById<Button>(R.id.askCancel).isEnabled = true
            askBar.visibility = View.VISIBLE
        }

        askOpen.setOnClickListener { answerPending(true) }
        findViewById<Button>(R.id.askCancel).setOnClickListener { answerPending(false) }

        findViewById<ImageButton>(R.id.back).setOnClickListener { if (web.canGoBack()) web.goBack() }
        findViewById<ImageButton>(R.id.forward).setOnClickListener { if (web.canGoForward()) web.goForward() }
        findViewById<ImageButton>(R.id.reload).setOnClickListener { web.reload() }
        findViewById<ImageButton>(R.id.home).setOnClickListener { goBlank() }
        errorRetry.setOnClickListener { lastMainError?.let { web.loadUrl(it) } ?: web.reload() }

        addr.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_GO || (event != null && event.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)) {
                editing = false
                go(addr.text.toString())
                true
            } else {
                false
            }
        }
        addr.setOnFocusChangeListener { _, has -> editing = has }

        goBlank()
    }

    private fun answerPending(open: Boolean) {
        val rec = pending ?: return
        if (!open) {
            askBar.visibility = View.GONE
            pending = null
            return
        }
        askText.text = getString(R.string.ask_open_file, rec.name, kindLabel(rec.kind), appLabel(rec.kind)) + " Loading…"
        askOpen.isEnabled = false
        findViewById<Button>(R.id.askCancel).isEnabled = false
        Thread {
            val file = fetchDownload(rec)
            runOnUiThread {
                pending = null
                askBar.visibility = View.GONE
                if (file == null) {
                    showNotice("${rec.name} could not be fetched.")
                    return@runOnUiThread
                }
                val head = file.inputStream().use { input ->
                    val buf = ByteArray(64)
                    val n = input.read(buf)
                    if (n <= 0) ByteArray(0) else buf.copyOf(n)
                }
                if (!contentMatches(rec.kind, head)) {
                    file.delete()
                    showNotice(getString(R.string.not_really, rec.name, kindLabel(rec.kind)))
                    return@runOnUiThread
                }
                openFile(file)
            }
        }.start()
    }

    private fun fetchDownload(rec: Pending): File? {
        var conn: HttpURLConnection? = null
        return try {
            val c = URL(rec.url).openConnection() as HttpURLConnection
            conn = c
            c.setRequestProperty("User-Agent", rec.userAgent)
            rec.cookie?.let { c.setRequestProperty("Cookie", it) }
            c.connectTimeout = 15000
            c.readTimeout = 15000
            c.connect()
            if (c.responseCode !in 200..299) return null
            val dir = downloadsDir(cacheDir)
            val out = File(dir, "${System.currentTimeMillis()}-${rec.name}")
            var total = 0L
            var tooBig = false
            c.inputStream.use { input ->
                FileOutputStream(out).use { output ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        total += n
                        if (total > MAX_BYTES) {
                            tooBig = true
                            break
                        }
                        output.write(buf, 0, n)
                    }
                }
            }
            if (tooBig) {
                out.delete()
                null
            } else {
                out
            }
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    private fun openFile(file: File) {
        val uri = Uri.parse("content://io.github.kd8pgk.nullbrowser.fileprovider/${Uri.encode(file.name)}")
        val mime = android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(file.extension.lowercase())
        val intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(uri, mime)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        try {
            startActivity(intent)
        } catch (e: android.content.ActivityNotFoundException) {
            showNotice(getString(R.string.no_app, file.name))
        }
    }

    private fun guessFileName(url: String, contentDisposition: String?): String {
        val m = contentDisposition?.let { Regex("filename=\"?([^\";]+)\"?").find(it) }
        m?.groupValues?.get(1)?.let { return it }
        return Uri.parse(url).lastPathSegment ?: "file"
    }

    private fun go(text: String) {
        val t = text.trim()
        if (t.isEmpty()) {
            goBlank()
            return
        }
        if (t.contains(Regex("\\s"))) {
            showNotice("Type a web address, for example example.com. There is no search box.")
            return
        }
        var candidate = t
        if (!Regex("^[a-z][a-z0-9+.-]*:", RegexOption.IGNORE_CASE).containsMatchIn(t)) {
            candidate = "https://$t"
        }
        val uri = try {
            Uri.parse(candidate)
        } catch (e: Exception) {
            showNotice("That is not a web address.")
            return
        }
        if (uri.scheme != "http" && uri.scheme != "https") {
            showNotice("${uri.scheme} addresses are not opened here.")
            return
        }
        hideError()
        blank.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl(candidate)
    }

    private fun goBlank() {
        hideError()
        web.loadUrl("about:blank")
        web.visibility = View.GONE
        blank.visibility = View.VISIBLE
        addr.setText("")
    }

    private fun refreshUi() {
        if (!editing) addr.setText(if (web.url == "about:blank") "" else web.url)
    }

    private fun hideError() {
        errorView.visibility = View.GONE
    }

    private fun showNotice(text: String) {
        notice.text = text
        notice.visibility = View.VISIBLE
        notice.postDelayed({ if (notice.text == text) notice.visibility = View.GONE }, 6000)
    }

    private fun showLoadError(message: String) {
        errorTitle.text = getString(R.string.load_failed_title)
        errorBody.text = message
        errorMain.visibility = View.GONE
        errorView.visibility = View.VISIBLE
        blank.visibility = View.GONE
    }

    private fun showNoHttps(host: String, plainUrl: String) {
        errorTitle.text = getString(R.string.no_https_title)
        errorBody.text = getString(R.string.no_https_body, host)
        errorMain.text = getString(R.string.open_anyway)
        errorMain.visibility = View.VISIBLE
        errorMain.setOnClickListener {
            allowHttp.add(host)
            web.loadUrl(plainUrl)
        }
        errorView.visibility = View.VISIBLE
        blank.visibility = View.GONE
    }

    private fun showCertError(url: String) {
        val host = Uri.parse(url).host ?: ""
        errorTitle.text = getString(R.string.cert_title)
        errorBody.text = getString(R.string.cert_body, host)
        errorMain.visibility = View.GONE
        errorView.visibility = View.VISIBLE
        blank.visibility = View.GONE
    }

    @SuppressLint("GestureBackNavigation")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        CookieManager.getInstance().removeAllCookies(null)
        web.clearHistory()
        web.clearCache(true)
        WebStorage.getInstance().deleteAllData()
        downloadsDir(cacheDir).deleteRecursively()
        super.onDestroy()
    }
}
