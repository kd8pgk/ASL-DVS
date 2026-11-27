package io.github.kd8pgk.nullbrowser

import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

class ViewGuard(private val web: WebView, private val changed: () -> Unit) {
    private sealed class Fetched {
        class Html(val text: String, val url: String) : Fetched()
        class Pass : Fetched()
        class Refused(val message: String) : Fetched()
    }

    @Volatile
    var tier = 4
        private set

    @Volatile
    var asking = true
        private set

    @Volatile
    var userAgent = ""

    @Volatile
    var imagesOn: () -> Boolean = { true }

    private val tokens = ConcurrentHashMap<String, String>()
    private val total = AtomicLong(0)
    private val random = SecureRandom()

    fun setTier(n: Int) {
        val next = ViewTier.normalize(n)
        val was = tier
        tier = next
        asking = false
        web.settings.javaScriptEnabled = ViewTier.scriptsOn(next)
        val url = web.url
        if (next != was && url != null && (url.startsWith("http://") || url.startsWith("https://"))) web.reload()
        changed()
    }

    private fun empty(status: Int): WebResourceResponse =
        WebResourceResponse("text/plain", "utf-8", status, "Not shown", emptyMap(), ByteArrayInputStream(ByteArray(0)))

    private fun page(html: String): WebResourceResponse =
        WebResourceResponse("text/html", "utf-8", 200, "OK", mapOf("Content-Security-Policy" to Gallery.CSP, "Cache-Control" to "no-store"), ByteArrayInputStream(html.toByteArray(Charsets.UTF_8)))

    private fun tokenFor(url: String): String {
        if (url.isEmpty() || tokens.size >= ViewTier.MAX_TOKENS) return ""
        val b = ByteArray(12)
        random.nextBytes(b)
        val token = b.joinToString("") { String.format("%02x", it) }
        tokens[token] = url
        return "https://" + Gallery.PIC_HOST + "/" + token
    }

    fun interceptMain(request: WebResourceRequest): WebResourceResponse? {
        val t = tier
        if (!request.isForMainFrame || !ViewTier.gallery(t)) return null
        if (!request.method.equals("GET", ignoreCase = true)) return null
        val url = request.url.toString()
        if (!url.startsWith("http://") && !url.startsWith("https://")) return null
        return when (val got = fetchPage(url, request.requestHeaders)) {
            is Fetched.Pass -> null
            is Fetched.Refused -> page(Gallery.errorPage(got.message))
            is Fetched.Html -> {
                val scan = HtmlScan.scan(got.text, ViewTier.wantText(t))
                val clean = HtmlScan.clean(scan, got.url, t)
                tokens.clear()
                total.set(0)
                page(Gallery.build(clean.title, clean.items) { tokenFor(it) })
            }
        }
    }

    fun interceptPicture(request: WebResourceRequest): WebResourceResponse? {
        if (request.url.host != Gallery.PIC_HOST) return null
        val token = request.url.lastPathSegment ?: return empty(404)
        val target = tokens[token] ?: return empty(404)
        if (!imagesOn()) return empty(204)
        if (total.get() >= ViewTier.MAX_TOTAL_BYTES) return empty(413)
        val bytes = fetchPicture(target) ?: return empty(502)
        total.addAndGet(bytes.size.toLong())
        val mime = ViewTier.imageMime(bytes)
        if (mime.isEmpty()) return empty(415)
        return WebResourceResponse(mime, null, 200, "OK", mapOf("Cache-Control" to "no-store"), ByteArrayInputStream(bytes))
    }

    private fun next(url: URL, location: String?, hops: Int): URL? {
        if (location == null || hops > 5) return null
        val n = try {
            URL(url, location)
        } catch (_: Exception) {
            return null
        }
        if (n.protocol != "https" && n.protocol != "http") return null
        if (url.protocol == "https" && n.protocol == "http") return null
        return n
    }

    private fun read(input: InputStream, max: Long): ByteArray? {
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(32 * 1024)
        var n: Int
        var sum = 0L
        while (true) {
            n = input.read(buf)
            if (n < 0) break
            sum += n
            if (sum > max) return null
            out.write(buf, 0, n)
        }
        return out.toByteArray()
    }

    private fun fetchPage(start: String, headers: Map<String, String>): Fetched {
        var url = try {
            URL(start)
        } catch (_: Exception) {
            return Fetched.Refused("That address could not be opened.")
        }
        var hops = 0
        while (true) {
            val c = try {
                url.openConnection() as HttpURLConnection
            } catch (_: Exception) {
                return Fetched.Refused("That address could not be opened.")
            }
            try {
                c.instanceFollowRedirects = false
                c.connectTimeout = 15000
                c.readTimeout = 30000
                c.setRequestProperty("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5")
                (headers["User-Agent"] ?: userAgent).takeIf { it.isNotEmpty() }?.let { c.setRequestProperty("User-Agent", it) }
                headers["Accept-Language"]?.let { c.setRequestProperty("Accept-Language", it) }
                CookieManager.getInstance().getCookie(url.toString())?.let { c.setRequestProperty("Cookie", it) }
                val code = c.responseCode
                c.headerFields?.get("Set-Cookie")?.forEach { CookieManager.getInstance().setCookie(url.toString(), it) }
                if (code in 300..399) {
                    val n = next(url, c.getHeaderField("Location"), ++hops) ?: return Fetched.Refused("The site sent a redirect that is not followed.")
                    url = n
                    continue
                }
                val type = c.contentType
                if (ViewTier.passThrough(type)) return Fetched.Pass()
                if (!ViewTier.isHtml(type)) return Fetched.Refused("This kind of file is not shown in the picture view.")
                val stream = if (code in 200..299) c.inputStream else c.errorStream
                val body = stream?.use { read(it, ViewTier.MAX_HTML_BYTES.toLong()) } ?: return Fetched.Refused("The page was empty or too big for the picture view.")
                val charset = Regex("charset=([\\w-]+)", RegexOption.IGNORE_CASE).find(type ?: "")?.groupValues?.get(1)
                val text = try {
                    String(body, if (charset != null) java.nio.charset.Charset.forName(charset) else Charsets.UTF_8)
                } catch (_: Exception) {
                    String(body, Charsets.UTF_8)
                }
                return Fetched.Html(text, url.toString())
            } catch (_: Exception) {
                return Fetched.Refused("This page could not be fetched for the picture view.")
            } finally {
                c.disconnect()
            }
        }
    }

    private fun fetchPicture(start: String): ByteArray? {
        var url = try {
            URL(start)
        } catch (_: Exception) {
            return null
        }
        var hops = 0
        while (true) {
            val c = try {
                url.openConnection() as HttpURLConnection
            } catch (_: Exception) {
                return null
            }
            try {
                c.instanceFollowRedirects = false
                c.connectTimeout = 15000
                c.readTimeout = 30000
                c.setRequestProperty("Accept", "image/avif,image/webp,image/png,image/jpeg,image/gif,image/*;q=0.8")
                if (userAgent.isNotEmpty()) c.setRequestProperty("User-Agent", userAgent)
                val code = c.responseCode
                if (code in 300..399) {
                    url = next(url, c.getHeaderField("Location"), ++hops) ?: return null
                    continue
                }
                if (code !in 200..299) return null
                if (c.contentLengthLong > ViewTier.MAX_PIC_BYTES) return null
                return c.inputStream.use { read(it, ViewTier.MAX_PIC_BYTES) }
            } catch (_: Exception) {
                return null
            } finally {
                c.disconnect()
            }
        }
    }
}
