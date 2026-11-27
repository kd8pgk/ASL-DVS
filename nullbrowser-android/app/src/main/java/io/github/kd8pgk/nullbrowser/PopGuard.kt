package io.github.kd8pgk.nullbrowser

import android.os.Handler
import android.os.Looper
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import java.io.ByteArrayInputStream
import java.security.SecureRandom

class PopGuard(private val web: WebView, private val say: (String) -> Unit, private val changed: () -> Unit) {
    class Entry(val id: Int, val kind: String, val from: String, val host: String, val action: String, var n: Int)

    class State(
        val picking: Boolean,
        val note: String,
        val found: List<PopItem>,
        val log: List<Entry>,
        val snapshot: BlockList.Snapshot,
        val hits: Map<String, Int>,
    )

    val list = BlockList()
    private val lock = Any()
    private val log = ArrayList<Entry>()
    private val hits = LinkedHashMap<String, Int>()
    private var seq = 0
    private var foundSeq = 0
    private var found: List<PopItem> = emptyList()
    private var note = ""
    private var picking = false
    private var token = ""
    private var pickUntil = 0L
    private val ui = Handler(Looper.getMainLooper())
    private var changePosted = false
    var onPicked: (() -> Unit)? = null

    private fun postChange() {
        synchronized(lock) {
            if (changePosted) return
            changePosted = true
        }
        ui.postDelayed({
            synchronized(lock) { changePosted = false }
            changed()
        }, 250)
    }

    fun topHost(): String = Sites.hostOfUrl(web.url)

    fun blockedBy(host: String?): String = list.hostBlocked(host)

    fun intercept(request: WebResourceRequest): WebResourceResponse? {
        if (request.isForMainFrame || list.size() == 0) return null
        val hit = list.hostBlocked(request.url.host)
        if (hit.isEmpty()) return null
        noteBlocked(hit)
        return WebResourceResponse("text/plain", "utf-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
    }

    fun noteBlocked(host: String) {
        synchronized(lock) {
            hits[host] = (hits[host] ?: 0) + 1
            if (hits.size > 300) hits.remove(hits.keys.first())
        }
        postChange()
    }

    fun logPop(kind: String, from: String, host: String, action: String) {
        synchronized(lock) {
            val last = log.firstOrNull()
            if (last != null && last.kind == kind && last.host == host && last.action == action && last.from == from) {
                last.n += 1
            } else {
                seq += 1
                log.add(0, Entry(seq, kind, from, host, action, 1))
                if (log.size > 200) log.removeAt(log.size - 1)
            }
        }
        postChange()
    }

    fun resetPage() {
        cancelPick()
        synchronized(lock) {
            found = emptyList()
            note = ""
        }
    }

    fun resetRun() {
        resetPage()
        synchronized(lock) {
            log.clear()
            hits.clear()
        }
    }

    fun state(): State = synchronized(lock) {
        State(picking, note, found, log.take(60).map { Entry(it.id, it.kind, it.from, it.host, it.action, it.n) }, list.snapshot(100), hits.entries.sortedByDescending { it.value }.take(15).associate { it.key to it.value })
    }

    fun clearLog() {
        synchronized(lock) {
            log.clear()
            hits.clear()
        }
        changed()
    }

    fun applyCss(view: WebView, url: String?) {
        val css = list.cssFor(Sites.hostOfUrl(url))
        if (css.isNotEmpty()) view.evaluateJavascript(PopScripts.applyJs(css), null)
    }

    private fun applyEverywhere() {
        applyCss(web, web.url)
    }

    fun find() {
        val top = topHost()
        if (top.isEmpty()) {
            synchronized(lock) { note = "Open a page first." }
            changed()
            return
        }
        synchronized(lock) { note = "Looking…" }
        changed()
        val url = web.url
        web.evaluateJavascript(PopScripts.FIND_JS) { json ->
            if (web.url != url) return@evaluateJavascript
            val items = PopItems.parseFound(json, top) { synchronized(lock) { foundSeq += 1; foundSeq } }
            synchronized(lock) {
                found = items
                note = if (items.isEmpty()) "Nothing that looks like a pop-up was found. Try Pick." else "Frames from other sites cannot be read from here; they are listed by their address."
            }
            changed()
        }
    }

    fun pick() {
        if (picking) {
            cancelPick()
            return
        }
        val top = topHost()
        if (top.isEmpty()) return
        val bytes = ByteArray(8)
        SecureRandom().nextBytes(bytes)
        token = bytes.joinToString("") { String.format("%02x", it) }
        picking = true
        pickUntil = System.currentTimeMillis() + 45000
        synchronized(lock) { note = "Tap the pop-up on the page." }
        web.evaluateJavascript(PopScripts.pickJs(token), null)
        changed()
        poll(top, web.url)
    }

    private fun poll(top: String, url: String?) {
        ui.postDelayed({
            if (!picking) return@postDelayed
            if (web.url != url || System.currentTimeMillis() > pickUntil) {
                cancelPick()
                return@postDelayed
            }
            val t = token
            web.evaluateJavascript(PopScripts.pollJs(t)) { json ->
                if (!picking || t != token) return@evaluateJavascript
                val s = MiniJson.unwrapString(json)
                if (s == null || s == "wait") {
                    poll(top, url)
                    return@evaluateJavascript
                }
                picking = false
                val id = synchronized(lock) { foundSeq += 1; foundSeq }
                val item = PopItems.parsePicked(json, top, id)
                synchronized(lock) {
                    if (item != null) {
                        found = listOf(item) + found.take(39)
                        note = ""
                    } else {
                        note = "Nothing was picked."
                    }
                }
                changed()
                onPicked?.invoke()
            }
        }, 350)
    }

    fun cancelPick() {
        if (!picking) return
        picking = false
        if (PopScripts.tokenOk(token)) web.evaluateJavascript(PopScripts.cancelJs(token), null)
        synchronized(lock) { note = "" }
        changed()
    }

    private fun findItem(id: Int): PopItem? = synchronized(lock) { found.firstOrNull { it.id == id } }

    fun show(id: Int) {
        val it = findItem(id) ?: return
        if (it.selector.isNotEmpty()) web.evaluateJavascript(PopScripts.outlineJs(it.selector), null)
    }

    fun hide(id: Int) {
        val it = findItem(id) ?: return
        if (it.selector.isEmpty() || it.frameHost.isEmpty()) return
        val r = list.addElement(it.frameHost, it.selector)
        if (!r.ok) {
            say("Not added: ${r.reason}.")
            return
        }
        say(if (r.added) "Hiding ${it.selector} on ${it.frameHost}." else "That element is already hidden.")
        applyEverywhere()
        changed()
    }

    private fun canBlock(host: String): String? {
        val c = BlockRules.cleanHost(host)
        if (c.isEmpty()) return "That is not a host name."
        val top = topHost()
        if (top.isNotEmpty() && Sites.siteOfHost(top) == Sites.siteOfHost(c)) return "That is the page's own site, so it was not blocked. Hide the element instead."
        return null
    }

    fun blockHost(host: String): Boolean {
        canBlock(host)?.let {
            say(it)
            return false
        }
        val r = list.addHost(host)
        if (!r.ok) {
            say("Not added: ${r.reason}.")
            return false
        }
        say(if (r.added) "Blocking ${r.host} from now on this run. Reload the page to see it gone." else "${r.host} is already on the list.")
        changed()
        return true
    }

    fun blockFound(id: Int, host: String) {
        val it = findItem(id) ?: return
        if (host == it.frameHost || it.hosts.contains(host)) blockHost(host)
    }

    fun blockLogged(id: Int) {
        val e = synchronized(lock) { log.firstOrNull { it.id == id } } ?: return
        if (e.host.isNotEmpty()) blockHost(e.host)
    }

    fun removeHost(host: String) {
        list.removeHost(host)
        changed()
    }

    fun removeElement(host: String, selector: String) {
        if (list.removeElement(host, selector)) applyEverywhere()
        changed()
    }

    fun importText(text: String) {
        val r = list.importText(text)
        applyEverywhere()
        say("Block list: ${r.hosts} host${if (r.hosts == 1) "" else "s"} and ${r.elements} element rule${if (r.elements == 1) "" else "s"} added${if (r.skipped > 0) ", ${r.skipped} line${if (r.skipped == 1) "" else "s"} skipped" else ""}${if (r.full) " (the list is full)" else ""}.")
        changed()
    }
}
