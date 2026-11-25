package io.github.kd8pgk.nullbrowser

import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

class Fetched(val bytes: ByteArray, val type: String)

class SlowLine(private val web: WebView, private val onChange: () -> Unit) {
    @Volatile
    var mode = SlowMode.AUTO
        private set
    @Volatile
    var images = true
        private set
    @Volatile
    var saveData = false
        private set
    @Volatile
    var readAhead = false
        private set

    val meter = Meter()
    private val ui = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val ahead = ConcurrentHashMap<String, Fetched>()
    @Volatile private var aheadBytes = 0L
    @Volatile private var gen = 0
    private var queue = ArrayList<Waiting>()
    private val known = HashSet<String>()
    private var seq = 0
    private var layout: Layout? = null
    private var busy: String? = null
    var done = 0
        private set
    var total = 0
        private set
    var retrying = false
        private set
    var stopped = false
        private set
    var aheadNote = ""
        private set
    private var pageUrl = ""
    private var startedAt = 0L
    private var finished = false
    private var aheadFor = ""
    private var scanning = false
    private var wasActive = false

    fun active(): Boolean = Slow.isActive(mode, meter.slow)

    fun busy(): Boolean = active() && (busy != null || queue.isNotEmpty())

    fun status(): String {
        val parts = ArrayList<String>()
        if (busy()) {
            parts.add("Slow line")
            if (retrying) parts.add("the line dropped, trying again")
            if (total > 0) parts.add("image ${minOf(done + 1, total)} of $total, in viewing order")
            if (meter.lastRate > 0) parts.add(Slow.rateLabel(meter.lastRate))
        }
        if (aheadNote.isNotEmpty()) parts.add(aheadNote)
        return parts.joinToString(" · ")
    }

    private fun applyBlock() {
        web.settings.blockNetworkImage = !images || (active() && !stopped && !drained())
    }

    private fun drained(): Boolean = finished && queue.isEmpty() && busy == null

    private fun changed() {
        val now = active()
        if (now != wasActive) {
            wasActive = now
            if (now) {
                web.evaluateJavascript(Slow.QUIET_JS, null)
                scan()
            }
        }
        applyBlock()
        onChange()
    }

    fun setMode(m: SlowMode) {
        mode = m
        changed()
    }

    fun setImages(on: Boolean) {
        images = on
        if (!on) stop() else stopped = false
        changed()
        if (on) scan()
    }

    fun setSaveData(on: Boolean) {
        saveData = on
        onChange()
    }

    fun setReadAhead(on: Boolean) {
        readAhead = on
        if (on) {
            aheadFor = ""
            maybeReadAhead()
        }
        onChange()
    }

    fun stop() {
        stopped = true
        done += queue.size
        queue.clear()
        gen += 1
        busy = null
        retrying = false
        applyBlock()
        onChange()
    }

    fun pageStarted(url: String) {
        gen += 1
        pageUrl = url
        startedAt = System.currentTimeMillis()
        finished = false
        queue.clear()
        known.clear()
        layout = null
        busy = null
        retrying = false
        stopped = false
        done = 0
        total = 0
        if (aheadFor != "" && Slow.siteOf(aheadFor) != Slow.siteOf(url)) clearAhead()
        applyBlock()
        if (active()) web.evaluateJavascript(Slow.QUIET_JS, null)
        onChange()
    }

    fun pageVisible() {
        if (startedAt > 0) {
            meter.firstByte(System.currentTimeMillis() - startedAt)
            startedAt = 0
            changed()
        }
        scan()
    }

    fun pageFinished() {
        finished = true
        if (active()) web.evaluateJavascript(Slow.QUIET_JS, null)
        scan()
        applyBlock()
        maybeReadAhead()
    }

    fun clearAhead() {
        ahead.clear()
        aheadBytes = 0
        aheadNote = ""
        aheadFor = ""
    }

    private fun scan() {
        if (scanning || !active() || !images || stopped) return
        scanning = true
        val g = gen
        web.evaluateJavascript(Slow.LAYOUT_JS) { json ->
            scanning = false
            if (g != gen) return@evaluateJavascript
            val l = Slow.parseLayout(json) ?: return@evaluateJavascript
            layout = l
            for (s in l.items) {
                if (known.add(s.src)) {
                    queue.add(Waiting(s.src, seq++))
                    total += 1
                }
            }
            pump()
            if (!drained() || !finished) ui.postDelayed({ if (g == gen) scan() }, 800)
            onChange()
        }
    }

    private fun pump() {
        if (busy != null || queue.isEmpty() || stopped || !images) {
            applyBlock()
            if (drained()) maybeReadAhead()
            return
        }
        val next = Slow.pickNext(queue, layout) ?: return
        queue.remove(next)
        busy = next.url
        val g = gen
        val referer = pageUrl
        val cookie = CookieManager.getInstance().getCookie(next.url)
        val ua = web.settings.userAgentString
        val save = saveData
        val cached = ahead[next.url]
        worker.execute {
            val got = cached ?: fetch(next.url, referer, cookie, ua, IMAGE_ACCEPT, Slow.MAX_IMAGE_BYTES, save) { g != gen }
            ui.post {
                if (g != gen) return@post
                busy = null
                retrying = false
                if (got != null && got.type.startsWith("image/")) {
                    done += 1
                    val data = "data:${got.type};base64," + Base64.encodeToString(got.bytes, Base64.NO_WRAP)
                    web.evaluateJavascript(Slow.placeJs(next.url, data), null)
                } else if (got != null || next.late) {
                    done += 1
                } else {
                    queue.add(next.copy(late = true))
                }
                onChange()
                pump()
            }
        }
        onChange()
    }

    private fun maybeReadAhead() {
        if (!readAhead || !images || stopped || !finished || busy != null || queue.isNotEmpty()) return
        if (pageUrl.isEmpty() || pageUrl == "about:blank" || aheadFor == pageUrl) return
        aheadFor = pageUrl
        val g = gen
        web.evaluateJavascript(Slow.LINKS_JS) { json ->
            if (g != gen) return@evaluateJavascript
            val next = Slow.pickNextLink(Slow.parseLinks(json), pageUrl)
            if (next.isEmpty()) return@evaluateJavascript
            aheadNote = "Reading ahead the next page…"
            onChange()
            val ua = web.settings.userAgentString
            val cookie = CookieManager.getInstance().getCookie(next)
            val save = saveData
            val referer = pageUrl
            worker.execute {
                val page = fetch(next, referer, cookie, ua, "text/html,application/xhtml+xml,*/*;q=0.8", 4L * 1024 * 1024, save) { !readAhead }
                val urls = if (page != null) Slow.imageUrlsIn(String(page.bytes, Charsets.UTF_8), next) else emptyList()
                for (u in urls) {
                    if (!readAhead || aheadBytes >= Slow.READ_AHEAD_BYTES) break
                    if (ahead.containsKey(u)) continue
                    val img = fetch(u, next, null, ua, IMAGE_ACCEPT, Slow.MAX_IMAGE_BYTES, save) { !readAhead } ?: continue
                    if (aheadBytes + img.bytes.size > Slow.READ_AHEAD_BYTES) break
                    ahead[u] = img
                    aheadBytes += img.bytes.size
                    ui.post {
                        aheadNote = "Reading ahead: ${ahead.size} image(s) of the next page ready"
                        onChange()
                    }
                }
                ui.post {
                    aheadNote = if (page == null) "" else "Next page ready (${ahead.size} image(s))"
                    onChange()
                }
            }
        }
    }

    fun intercept(request: WebResourceRequest): WebResourceResponse? {
        val url = request.url.toString()
        if (!request.isForMainFrame) {
            ahead[url]?.let { return WebResourceResponse(it.type.substringBefore(';'), null, ByteArrayInputStream(it.bytes)) }
            if (active() && (Slow.isFont(url) || Slow.isPrefetch(request.requestHeaders) || Slow.isPing(request.requestHeaders))) {
                return WebResourceResponse("text/plain", "utf-8", 204, "No Content", emptyMap(), ByteArrayInputStream(ByteArray(0)))
            }
        }
        return null
    }

    fun shutdown() {
        gen += 1
        worker.shutdownNow()
        ahead.clear()
    }

    private fun fetch(url: String, referer: String, cookie: String?, ua: String, accept: String, max: Long, save: Boolean, cancelled: () -> Boolean): Fetched? {
        val buf = ByteArrayOutputStream()
        var type = ""
        var validator = ""
        var expected = -1L
        var tries = 0
        while (!cancelled()) {
            val have = buf.size().toLong()
            val t0 = System.currentTimeMillis()
            var c: HttpURLConnection? = null
            var bytesNow = 0L
            try {
                val conn = URL(url).openConnection() as HttpURLConnection
                c = conn
                conn.connectTimeout = 20000
                conn.readTimeout = 30000
                conn.setRequestProperty("User-Agent", ua)
                conn.setRequestProperty("Accept", accept)
                if (referer.startsWith("http")) conn.setRequestProperty("Referer", referer)
                cookie?.let { conn.setRequestProperty("Cookie", it) }
                if (save) conn.setRequestProperty("Save-Data", "on")
                if (have > 0) {
                    conn.setRequestProperty("Range", "bytes=$have-")
                    if (validator.isNotEmpty()) conn.setRequestProperty("If-Range", validator)
                }
                val code = conn.responseCode
                meter.firstByte(System.currentTimeMillis() - t0)
                if (code == 206 && have > 0) {
                    val r = Slow.parseContentRange(conn.getHeaderField("Content-Range"))
                    if (r == null || r.start != have) {
                        buf.reset()
                        throw IOException("range mismatch")
                    }
                    if (r.total > 0) expected = r.total
                } else if (code in 200..299) {
                    buf.reset()
                    expected = conn.contentLengthLong
                } else if (code >= 500 || code == 408 || code == 429) {
                    throw IOException("server busy")
                } else {
                    return null
                }
                if (expected > max) return null
                type = conn.contentType ?: type
                validator = conn.getHeaderField("ETag") ?: conn.getHeaderField("Last-Modified") ?: validator
                conn.inputStream.use { input ->
                    val chunk = ByteArray(16 * 1024)
                    while (true) {
                        if (cancelled()) return null
                        val n = input.read(chunk)
                        if (n < 0) break
                        buf.write(chunk, 0, n)
                        bytesNow += n
                        if (buf.size() > max) return null
                    }
                }
                meter.transfer(bytesNow, System.currentTimeMillis() - t0)
                if (expected > 0 && buf.size() < expected) throw IOException("short body")
                return Fetched(buf.toByteArray(), type.ifEmpty { "application/octet-stream" })
            } catch (e: IOException) {
                tries += 1
                if (tries > Slow.RETRIES) return null
                ui.post {
                    retrying = true
                    onChange()
                }
                try {
                    Thread.sleep(Slow.backoffMs(tries))
                } catch (_: InterruptedException) {
                    return null
                }
            } catch (e: Exception) {
                return null
            } finally {
                c?.disconnect()
            }
        }
        return null
    }

    companion object {
        const val IMAGE_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
    }
}

