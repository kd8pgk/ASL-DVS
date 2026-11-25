package io.github.kd8pgk.nullbrowser

fun isPrivateHost(host: String?): Boolean {
    val h = (host ?: "").lowercase()
    if (h.isEmpty()) return true
    if (h == "localhost" || h.endsWith(".localhost") || h.endsWith(".local") ||
        h.endsWith(".internal") || h.endsWith(".lan") || h.endsWith(".home.arpa")
    ) return true
    if (!h.contains('.') && !h.contains(':')) return true
    val v4 = Regex("^(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})$").find(h)
    if (v4 != null) {
        val a = v4.groupValues[1].toInt()
        val b = v4.groupValues[2].toInt()
        return a == 0 || a == 10 || a == 127 || (a == 169 && b == 254) ||
            (a == 172 && b in 16..31) || (a == 192 && b == 168) ||
            (a == 100 && b in 64..127) || a >= 224
    }
    if (h.contains(':')) {
        if (h == "::" || h == "::1") return true
        return Regex("^(fc|fd|fe8|fe9|fea|feb)").containsMatchIn(h) || h.startsWith("::ffff:")
    }
    return false
}
