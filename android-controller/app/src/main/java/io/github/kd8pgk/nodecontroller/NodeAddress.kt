package io.github.kd8pgk.nodecontroller

data class NodeAddress(val host: String, val port: Int, val https: Boolean) {
    val origin: String
        get() = (if (https) "https" else "http") + "://" + (if (host.contains(':')) "[$host]" else host) + ":" + port

    fun isOrigin(scheme: String?, urlHost: String?, urlPort: Int): Boolean {
        val s = scheme?.lowercase() ?: return false
        val h = urlHost?.trim('[', ']') ?: return false
        val p = if (urlPort != -1) urlPort else if (s == "https") 443 else 80
        return s == (if (https) "https" else "http") && h.equals(host, ignoreCase = true) && p == port
    }

    companion object {
        const val DEFAULT_PORT = 8989
        private val HOST_RE = Regex("^[A-Za-z0-9]([A-Za-z0-9.-]{0,252})$|^[0-9A-Fa-f:.]{2,45}$")

        fun validHost(h: String) = HOST_RE.matches(h)

        fun parse(text: String): NodeAddress? {
            var rest = text.trim()
            var https = false
            val sep = rest.indexOf("://")
            if (sep >= 0) {
                when (rest.substring(0, sep).lowercase()) {
                    "http" -> https = false
                    "https" -> https = true
                    else -> return null
                }
                rest = rest.substring(sep + 3)
            }
            rest = rest.substringBefore('/').substringBefore('?').substringBefore('#')
            if (rest.isEmpty() || rest.contains('@')) return null
            val host: String
            var portText: String? = null
            if (rest.startsWith("[")) {
                val close = rest.indexOf(']')
                if (close < 0) return null
                host = rest.substring(1, close)
                val after = rest.substring(close + 1)
                if (after.isNotEmpty()) {
                    if (!after.startsWith(":")) return null
                    portText = after.substring(1)
                }
            } else if (rest.count { it == ':' } == 1) {
                host = rest.substringBefore(':')
                portText = rest.substringAfter(':')
            } else {
                host = rest
            }
            if (!validHost(host)) return null
            val port = if (portText == null) {
                if (https) 443 else DEFAULT_PORT
            } else {
                if (portText.isEmpty() || !portText.all { it in '0'..'9' }) return null
                portText.toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
            }
            return NodeAddress(host, port, https)
        }
    }
}
