package io.github.kd8pgk.nullbrowser

import java.net.URI

enum class SlowMode { AUTO, ON, OFF }

data class Spot(val src: String, val top: Double, val x: Double, val w: Double, val h: Double)

data class Layout(val vh: Double, val vw: Double, val items: List<Spot>)

data class Waiting(val url: String, val seq: Int, val late: Boolean = false)

data class Range(val start: Long, val end: Long, val total: Long)

data class Link(val rel: String, val href: String, val text: String)

class Meter {
    private val rates = ArrayDeque<Double>()
    private val waits = ArrayDeque<Long>()
    var slow = false
        private set
    var lastRate = 0.0
        private set

    @Synchronized
    fun transfer(bytes: Long, ms: Long) {
        if (bytes < Slow.MIN_SAMPLE_BYTES || ms <= 0) return
        lastRate = bytes * 1000.0 / ms
        rates.addLast(lastRate)
        if (rates.size > Slow.SAMPLES) rates.removeFirst()
        decide()
    }

    @Synchronized
    fun firstByte(ms: Long) {
        if (ms < 0) return
        waits.addLast(ms)
        if (waits.size > Slow.SAMPLES) waits.removeFirst()
        decide()
    }

    private fun decide() {
        val r = if (rates.size >= Slow.SAMPLES) rates.sorted()[rates.size / 2] else 0.0
        val w = waits.lastOrNull() ?: 0L
        if (!slow && ((r > 0 && r < Slow.SLOW_BPS) || w > Slow.SLOW_TTFB_MS)) slow = true
        else if (slow && r >= Slow.FAST_BPS && w <= Slow.SLOW_TTFB_MS) slow = false
    }
}

object Slow {
    const val SLOW_BPS = 16.0 * 1024
    const val FAST_BPS = 48.0 * 1024
    const val SLOW_TTFB_MS = 3000L
    const val MIN_SAMPLE_BYTES = 8L * 1024
    const val SAMPLES = 3
    const val SMALL_PX = 100.0 * 100.0
    const val MAX_IMAGE_BYTES = 8L * 1024 * 1024
    const val RETRIES = 5
    const val READ_AHEAD_BYTES = 48L * 1024 * 1024

    fun isActive(mode: SlowMode, meterSlow: Boolean): Boolean = when (mode) {
        SlowMode.ON -> true
        SlowMode.OFF -> false
        SlowMode.AUTO -> meterSlow
    }

    private data class Main(val left: Double, val width: Double)

    private fun mainColumn(layout: Layout?): Main? {
        val best = layout?.items?.filter { it.w > 0 && it.h > 0 }?.maxByOrNull { it.w * it.h } ?: return null
        return Main(best.x, best.w)
    }

    fun place(entry: Waiting, layout: Layout?): Pair<Int, Double> = place(entry, layout, mainColumn(layout))

    private fun place(entry: Waiting, layout: Layout?, main: Main?): Pair<Int, Double> {
        if (entry.late) return 5 to entry.seq.toDouble()
        if (layout == null || layout.vh <= 0) return 3 to entry.seq.toDouble()
        val hit = layout.items.firstOrNull { it.src == entry.url } ?: return 3 to entry.seq.toDouble()
        val small = hit.w > 0 && hit.h > 0 && hit.w * hit.h < SMALL_PX
        val center = hit.x + hit.w / 2
        val side = hit.w > 0 && if (main != null) {
            (center < main.left || center > main.left + main.width) && hit.w < main.width * 0.6
        } else {
            layout.vw > 0 && hit.w < layout.vw * 0.3 && (center < layout.vw * 0.25 || center > layout.vw * 0.75)
        }
        if (small || side) return 4 to entry.seq.toDouble()
        val bottom = hit.top + maxOf(hit.h, 1.0)
        if (hit.top < layout.vh && bottom > 0) return 0 to hit.top
        if (hit.top >= layout.vh) return 1 to hit.top
        return 2 to -hit.top
    }

    fun pickNext(entries: List<Waiting>, layout: Layout?): Waiting? {
        val main = mainColumn(layout)
        return entries.minWithOrNull(compareBy<Waiting>({ place(it, layout, main).first }, { place(it, layout, main).second }, { it.seq }))
    }

    fun parseContentRange(value: String?): Range? {
        val m = Regex("^bytes\\s+(\\d+)-(\\d+)/(\\d+|\\*)$", RegexOption.IGNORE_CASE).find(value?.trim() ?: return null) ?: return null
        val total = m.groupValues[3].let { if (it == "*") 0L else it.toLong() }
        return Range(m.groupValues[1].toLong(), m.groupValues[2].toLong(), total)
    }

    fun backoffMs(attempt: Int): Long = minOf(32000L, 2000L shl maxOf(0, attempt - 1).coerceAtMost(4))

    private val NEXT_TEXT = Regex("^\\s*(next(\\s+(page|comic|chapter|strip|episode))?|›|»|>|>>|→)\\s*[›»>→]?\\s*$", RegexOption.IGNORE_CASE)
    private val REL_NEXT = Regex("(^|\\s)next(\\s|$)", RegexOption.IGNORE_CASE)

    fun pickNextLink(links: List<Link>, pageUrl: String): String {
        val base = try { URI(pageUrl) } catch (_: Exception) { return "" }
        fun ok(href: String): String {
            return try {
                val u = base.resolve(href.trim())
                if (u.scheme != base.scheme || u.authority != base.authority) return ""
                val clean = u.toString().substringBefore('#')
                if (clean == pageUrl.substringBefore('#')) "" else u.toString()
            } catch (_: Exception) {
                ""
            }
        }
        for (l in links) if (REL_NEXT.containsMatchIn(l.rel)) ok(l.href).let { if (it.isNotEmpty()) return it }
        for (l in links) if (NEXT_TEXT.matches(l.text)) ok(l.href).let { if (it.isNotEmpty()) return it }
        return ""
    }

    private val IMG_SRC = Regex("<img\\b[^>]*?\\ssrc\\s*=\\s*(\"([^\"]*)\"|'([^']*)'|([^\\s>]+))", RegexOption.IGNORE_CASE)

    fun imageUrlsIn(html: String, pageUrl: String): List<String> {
        val base = try { URI(pageUrl) } catch (_: Exception) { return emptyList() }
        val out = LinkedHashSet<String>()
        for (m in IMG_SRC.findAll(html)) {
            if (out.size >= 200) break
            val raw = (m.groupValues[2].ifEmpty { m.groupValues[3] }.ifEmpty { m.groupValues[4] }).replace("&amp;", "&")
            try {
                val u = base.resolve(raw.trim())
                if (u.scheme == "https" || u.scheme == "http") out.add(u.toString())
            } catch (_: Exception) {
            }
        }
        return out.toList()
    }

    fun rateLabel(bytesPerSecond: Double): String =
        if (bytesPerSecond >= 1024 * 1024) String.format(java.util.Locale.US, "%.1f MB/s", bytesPerSecond / (1024 * 1024))
        else String.format(java.util.Locale.US, "%.1f KB/s", bytesPerSecond / 1024)

    fun siteOf(url: String): String {
        val host = try { URI(url).host?.lowercase() ?: return "" } catch (_: Exception) { return "" }
        val parts = host.split('.')
        return if (parts.size <= 2) host else parts.takeLast(2).joinToString(".")
    }

    fun isFont(url: String): Boolean = Regex("\\.(woff2?|ttf|otf|eot)(\\?|#|$)", RegexOption.IGNORE_CASE).containsMatchIn(url)

    fun isPrefetch(headers: Map<String, String>): Boolean =
        headers.entries.any { (k, v) -> k.lowercase() in setOf("sec-purpose", "purpose", "x-purpose", "x-moz") && Regex("prefetch|prerender|preview", RegexOption.IGNORE_CASE).containsMatchIn(v) }

    fun isPing(headers: Map<String, String>): Boolean = headers.keys.any { it.lowercase() == "ping-to" || it.lowercase() == "ping-from" }

    private fun unwrap(json: String?): String? {
        if (json == null || json == "null") return null
        return org.json.JSONTokener(json).nextValue() as? String
    }

    fun parseLayout(json: String?): Layout? {
        return try {
            val o = org.json.JSONObject(unwrap(json) ?: return null)
            val arr = o.optJSONArray("items")
            val items = ArrayList<Spot>()
            if (arr != null) for (i in 0 until minOf(arr.length(), 500)) {
                val it = arr.optJSONObject(i) ?: continue
                val src = it.optString("src", "")
                if (src.isEmpty() || src.length > 4096) continue
                items.add(Spot(src, it.optDouble("top", 0.0), it.optDouble("x", 0.0), it.optDouble("w", 0.0), it.optDouble("h", 0.0)))
            }
            Layout(o.optDouble("vh", 0.0), o.optDouble("vw", 0.0), items)
        } catch (_: Exception) {
            null
        }
    }

    fun parseLinks(json: String?): List<Link> {
        return try {
            val arr = org.json.JSONArray(unwrap(json) ?: return emptyList())
            (0 until minOf(arr.length(), 300)).mapNotNull { i ->
                val o = arr.optJSONObject(i) ?: return@mapNotNull null
                Link(o.optString("rel", "").take(100), o.optString("href", "").take(4096), o.optString("text", "").take(40))
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    const val LAYOUT_JS = """(function(){var o={vh:innerHeight,vw:innerWidth,items:[]};var im=document.images;for(var i=0;i<im.length&&o.items.length<500;i++){var e=im[i];var s=e.getAttribute('data-nb-src')||e.currentSrc||e.src;if(!s||s.indexOf('data:')===0)continue;var r=e.getBoundingClientRect();o.items.push({src:String(s),top:Math.round(r.top),x:Math.round(r.left),w:Math.round(r.width),h:Math.round(r.height)})}return JSON.stringify(o)})()"""

    const val LINKS_JS = """(function(){var a=[];var n=document.querySelectorAll('a[href], link[rel][href]');for(var i=0;i<n.length&&a.length<300;i++){var e=n[i];a.push({rel:String(e.getAttribute('rel')||''),href:String(e.href||''),text:String(e.textContent||e.getAttribute('aria-label')||e.getAttribute('title')||'').trim().slice(0,40)})}return JSON.stringify(a)})()"""

    const val QUIET_JS = """(function(){try{var q=function(e){if(!e||(e.tagName!=='VIDEO'&&e.tagName!=='AUDIO')||e.dataset.nbQuiet)return;e.dataset.nbQuiet='1';e.preload='none';e.autoplay=false;e.removeAttribute('autoplay')};document.querySelectorAll('video,audio').forEach(q);if(!window.__nbQuiet){window.__nbQuiet=new MutationObserver(function(r){r.forEach(function(x){x.addedNodes.forEach(function(n){if(n.nodeType===1){q(n);if(n.querySelectorAll)n.querySelectorAll('video,audio').forEach(q)}})})});window.__nbQuiet.observe(document,{childList:true,subtree:true})}}catch(e){}})();"""

    fun placeJs(url: String, dataUrl: String): String {
        val u = org.json.JSONObject.quote(url)
        val d = org.json.JSONObject.quote(dataUrl)
        return "(function(){var u=$u,d=$d,n=0;var im=document.images;for(var i=0;i<im.length;i++){var e=im[i];var s=e.getAttribute('data-nb-src')||e.currentSrc||e.src;if(s===u){e.setAttribute('data-nb-src',u);e.removeAttribute('srcset');e.onerror=function(){this.onerror=null;this.src=u};e.src=d;n++}}return n})()"
    }
}
