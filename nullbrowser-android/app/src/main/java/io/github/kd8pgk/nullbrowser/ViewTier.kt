package io.github.kd8pgk.nullbrowser

object ViewTier {
    val LABELS = listOf("Pictures only", "Pictures and text", "Pictures, text and links", "Page layout and media, no scripts", "Full page")
    val SHORT = listOf("Pictures", "Text", "Links", "Layout", "Full")

    const val MAX_PICTURES = 400
    const val MAX_TEXT_ITEMS = 1500
    const val MAX_TEXT = 3000
    const val MAX_URL = 4096
    const val MAX_PIC_BYTES = 25L * 1024 * 1024
    const val MAX_TOTAL_BYTES = 300L * 1024 * 1024
    const val MAX_TOKENS = 600
    const val MAX_HTML_BYTES = 5 * 1024 * 1024
    const val MIN_SIDE = 120

    fun normalize(n: Int): Int = n.coerceIn(0, 4)

    fun applyTick(tier: Int, key: String, on: Boolean): Int {
        val level = when (key) {
            "text" -> 1
            "links" -> 2
            "layout" -> 3
            "scripts" -> 4
            else -> return normalize(tier)
        }
        return if (on) maxOf(normalize(tier), level) else minOf(normalize(tier), level - 1)
    }

    fun gallery(tier: Int): Boolean = normalize(tier) <= 2
    fun wantText(tier: Int): Boolean = normalize(tier) >= 1
    fun wantLinks(tier: Int): Boolean = normalize(tier) >= 2
    fun scriptsOn(tier: Int): Boolean = normalize(tier) != 3

    fun imageMime(b: ByteArray): String {
        if (b.size < 12) return ""
        if (b[0] == 0xff.toByte() && b[1] == 0xd8.toByte() && b[2] == 0xff.toByte()) return "image/jpeg"
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a)
        if (png.indices.all { b[it] == png[it] }) return "image/png"
        val head = String(b, 0, 12, Charsets.ISO_8859_1)
        if (head.startsWith("GIF87a") || head.startsWith("GIF89a")) return "image/gif"
        if (head.startsWith("RIFF") && head.substring(8, 12) == "WEBP") return "image/webp"
        if (head.substring(4, 8) == "ftyp") {
            val brand = head.substring(8, 12)
            if (brand == "avif" || brand == "avis") return "image/avif"
        }
        return ""
    }

    fun passThrough(contentType: String?): Boolean {
        val t = (contentType ?: "").substringBefore(';').trim().lowercase()
        if (t.isEmpty()) return false
        if (t == "image/svg+xml") return false
        return t.startsWith("image/") || t.startsWith("audio/") || t.startsWith("video/") || t == "application/pdf" || t == "text/plain" || t == "application/octet-stream"
    }

    fun isHtml(contentType: String?): Boolean {
        val t = (contentType ?: "").substringBefore(';').trim().lowercase()
        return t == "text/html" || t == "application/xhtml+xml"
    }
}
