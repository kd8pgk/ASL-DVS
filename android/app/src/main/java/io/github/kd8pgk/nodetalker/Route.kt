package io.github.kd8pgk.nodetalker

import java.net.InetSocketAddress
import java.net.Socket

object NodeRoute {
    const val HOME_MS = 1500
    const val KEEP_MS = 30000L

    private val seen = HashMap<String, Pair<Long, Boolean>>()

    fun decide(node: Node, homeReachable: Boolean): Node = if (node.hasAway && !homeReachable) node.useAway() else node

    fun pick(node: Node, now: Long = System.currentTimeMillis(), probe: (Node) -> Boolean = ::reachable): Node {
        if (!node.hasAway) return node
        val hit = synchronized(seen) { seen[node.id] }
        if (hit != null && now - hit.first < KEEP_MS) return decide(node, hit.second)
        val ok = probe(node)
        synchronized(seen) { seen[node.id] = Pair(now, ok) }
        return decide(node, ok)
    }

    fun forget(id: String) {
        synchronized(seen) { seen.remove(id) }
    }

    fun reachable(node: Node): Boolean = try {
        Socket().use {
            it.connect(InetSocketAddress(node.host, node.port), HOME_MS)
            true
        }
    } catch (e: java.io.IOException) {
        false
    } catch (e: SecurityException) {
        false
    }
}

object AwayLearn {
    fun candidate(url: String, allowWan: Boolean): Triple<String, Int, Boolean>? {
        if (!allowWan || !url.startsWith("https://")) return null
        val (host, port, https) = Node.parseAddress(url)
        if (https != true || !Node.validHost(host) || port == null || port !in 1..65535) return null
        return Triple(host, port, true)
    }

    fun apply(node: Node, found: Triple<String, Int, Boolean>?): Node? {
        if (found == null || !node.awayAuto || node.viaAway) return null
        if (node.awayHost.equals(found.first, true) && node.awayPort == found.second && node.awayHttps == found.third) return null
        return node.copy(awayHost = found.first, awayPort = found.second, awayHttps = found.third)
    }

    fun fetch(node: Node, cookie: String?): Triple<String, Int, Boolean>? {
        val c = NodeHttp.open(node, "/api/internet", cookie)
        try {
            c.connectTimeout = 4000
            c.readTimeout = 6000
            if (c.responseCode != 200) return null
            val o = org.json.JSONObject(c.inputStream.bufferedReader().readText())
            return candidate(o.optString("url"), o.optBoolean("allow_wan"))
        } catch (e: java.io.IOException) {
            return null
        } catch (e: org.json.JSONException) {
            return null
        } finally {
            c.disconnect()
        }
    }
}
