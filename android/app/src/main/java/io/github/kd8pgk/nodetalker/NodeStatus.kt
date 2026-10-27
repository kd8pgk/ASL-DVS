package io.github.kd8pgk.nodetalker

import org.json.JSONObject

data class TxState(val keyed: Boolean, val who: String, val secs: Double, val ready: Boolean, val tot: Double)

data class LinkInfo(val state: String, val label: String, val mode: String, val tag: String)

data class NodeStatus(
    val node: String,
    val listeners: Int,
    val maxListeners: Int,
    val receiving: Boolean,
    val packets: Int,
    val lastRxAge: Double?,
    val audioActive: Boolean,
    val peakDb: Double,
    val kcTest: Boolean,
    val tx: TxState?,
    val link: LinkInfo?,
    val links: List<String> = emptyList(),
    val m17: String = "",
    val tuned: String = "",
    val tunedNow: String = "",
    val defaultMode: String = "",
) {
    val feedText: String
        get() = when {
            receiving -> "feed"
            lastRxAge != null -> "no feed ${Math.round(lastRxAge)} s"
            else -> "no feed yet"
        }

    val feedLevel: Int
        get() = if (receiving) DOT_ON else if (packets > 0) DOT_WARN else DOT_ERR

    companion object {
        const val DOT_OFF = 0
        const val DOT_ON = 1
        const val DOT_RX = 2
        const val DOT_TX = 3
        const val DOT_WARN = 4
        const val DOT_ERR = 5

        fun parse(j: JSONObject): NodeStatus {
            val t = j.optJSONObject("tx")
            val l = j.optJSONObject("link")
            val la = j.optJSONArray("links")
            return NodeStatus(
                node = j.optString("node"),
                listeners = j.optInt("listeners"),
                maxListeners = j.optInt("max_listeners"),
                receiving = j.optBoolean("receiving"),
                packets = j.optInt("packets"),
                lastRxAge = if (j.isNull("last_rx_age") || !j.has("last_rx_age")) null else j.optDouble("last_rx_age"),
                audioActive = j.optBoolean("audio_active"),
                peakDb = j.optDouble("peak_db", -120.0),
                kcTest = j.optBoolean("kc_test"),
                tx = t?.let {
                    TxState(it.optBoolean("keyed"), it.optString("who"), it.optDouble("secs", 0.0), it.optBoolean("ready"), it.optDouble("tot", 0.0))
                },
                link = l?.let { LinkInfo(it.optString("state"), it.optString("label"), it.optString("mode"), it.optString("tag")) },
                links = if (la == null) emptyList() else (0 until la.length()).mapNotNull { la.optJSONObject(it)?.optString("node")?.takeIf { n -> n.isNotEmpty() } },
                m17 = j.optString("m17"),
                tuned = j.optString("tuned"),
                tunedNow = j.optString("tuned_now"),
                defaultMode = j.optString("default_mode"),
            )
        }
    }
}
