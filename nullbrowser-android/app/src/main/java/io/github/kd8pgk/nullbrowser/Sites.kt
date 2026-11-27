package io.github.kd8pgk.nullbrowser

object Sites {
    private val MULTI = setOf(
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk",
        "plc.uk", "net.uk", "com.au", "net.au", "org.au", "edu.au",
        "gov.au", "asn.au", "id.au", "co.nz", "org.nz", "net.nz",
        "govt.nz", "ac.nz", "co.jp", "ne.jp", "or.jp", "ac.jp",
        "go.jp", "com.br", "net.br", "org.br", "gov.br", "co.za",
        "org.za", "gov.za", "co.in", "net.in", "org.in", "gov.in",
        "ac.in", "com.cn", "net.cn", "org.cn", "gov.cn", "com.mx",
        "org.mx", "gob.mx", "co.kr", "or.kr", "go.kr", "com.tw",
        "org.tw", "gov.tw", "com.hk", "org.hk", "gov.hk", "com.sg",
        "org.sg", "gov.sg", "com.ar", "gob.ar", "com.tr", "gov.tr",
        "co.il", "org.il", "gov.il", "github.io", "gitlab.io", "netlify.app",
        "vercel.app", "pages.dev", "herokuapp.com", "blogspot.com", "appspot.com", "web.app",
        "firebaseapp.com", "azurewebsites.net", "cloudfront.net",
    )

    private val IPV4 = Regex("^\\d{1,3}(?:\\.\\d{1,3}){3}$")

    fun siteOfHost(host: String?): String {
        val h = (host ?: "").lowercase().trimStart('[').trimEnd(']').trimEnd('.')
        if (h.isEmpty() || IPV4.matches(h) || h.contains(':')) return h
        val parts = h.split('.')
        if (parts.size <= 2) return h
        val last2 = parts.takeLast(2).joinToString(".")
        if (MULTI.contains(last2)) return parts.takeLast(3).joinToString(".")
        return last2
    }

    fun hostOfUrl(url: String?): String {
        val u = url ?: return ""
        val start = u.indexOf("://")
        if (start < 0) return ""
        var rest = u.substring(start + 3)
        val end = rest.indexOfFirst { it == '/' || it == '?' || it == '#' }
        if (end >= 0) rest = rest.substring(0, end)
        val at = rest.lastIndexOf('@')
        if (at >= 0) rest = rest.substring(at + 1)
        if (rest.startsWith("[")) return rest.substringBefore(']').trimStart('[').lowercase()
        return rest.substringBefore(':').lowercase()
    }
}
