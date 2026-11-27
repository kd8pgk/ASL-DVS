package io.github.kd8pgk.nullbrowser

object BlockRules {
    const val MAX_RULES = 20000
    const val MAX_FILE_BYTES = 5 * 1024 * 1024
    const val MAX_LINES = 100000
    const val MAX_SELECTOR = 500
    const val MAX_CSS = 200 * 1024

    private val HOST_RE = Regex("^(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\\.)+[a-z][a-z0-9-]{1,23}$")
    private val IPV4_RE = Regex("^\\d{1,3}(?:\\.\\d{1,3}){3}$")
    private val BAD_SELECTOR_CHARS = Regex("[{};@\\\\\\n\\r,<]")
    private val BAD_SELECTOR_WORDS = Regex("url\\s*\\(|expression\\s*\\(|/\\*", RegexOption.IGNORE_CASE)
    private val WHOLE_PAGE = Regex("^(html|body|head|\\*|:root)$", RegexOption.IGNORE_CASE)

    fun cleanHost(value: String?): String {
        var h = (value ?: "").trim().lowercase()
        h = h.replace(Regex("^\\|\\|"), "").replace(Regex("^\\*\\."), "").replace(Regex("^\\."), "")
        h = h.replace(Regex("\\$.*$"), "").replace(Regex("\\^.*$"), "").replace(Regex("/.*$"), "").replace(Regex(":\\d+$"), "").replace(Regex("\\.$"), "")
        if (h.isEmpty() || h.length > 253 || h == "localhost") return ""
        if (IPV4_RE.matches(h)) return if (h.split('.').all { it.toInt() <= 255 }) h else ""
        return if (HOST_RE.matches(h)) h else ""
    }

    fun validSelector(sel: String?): String {
        val s = (sel ?: "").trim()
        if (s.isEmpty() || s.length > MAX_SELECTOR) return ""
        if (BAD_SELECTOR_CHARS.containsMatchIn(s) || BAD_SELECTOR_WORDS.containsMatchIn(s)) return ""
        if (s.count { it == '"' } % 2 != 0 || s.count { it == '\'' } % 2 != 0) return ""
        if (s.count { it == '(' } != s.count { it == ')' }) return ""
        if (s.count { it == '[' } != s.count { it == ']' }) return ""
        if (WHOLE_PAGE.matches(s)) return ""
        return s
    }

    fun labels(host: String): List<String> {
        val out = ArrayList<String>()
        var h = host
        while (h.isNotEmpty()) {
            out.add(h)
            val i = h.indexOf('.')
            if (i < 0) break
            h = h.substring(i + 1)
        }
        return out
    }
}

class BlockList {
    data class AddResult(val ok: Boolean, val added: Boolean = false, val reason: String = "", val host: String = "", val selector: String = "")
    data class ImportResult(var hosts: Int = 0, var elements: Int = 0, var skipped: Int = 0, var full: Boolean = false)
    data class Snapshot(val hostCount: Int, val elementCount: Int, val hosts: List<String>, val elements: List<Pair<String, String>>)

    private val hosts = HashSet<String>()
    private val elements = LinkedHashMap<String, LinkedHashSet<String>>()
    private val cssCache = HashMap<String, String>()
    private var elementCount = 0

    @Synchronized
    fun size(): Int = hosts.size + elementCount

    @Synchronized
    fun hasElements(): Boolean = elementCount > 0

    @Synchronized
    fun hostBlocked(host: String?): String {
        val h = (host ?: "").lowercase()
        if (h.isEmpty() || hosts.isEmpty()) return ""
        for (l in BlockRules.labels(h)) if (l.contains('.') && hosts.contains(l)) return l
        return ""
    }

    @Synchronized
    fun addHost(value: String?): AddResult {
        val h = BlockRules.cleanHost(value)
        if (h.isEmpty()) return AddResult(false, reason = "not a host name")
        if (hosts.contains(h)) return AddResult(true, false, host = h)
        if (size() >= BlockRules.MAX_RULES) return AddResult(false, reason = "the list is full")
        hosts.add(h)
        return AddResult(true, true, host = h)
    }

    @Synchronized
    fun addElement(host: String?, selector: String?): AddResult {
        val h = BlockRules.cleanHost(host)
        val sel = BlockRules.validSelector(selector)
        if (h.isEmpty()) return AddResult(false, reason = "not a host name")
        if (sel.isEmpty()) return AddResult(false, reason = "that selector is not allowed")
        var set = elements[h]
        if (set != null && set.contains(sel)) return AddResult(true, false, host = h, selector = sel)
        if (size() >= BlockRules.MAX_RULES) return AddResult(false, reason = "the list is full")
        if (set == null) {
            set = LinkedHashSet()
            elements[h] = set
        }
        set.add(sel)
        elementCount += 1
        cssCache.clear()
        return AddResult(true, true, host = h, selector = sel)
    }

    @Synchronized
    fun removeHost(value: String?): Boolean = hosts.remove(value ?: "")

    @Synchronized
    fun removeElement(host: String?, selector: String?): Boolean {
        val set = elements[host ?: ""] ?: return false
        if (!set.remove(selector ?: "")) return false
        if (set.isEmpty()) elements.remove(host ?: "")
        elementCount -= 1
        cssCache.clear()
        return true
    }

    @Synchronized
    fun cssFor(host: String?): String {
        val h = (host ?: "").lowercase()
        if (h.isEmpty() || elementCount == 0) return ""
        cssCache[h]?.let { return it }
        val picked = ArrayList<String>()
        for (l in BlockRules.labels(h)) elements[l]?.forEach { picked.add("$it{display:none!important}") }
        var css = picked.joinToString("\n")
        if (css.length > BlockRules.MAX_CSS) css = css.substring(0, maxOf(0, css.lastIndexOf('\n', BlockRules.MAX_CSS)))
        cssCache[h] = css
        return css
    }

    private class Line(val kind: String, val host: String = "", val selector: String = "")

    private fun parseLine(raw: String): Line? {
        val line = raw.trim()
        if (line.isEmpty() || line.startsWith("!") || line.startsWith("[") || (line.startsWith("#") && !line.contains("##"))) return null
        val hide = line.indexOf("##")
        if (hide > 0) return Line("element", line.substring(0, hide), line.substring(hide + 2))
        if (hide == 0 || line.contains("#@#") || line.contains("#?#") || line.startsWith("@@")) return Line("skip")
        val parts = line.split(Regex("\\s+"))
        if (parts.size >= 2 && Regex("^(0\\.0\\.0\\.0|127\\.0\\.0\\.1|::1?)$").matches(parts[0])) return Line("host", parts[1])
        if (parts.size == 1) return Line("host", parts[0])
        return Line("skip")
    }

    fun importText(text: String?): ImportResult {
        val out = ImportResult()
        val lines = (text ?: "").split(Regex("\r?\n"))
        for (i in 0 until minOf(lines.size, BlockRules.MAX_LINES)) {
            val p = parseLine(lines[i]) ?: continue
            if (p.kind == "skip") {
                out.skipped += 1
                continue
            }
            val r = if (p.kind == "host") addHost(p.host) else addElement(p.host, p.selector)
            if (!r.ok) {
                if (r.reason == "the list is full") out.full = true
                out.skipped += 1
            } else if (r.added) {
                if (p.kind == "host") out.hosts += 1 else out.elements += 1
            }
        }
        return out
    }

    @Synchronized
    fun snapshot(limit: Int = 100): Snapshot {
        val els = ArrayList<Pair<String, String>>()
        for ((h, set) in elements) for (s in set) els.add(Pair(h, s))
        return Snapshot(hosts.size, elementCount, hosts.sorted().take(limit), els.take(limit))
    }

    @Synchronized
    fun clear() {
        hosts.clear()
        elements.clear()
        cssCache.clear()
        elementCount = 0
    }
}
