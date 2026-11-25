package io.github.kd8pgk.nullbrowser

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Message
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.inputmethod.EditorInfo
import android.webkit.CookieManager
import android.webkit.GeolocationPermissions
import android.webkit.MimeTypeMap
import android.webkit.PermissionRequest
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.TextView
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL

private val FILENAME_RE = Regex("filename=\"?([^\";]+)\"?")
private val SCHEME_RE = Regex("^[a-z][a-z0-9+.-]*:", RegexOption.IGNORE_CASE)
private val SPACE_RE = Regex("\\s")
private const val MAX_REDIRECTS = 5

class BrowserActivity : Activity() {
    private var clearingClip = false
    private val clipGuard = ClipboardManager.OnPrimaryClipChangedListener {
        if (!clearingClip) {
            clearingClip = true
            runCatching { getSystemService(ClipboardManager::class.java)?.let { NoClip.clear(it) } }
            clearingClip = false
        }
    }
    private lateinit var web: WebView
    private lateinit var addr: EditText
    private lateinit var notice: TextView
    private lateinit var askBar: View
    private lateinit var askText: TextView
    private lateinit var askOpen: Button
    private lateinit var askCancel: Button
    private lateinit var blank: View
    private lateinit var errorView: View
    private lateinit var errorTitle: TextView
    private lateinit var errorBody: TextView
    private lateinit var errorMain: Button
    private lateinit var errorRetry: Button

    private val upgradedHosts = mutableSetOf<String>()
    private val allowHttp = mutableSetOf<String>()
    private var editing = false
    private var pending: Pending? = null
    private var lastMainError: String? = null
    private var loadingHost: String? = null
    private var customView: View? = null
    private var customCallback: WebChromeClient.CustomViewCallback? = null
    private var backCallback: Any? = null
    private var rendererGone = false
    private lateinit var line: SlowLine
    private lateinit var lineBtn: Button
    private lateinit var lineRow: View
    private lateinit var lineStatus: View
    private lateinit var lineText: TextView
    private lateinit var lineMode: Button
    private lateinit var lineImages: Button
    private lateinit var lineSave: Button
    private lateinit var lineAhead: Button

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
        wipe()
        setContentView(R.layout.activity_browser)

        web = findViewById(R.id.web)
        addr = findViewById(R.id.addr)
        notice = findViewById(R.id.notice)
        askBar = findViewById(R.id.askBar)
        askText = findViewById(R.id.askText)
        askOpen = findViewById(R.id.askOpen)
        askCancel = findViewById(R.id.askCancel)
        blank = findViewById(R.id.blank)
        errorView = findViewById(R.id.errorView)
        errorTitle = findViewById(R.id.errorTitle)
        errorBody = findViewById(R.id.errorBody)
        errorMain = findViewById(R.id.errorMain)
        errorRetry = findViewById(R.id.errorRetry)
        lineBtn = findViewById(R.id.lineBtn)
        lineRow = findViewById(R.id.lineRow)
        lineStatus = findViewById(R.id.lineStatus)
        lineText = findViewById(R.id.lineText)
        lineMode = findViewById(R.id.lineMode)
        lineImages = findViewById(R.id.lineImages)
        lineSave = findViewById(R.id.lineSave)
        lineAhead = findViewById(R.id.lineAhead)

        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.databaseEnabled = false
        web.settings.allowFileAccess = false
        web.settings.allowContentAccess = false
        web.settings.setGeolocationEnabled(false)
        web.settings.mediaPlaybackRequiresUserGesture = true
        web.settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        web.settings.setSupportMultipleWindows(true)
        web.settings.javaScriptCanOpenWindowsAutomatically = false
        web.settings.userAgentString = LessInfo.userAgent(web.settings.userAgentString)
        line = SlowLine(web) { renderLine() }

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (!request.isForMainFrame) return false
                val url = request.url
                if (url.scheme != "http" && url.scheme != "https") return true
                val up = upgradeIfNeeded(url)
                if (up != null) {
                    view.loadUrl(up, extraHeaders())
                    return true
                }
                if (line.saveData && request.method == "GET" && !request.isRedirect) {
                    view.loadUrl(url.toString(), extraHeaders())
                    return true
                }
                return false
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? = line.intercept(request)

            override fun onPageCommitVisible(view: WebView, url: String) {
                line.pageVisible()
            }

            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                loadingHost = Uri.parse(url).host
                hideError()
                view.evaluateJavascript(NoClip.JS, null)
                view.evaluateJavascript(LessInfo.JS, null)
                line.pageStarted(url)
            }

            override fun onPageFinished(view: WebView, url: String) {
                view.evaluateJavascript(NoClip.JS, null)
                view.evaluateJavascript(LessInfo.JS, null)
                line.pageFinished()
                refreshUi()
            }

            override fun doUpdateVisitedHistory(view: WebView, url: String, isReload: Boolean) {
                refreshUi()
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (!request.isForMainFrame) return
                val url = request.url
                lastMainError = url.toString()
                val host = url.host ?: ""
                if (url.scheme == "https" && upgradedHosts.contains(host)) {
                    showNoHttps(host, url.buildUpon().scheme("http").build().toString())
                } else {
                    showLoadError(error.description?.toString() ?: "It did not load.")
                }
            }

            override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
                handler.cancel()
                val host = Uri.parse(error.url).host
                if (host != null && host == loadingHost) showCertError(host)
            }

            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                rendererGone = true
                recreate()
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
                        navigate(request.url.toString())
                        v.post { v.destroy() }
                        return true
                    }
                }
                val transport = resultMsg.obj as WebView.WebViewTransport
                transport.webView = temp
                resultMsg.sendToTarget()
                return true
            }

            override fun onShowCustomView(view: View, callback: CustomViewCallback) {
                if (customView != null) {
                    callback.onCustomViewHidden()
                    return
                }
                customView = view
                customCallback = callback
                (window.decorView as FrameLayout).addView(
                    view,
                    FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
                )
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    window.insetsController?.hide(WindowInsets.Type.systemBars())
                }
                syncBack()
            }

            override fun onHideCustomView() {
                exitFullscreen()
            }
        }

        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            val raw = safeName(guessFileName(url, contentDisposition))
            val kind = classify(mimeType, raw)
            if (kind == null) {
                showNotice(getString(R.string.downloads_off))
                return@setDownloadListener
            }
            if (pending != null) {
                showNotice("Answer the question about the other file first.")
                return@setDownloadListener
            }
            val mimeExt = MimeTypeMap.getSingleton().getExtensionFromMimeType(mimeType?.substringBefore(';')?.trim())
            val name = withExtension(raw, kind, mimeExt)
            val cookie = CookieManager.getInstance().getCookie(url)
            pending = Pending(kind, name, url, cookie, userAgent)
            askText.text = getString(R.string.ask_open_file, name, kindLabel(kind), appLabel(kind))
            askOpen.isEnabled = true
            askCancel.isEnabled = true
            askBar.visibility = View.VISIBLE
        }

        askOpen.setOnClickListener { answerPending(true) }
        askCancel.setOnClickListener { answerPending(false) }

        findViewById<ImageButton>(R.id.back).setOnClickListener { if (web.canGoBack()) web.goBack() }
        findViewById<ImageButton>(R.id.forward).setOnClickListener { if (web.canGoForward()) web.goForward() }
        findViewById<ImageButton>(R.id.reload).setOnClickListener { web.reload() }
        findViewById<ImageButton>(R.id.home).setOnClickListener { goBlank() }
        errorRetry.setOnClickListener { lastMainError?.let { navigate(it) } ?: web.reload() }
        lineBtn.setOnClickListener {
            lineRow.visibility = if (lineRow.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }
        findViewById<Button>(R.id.lineClose).setOnClickListener { lineRow.visibility = View.GONE }
        lineMode.setOnClickListener {
            line.setMode(when (line.mode) {
                SlowMode.AUTO -> SlowMode.ON
                SlowMode.ON -> SlowMode.OFF
                SlowMode.OFF -> SlowMode.AUTO
            })
        }
        lineImages.setOnClickListener { line.setImages(!line.images) }
        lineSave.setOnClickListener { line.setSaveData(!line.saveData) }
        lineAhead.setOnClickListener { line.setReadAhead(!line.readAhead) }
        findViewById<Button>(R.id.lineStop).setOnClickListener { line.stop() }
        renderLine()

        addr.setOnEditorActionListener { _, actionId, event ->
            if (actionId == EditorInfo.IME_ACTION_GO || (event != null && event.keyCode == KeyEvent.KEYCODE_ENTER && event.action == KeyEvent.ACTION_DOWN)) {
                editing = false
                addr.clearFocus()
                go(addr.text.toString())
                true
            } else {
                false
            }
        }
        addr.setOnFocusChangeListener { _, has -> editing = has }

        goBlank()
    }

    private fun upgradeIfNeeded(url: Uri): String? {
        val host = url.host ?: return null
        if (url.scheme != "http" || isPrivateHost(host) || allowHttp.contains(host)) return null
        upgradedHosts.add(host)
        return url.buildUpon().scheme("https").build().toString()
    }

    private fun navigate(target: String) {
        val uri = Uri.parse(target)
        hideError()
        blank.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl(upgradeIfNeeded(uri) ?: target, extraHeaders())
    }

    private fun extraHeaders(): Map<String, String> = if (line.saveData) mapOf("Save-Data" to "on") else emptyMap()

    private fun renderLine() {
        if (isDestroyed) return
        lineBtn.text = getString(if (line.active()) R.string.line_slow else R.string.line)
        lineMode.text = getString(when (line.mode) {
            SlowMode.AUTO -> R.string.slow_auto
            SlowMode.ON -> R.string.slow_on
            SlowMode.OFF -> R.string.slow_off
        })
        lineImages.text = getString(if (line.images) R.string.images_on else R.string.images_off)
        lineSave.text = getString(if (line.saveData) R.string.save_data_on else R.string.save_data_off)
        lineAhead.text = getString(if (line.readAhead) R.string.read_ahead_on else R.string.read_ahead_off)
        val text = line.status()
        lineText.text = text
        lineStatus.visibility = if (text.isEmpty()) View.GONE else View.VISIBLE
        findViewById<Button>(R.id.lineStop).visibility = if (line.busy()) View.VISIBLE else View.GONE
    }

    private fun exitFullscreen() {
        val v = customView ?: return
        (window.decorView as FrameLayout).removeView(v)
        customView = null
        customCallback?.onCustomViewHidden()
        customCallback = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.show(WindowInsets.Type.systemBars())
        }
        syncBack()
    }

    private fun handleBack(): Boolean {
        if (customView != null) {
            exitFullscreen()
            return true
        }
        if (web.canGoBack()) {
            web.goBack()
            return true
        }
        return false
    }

    private fun syncBack() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val want = customView != null || web.canGoBack()
        val current = backCallback as OnBackInvokedCallback?
        if (want && current == null) {
            val cb = OnBackInvokedCallback { handleBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, cb)
            backCallback = cb
        } else if (!want && current != null) {
            onBackInvokedDispatcher.unregisterOnBackInvokedCallback(current)
            backCallback = null
        }
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
        askCancel.isEnabled = false
        Thread {
            val file = fetchDownload(rec)
            val ok = file != null && contentMatches(rec.kind, readHead(file))
            if (file != null && !ok) file.delete()
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                pending = null
                askBar.visibility = View.GONE
                when {
                    file == null -> showNotice("${rec.name} could not be fetched.")
                    !ok -> showNotice(getString(R.string.not_really, rec.name, kindLabel(rec.kind)))
                    else -> openFile(file, rec.kind)
                }
            }
        }.start()
    }

    private fun readHead(file: File): ByteArray = file.inputStream().use { input ->
        val buf = ByteArray(64)
        var n = 0
        while (n < buf.size) {
            val r = input.read(buf, n, buf.size - n)
            if (r < 0) break
            n += r
        }
        buf.copyOf(n)
    }

    private fun fetchDownload(rec: Pending): File? {
        var url = URL(rec.url)
        var hops = 0
        val out = File(downloadsDir(cacheDir), "${System.currentTimeMillis()}-${rec.name}")
        var got = 0L
        var expected = -1L
        var validator = ""
        var tries = 0
        while (true) {
            val c = try {
                url.openConnection() as HttpURLConnection
            } catch (e: Exception) {
                out.delete()
                return null
            }
            try {
                c.instanceFollowRedirects = false
                c.setRequestProperty("User-Agent", rec.userAgent)
                if (hops == 0) rec.cookie?.let { c.setRequestProperty("Cookie", it) }
                if (line.saveData) c.setRequestProperty("Save-Data", "on")
                if (got > 0) {
                    c.setRequestProperty("Range", "bytes=$got-")
                    if (validator.isNotEmpty()) c.setRequestProperty("If-Range", validator)
                }
                c.connectTimeout = 15000
                c.readTimeout = 30000
                val code = c.responseCode
                if (code in 300..399) {
                    val loc = c.getHeaderField("Location") ?: return null.also { out.delete() }
                    val next = URL(url, loc)
                    if (next.protocol != "https" && next.protocol != "http") return null.also { out.delete() }
                    if (url.protocol == "https" && next.protocol == "http") return null.also { out.delete() }
                    hops += 1
                    if (hops > MAX_REDIRECTS) return null.also { out.delete() }
                    url = next
                    continue
                }
                val append: Boolean
                if (code == 206 && got > 0) {
                    val r = Slow.parseContentRange(c.getHeaderField("Content-Range"))
                    if (r == null || r.start != got) {
                        got = 0
                        validator = ""
                        throw java.io.IOException("range mismatch")
                    }
                    if (r.total > 0) expected = r.total
                    append = true
                } else if (code in 200..299) {
                    got = 0
                    expected = c.contentLengthLong
                    append = false
                } else if (code >= 500 || code == 408 || code == 429) {
                    throw java.io.IOException("server busy")
                } else {
                    out.delete()
                    return null
                }
                if (expected > MAX_BYTES) {
                    out.delete()
                    return null
                }
                validator = c.getHeaderField("ETag") ?: c.getHeaderField("Last-Modified") ?: validator
                c.inputStream.use { input ->
                    FileOutputStream(out, append).use { output ->
                        val buf = ByteArray(64 * 1024)
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            if (got + n > MAX_BYTES) {
                                out.delete()
                                return null
                            }
                            output.write(buf, 0, n)
                            got += n
                        }
                    }
                }
                if (expected > 0 && got < expected) throw java.io.IOException("short body")
                return out
            } catch (e: java.io.IOException) {
                tries += 1
                if (tries > Slow.RETRIES) {
                    out.delete()
                    return null
                }
                try {
                    Thread.sleep(Slow.backoffMs(tries))
                } catch (_: InterruptedException) {
                    out.delete()
                    return null
                }
            } catch (e: Exception) {
                out.delete()
                return null
            } finally {
                c.disconnect()
            }
        }
    }

    private fun openFile(file: File, kind: Kind) {
        val uri = Uri.parse("content://io.github.kd8pgk.nullbrowser.fileprovider/${Uri.encode(file.name)}")
        val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(file.extension.lowercase()) ?: when (kind) {
            Kind.PDF -> "application/pdf"
            Kind.AUDIO -> "audio/*"
            Kind.VIDEO -> "video/*"
        }
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
        contentDisposition?.let { FILENAME_RE.find(it) }?.groupValues?.get(1)?.let { return it }
        return Uri.parse(url).lastPathSegment ?: "file"
    }

    private fun go(text: String) {
        val t = text.trim()
        if (t.isEmpty()) {
            goBlank()
            return
        }
        if (SPACE_RE.containsMatchIn(t)) {
            showNotice("Type a web address, for example example.com. There is no search box.")
            return
        }
        val candidate = if (SCHEME_RE.containsMatchIn(t)) t else "https://$t"
        val uri = Uri.parse(candidate)
        if (uri.scheme != "http" && uri.scheme != "https") {
            showNotice("${uri.scheme} addresses are not opened here.")
            return
        }
        if (uri.host.isNullOrEmpty()) {
            showNotice("That is not a web address.")
            return
        }
        navigate(candidate)
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
        syncBack()
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
            navigate(plainUrl)
        }
        errorView.visibility = View.VISIBLE
        blank.visibility = View.GONE
    }

    private fun showCertError(host: String) {
        errorTitle.text = getString(R.string.cert_title)
        errorBody.text = getString(R.string.cert_body, host)
        errorMain.visibility = View.GONE
        errorView.visibility = View.VISIBLE
        blank.visibility = View.GONE
    }

    @SuppressLint("GestureBackNavigation")
    override fun onBackPressed() {
        if (!handleBack()) super.onBackPressed()
    }

    override fun onResume() {
        super.onResume()
        getSystemService(ClipboardManager::class.java)?.addPrimaryClipChangedListener(clipGuard)
    }

    override fun onPause() {
        getSystemService(ClipboardManager::class.java)?.removePrimaryClipChangedListener(clipGuard)
        super.onPause()
    }

    private fun wipe() {
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
        WebStorage.getInstance().deleteAllData()
        downloadsDir(cacheDir).deleteRecursively()
    }

    override fun onDestroy() {
        if (::line.isInitialized) line.shutdown()
        if (::web.isInitialized) {
            if (!rendererGone) {
                web.stopLoading()
                web.clearHistory()
                web.clearCache(true)
            }
            (web.parent as? ViewGroup)?.removeView(web)
            web.destroy()
        }
        wipe()
        super.onDestroy()
    }
}
