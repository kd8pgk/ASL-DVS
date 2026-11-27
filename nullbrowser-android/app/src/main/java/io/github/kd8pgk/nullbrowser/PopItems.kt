package io.github.kd8pgk.nullbrowser

data class PopItem(
    val id: Int,
    val kind: String,
    val tag: String,
    val text: String,
    val selector: String,
    val frameHost: String,
    val thirdParty: Boolean,
    val hosts: List<String>,
    val w: Int,
    val h: Int,
)

object PopItems {
    private val KINDS = setOf("frame", "overlay", "cover", "picked")
    private val CONTROL = Regex("[\\u0000-\\u001f\\u007f]")

    private fun clean(v: Any?, max: Int): String = CONTROL.replace(MiniJson.text(v, max), " ")

    private fun clampInt(v: Any?, lo: Int, hi: Int): Int {
        val n = MiniJson.number(v)
        if (n.isNaN()) return lo
        return Math.round(n).coerceIn(lo.toLong(), hi.toLong()).toInt()
    }

    fun sanitize(raw: Any?, topHost: String, id: Int): PopItem? {
        val o = MiniJson.map(raw) ?: return null
        val hosts = ArrayList<String>()
        for (h in MiniJson.list(o["hosts"]) ?: emptyList()) {
            val c = BlockRules.cleanHost(MiniJson.text(h, 253))
            if (c.isNotEmpty() && !hosts.contains(c)) hosts.add(c)
            if (hosts.size >= 6) break
        }
        val rawHost = MiniJson.text(o["frameHost"], 253)
        val frameHost = BlockRules.cleanHost(rawHost).ifEmpty { clean(rawHost, 100).lowercase() }
        val kind = MiniJson.text(o["kind"], 20)
        return PopItem(
            id = id,
            kind = if (KINDS.contains(kind)) kind else "overlay",
            tag = clean(o["tag"], 20).lowercase().trim(),
            text = clean(o["text"], 80),
            selector = BlockRules.validSelector(clean(o["selector"], BlockRules.MAX_SELECTOR)),
            frameHost = frameHost,
            thirdParty = frameHost.isNotEmpty() && frameHost != topHost,
            hosts = hosts,
            w = clampInt(o["w"], 0, 99999),
            h = clampInt(o["h"], 0, 99999),
        )
    }

    fun parseFound(json: String?, topHost: String, nextId: () -> Int): List<PopItem> {
        val arr = MiniJson.list(MiniJson.parse(json)) ?: return emptyList()
        val out = ArrayList<PopItem>()
        for (raw in arr.take(40)) sanitize(raw, topHost, nextId())?.let { out.add(it) }
        return out
    }

    fun parsePicked(json: String?, topHost: String, id: Int): PopItem? {
        val inner = MiniJson.unwrapString(json) ?: return null
        if (inner == "null") return null
        return sanitize(MiniJson.parse(inner), topHost, id)
    }
}
