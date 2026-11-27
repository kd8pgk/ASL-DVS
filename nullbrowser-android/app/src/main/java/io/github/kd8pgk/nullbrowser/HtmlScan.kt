package io.github.kd8pgk.nullbrowser

import java.net.URI

data class Seg(val t: String, val href: String = "")

sealed class ViewItem {
    data class Img(val src: String, val thumb: String, val href: String, val w: Int, val h: Int) : ViewItem()
    data class Text(val tag: String, val segs: List<Seg>) : ViewItem()
}

class Scan(val title: String, val baseHref: String, val items: List<ViewItem>)

class Clean(val title: String, val items: List<ViewItem>)

object HtmlScan {
    private val VOID = setOf("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr")
    private val SKIP = setOf("script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed", "head", "select", "option", "textarea", "button", "nav", "footer", "aside", "form", "audio", "math")
    private val RAW = setOf("script", "style", "noscript", "template", "textarea", "title")
    private val TEXT_BLOCKS = setOf("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "figcaption", "pre", "dt", "dd")
    private val INLINE = setOf("a", "span", "b", "i", "em", "strong", "small", "code", "mark", "u", "sub", "sup", "abbr", "cite", "time", "label", "font", "s", "q", "big", "tt", "kbd", "samp", "var", "bdi", "bdo", "ins", "del", "dfn", "wbr")
    private val ROLES = setOf("navigation", "banner", "complementary", "contentinfo", "search")
    private val HIDDEN_STYLE = Regex("display\\s*:\\s*none|visibility\\s*:\\s*hidden", RegexOption.IGNORE_CASE)
    private val ENTITY = Regex("&(#[xX][0-9a-fA-F]{1,6}|#[0-9]{1,7}|[a-zA-Z]{2,10});")
    private val NAMED = mapOf(
        "amp" to "&", "lt" to "<", "gt" to ">", "quot" to "\"", "apos" to "'", "nbsp" to " ", "copy" to "©", "reg" to "®",
        "mdash" to "—", "ndash" to "–", "hellip" to "…", "lsquo" to "‘", "rsquo" to "’", "ldquo" to "“", "rdquo" to "”",
        "bull" to "•", "middot" to "·", "laquo" to "«", "raquo" to "»", "eacute" to "é", "egrave" to "è", "uuml" to "ü", "ouml" to "ö", "auml" to "ä",
    )
    private val IMAGE_LIKE = Regex("\\.(jpe?g|png|gif|webp|avif)$", RegexOption.IGNORE_CASE)
    private val LAZY = listOf("data-src", "data-original", "data-lazy-src", "data-lazy", "src")

    fun decode(s: String): String {
        if (!s.contains('&')) return s
        return ENTITY.replace(s) { m ->
            val g = m.groupValues[1]
            when {
                g.startsWith("#x") || g.startsWith("#X") -> codePoint(g.substring(2).toIntOrNull(16))
                g.startsWith("#") -> codePoint(g.substring(1).toIntOrNull())
                else -> NAMED[g] ?: m.value
            }
        }
    }

    private fun codePoint(n: Int?): String = if (n == null || n <= 0 || n > 0x10ffff || (n in 0xd800..0xdfff)) "" else String(Character.toChars(n))

    private class Frame(val name: String, val href: String, val textBlock: Boolean)

    private class Tag(val name: String, val closing: Boolean, val attrs: Map<String, String>, val end: Int)

    private fun parseTag(s: String, start: Int): Tag? {
        var i = start + 1
        var closing = false
        if (i < s.length && s[i] == '/') {
            closing = true
            i++
        }
        val nameStart = i
        while (i < s.length && (s[i].isLetterOrDigit() || s[i] == '-' || s[i] == ':')) i++
        if (i == nameStart || !s[nameStart].isLetter()) return null
        val name = s.substring(nameStart, i).lowercase()
        val attrs = LinkedHashMap<String, String>()
        while (i < s.length && s[i] != '>') {
            while (i < s.length && (s[i].isWhitespace() || s[i] == '/')) i++
            if (i >= s.length || s[i] == '>') break
            val ns = i
            while (i < s.length && !s[i].isWhitespace() && s[i] != '=' && s[i] != '>' && s[i] != '/') i++
            val an = s.substring(ns, i).lowercase()
            while (i < s.length && s[i].isWhitespace()) i++
            var value = ""
            if (i < s.length && s[i] == '=') {
                i++
                while (i < s.length && s[i].isWhitespace()) i++
                if (i < s.length && (s[i] == '"' || s[i] == '\'')) {
                    val q = s[i]
                    val e = s.indexOf(q, i + 1)
                    val stop = if (e < 0) s.length else e
                    value = s.substring(i + 1, stop)
                    i = if (e < 0) s.length else e + 1
                } else {
                    val vs = i
                    while (i < s.length && !s[i].isWhitespace() && s[i] != '>') i++
                    value = s.substring(vs, i)
                }
            }
            if (an.isNotEmpty() && attrs.size < 40 && !attrs.containsKey(an)) attrs[an] = decode(value.take(8192))
        }
        return Tag(name, closing, attrs, if (i < s.length) i + 1 else s.length)
    }

    private fun largest(sets: List<String?>, fallback: String): String {
        var best = ""
        var bestW = -1.0
        for (set in sets) {
            if (set.isNullOrBlank()) continue
            for (cand in set.split(Regex(",\\s+|,(?=[^\\s])")).take(30)) {
                val bits = cand.trim().split(Regex("\\s+"))
                if (bits[0].isEmpty()) continue
                val d = bits.getOrElse(1) { "" }
                val w = when {
                    d.endsWith("w") -> d.dropLast(1).toDoubleOrNull() ?: 1.0
                    d.endsWith("x") -> (d.dropLast(1).toDoubleOrNull() ?: 1.0) * 1000
                    else -> 1.0
                }
                if (w > bestW) {
                    bestW = w
                    best = bits[0]
                }
            }
        }
        return best.ifEmpty { fallback }
    }

    private fun shouldSkip(name: String, attrs: Map<String, String>): Boolean {
        if (name in SKIP) return true
        if (attrs.containsKey("hidden") || attrs["aria-hidden"] == "true") return true
        if (name == "input" && attrs["type"]?.lowercase() == "hidden") return true
        val role = attrs["role"]?.lowercase()
        if (role != null && role in ROLES) return true
        val style = attrs["style"]
        return style != null && HIDDEN_STYLE.containsMatchIn(style)
    }

    fun scan(html: String, wantText: Boolean): Scan {
        val s = if (html.length > ViewTier.MAX_HTML_BYTES) html.substring(0, ViewTier.MAX_HTML_BYTES) else html
        val items = ArrayList<ViewItem>()
        val stack = ArrayList<Frame>()
        val run = ArrayList<Seg>()
        val sets = ArrayList<String?>()
        var title = ""
        var baseHref = ""
        var skipAt = -1
        var imgs = 0
        var texts = 0
        var chars = 0
        var i = 0

        fun runTag(): String = stack.lastOrNull { it.textBlock }?.name ?: "p"
        fun linkHref(): String = stack.lastOrNull { it.name == "a" && it.href.isNotEmpty() }?.href ?: ""

        fun flush() {
            if (run.isEmpty()) return
            val tag = runTag()
            val segs = ArrayList<Seg>()
            for (r in run) {
                val t = if (tag == "pre") r.t else r.t.replace(Regex("\\s+"), " ")
                if (t.isNotEmpty()) segs.add(Seg(t, r.href))
            }
            run.clear()
            if (!wantText || segs.isEmpty() || texts >= ViewTier.MAX_TEXT_ITEMS || chars > 200000) return
            if (tag != "pre") {
                while (segs.isNotEmpty() && segs.first().t.isBlank()) segs.removeAt(0)
                while (segs.isNotEmpty() && segs.last().t.isBlank()) segs.removeAt(segs.size - 1)
                if (segs.isEmpty()) return
                segs[0] = Seg(segs[0].t.trimStart(), segs[0].href)
                val last = segs.size - 1
                segs[last] = Seg(segs[last].t.trimEnd(), segs[last].href)
            }
            val len = segs.sumOf { it.t.length }
            if (len < 2 || segs.none { it.t.any { c -> !c.isWhitespace() } }) return
            texts += 1
            chars += len
            items.add(ViewItem.Text(tag, segs.filter { it.t.isNotEmpty() }))
        }

        fun popTo(name: String) {
            val j = stack.indexOfLast { it.name == name }
            if (j < 0) return
            while (stack.size > j) stack.removeAt(stack.size - 1)
            if (skipAt >= stack.size) skipAt = -1
        }

        while (i < s.length) {
            val lt = s.indexOf('<', i)
            val textEnd = if (lt < 0) s.length else lt
            if (textEnd > i && skipAt < 0 && wantText) {
                val t = decode(s.substring(i, textEnd))
                if (t.isNotEmpty()) run.add(Seg(t, linkHref()))
            }
            if (lt < 0) break
            i = lt
            if (s.startsWith("<!--", i)) {
                val e = s.indexOf("-->", i + 4)
                i = if (e < 0) s.length else e + 3
                continue
            }
            if (i + 1 < s.length && (s[i + 1] == '!' || s[i + 1] == '?')) {
                val e = s.indexOf('>', i)
                i = if (e < 0) s.length else e + 1
                continue
            }
            val tag = parseTag(s, i)
            if (tag == null) {
                if (skipAt < 0 && wantText) run.add(Seg("<", linkHref()))
                i += 1
                continue
            }
            i = tag.end
            val name = tag.name
            if (tag.closing) {
                if (name in RAW) continue
                if (skipAt < 0 && name !in INLINE) flush()
                if (name == "picture") sets.clear()
                popTo(name)
                continue
            }
            if (name == "body" || name == "html") {
                flush()
                stack.clear()
                skipAt = -1
                continue
            }
            if (name == "base") {
                if (baseHref.isEmpty()) baseHref = tag.attrs["href"] ?: ""
                continue
            }
            if (name in RAW) {
                val close = Regex("</" + name + "\\s*>", RegexOption.IGNORE_CASE).find(s, i)
                val endContent = close?.range?.first ?: s.length
                if (name == "title" && title.isEmpty()) title = decode(s.substring(i, endContent)).replace(Regex("\\s+"), " ").trim().take(200)
                i = if (close == null) s.length else close.range.last + 1
                continue
            }
            val skipping = skipAt >= 0
            if (name == "br") {
                if (!skipping && wantText) run.add(Seg(" ", linkHref()))
                continue
            }
            if (name == "source") {
                if (!skipping) sets.add(tag.attrs["srcset"])
                continue
            }
            if (name == "img") {
                if (!skipping && !shouldSkip(name, tag.attrs)) {
                    flush()
                    val own = tag.attrs["srcset"] ?: tag.attrs["data-srcset"]
                    val fallback = LAZY.firstNotNullOfOrNull { k -> tag.attrs[k]?.takeIf { it.isNotBlank() } } ?: ""
                    val src = largest(sets + own, fallback)
                    val w = tag.attrs["width"]?.takeIf { it.all { c -> c.isDigit() } && it.isNotEmpty() }?.toIntOrNull() ?: 0
                    val h = tag.attrs["height"]?.takeIf { it.all { c -> c.isDigit() } && it.isNotEmpty() }?.toIntOrNull() ?: 0
                    if (src.isNotBlank() && imgs < ViewTier.MAX_PICTURES) {
                        imgs += 1
                        items.add(ViewItem.Img(src.trim(), "", linkHref(), w, h))
                    }
                    sets.clear()
                }
                continue
            }
            if (name == "video") {
                if (!skipping && !shouldSkip(name, tag.attrs)) {
                    val poster = tag.attrs["poster"]
                    if (!poster.isNullOrBlank() && imgs < ViewTier.MAX_PICTURES) {
                        flush()
                        imgs += 1
                        items.add(ViewItem.Img(poster.trim(), "", "", 0, 0))
                    }
                }
                if (name !in VOID) stack.add(Frame(name, "", false))
                continue
            }
            if (name in VOID) continue
            val hides = !skipping && shouldSkip(name, tag.attrs)
            if (!skipping && name !in INLINE) {
                if (name in TEXT_BLOCKS && stack.isNotEmpty() && stack.last().name == name && name in setOf("p", "li", "dt", "dd")) {
                    flush()
                    stack.removeAt(stack.size - 1)
                }
                flush()
            }
            if (name == "picture") sets.clear()
            val href = if (name == "a") (tag.attrs["href"]?.takeIf { !Regex("^\\s*(javascript|data|mailto|tel):", RegexOption.IGNORE_CASE).containsMatchIn(it) } ?: "") else ""
            stack.add(Frame(name, href, name in TEXT_BLOCKS))
            if (hides && skipAt < 0) skipAt = stack.size - 1
        }
        flush()
        return Scan(title, baseHref, items)
    }

    private val ILLEGAL = Regex("[ \"<>\\\\^`{|}\\[\\]]")

    private fun encodeIllegal(r: String): String = ILLEGAL.replace(r) { String.format("%%%02X", it.value[0].code) }

    private fun resolve(base: String, ref: String): String {
        val r = ref.trim()
        if (r.isEmpty() || r.length > ViewTier.MAX_URL) return ""
        return try {
            val u = URI(base).resolve(URI(encodeIllegal(r)))
            if (u.scheme != "http" && u.scheme != "https") "" else URI(u.scheme, u.rawAuthority, u.path, u.query, null).toString()
        } catch (_: Exception) {
            ""
        }
    }

    fun clean(scan: Scan, pageUrl: String, tier: Int): Clean {
        val base = if (scan.baseHref.isNotBlank()) resolve(pageUrl, scan.baseHref).ifEmpty { pageUrl } else pageUrl
        val out = ArrayList<ViewItem>()
        val seen = HashSet<String>()
        val links = ViewTier.wantLinks(tier)
        for (it in scan.items) {
            when (it) {
                is ViewItem.Img -> {
                    var src = resolve(base, it.src)
                    val link = resolve(base, it.href)
                    var thumb = ""
                    if (link.isNotEmpty() && link != src && IMAGE_LIKE.containsMatchIn(link.substringBefore('?'))) {
                        thumb = src
                        src = link
                    }
                    if (src.isEmpty() || !seen.add(src)) continue
                    if ((it.w in 1 until ViewTier.MIN_SIDE) || (it.h in 1 until ViewTier.MIN_SIDE)) continue
                    out.add(ViewItem.Img(src, if (thumb != src) thumb else "", if (links && link.isNotEmpty() && link != src) link else "", it.w, it.h))
                }
                is ViewItem.Text -> {
                    if (!ViewTier.wantText(tier)) continue
                    val segs = ArrayList<Seg>()
                    var total = 0
                    for (s in it.segs.take(80)) {
                        val t = s.t.replace(Regex("[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f]"), " ").take(ViewTier.MAX_TEXT)
                        if (t.isEmpty()) continue
                        total += t.length
                        if (total > ViewTier.MAX_TEXT) break
                        val href = if (links) resolve(base, s.href) else ""
                        segs.add(Seg(t, href))
                    }
                    if (segs.isNotEmpty()) out.add(ViewItem.Text(it.tag, segs))
                }
            }
        }
        val title = if (ViewTier.wantText(tier)) scan.title.replace(Regex("[\\u0000-\\u001f\\u007f]"), " ").take(200) else ""
        return Clean(title, out)
    }
}
