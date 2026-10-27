package io.github.kd8pgk.nodetalker

import android.content.Context
import android.net.Uri
import android.net.http.SslCertificate
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID

data class Node(
    val id: String,
    val name: String,
    val host: String,
    val port: Int,
    val https: Boolean,
    val pin: String = "",
) {
    val origin: String
        get() = (if (https) "https" else "http") + "://" + (if (host.contains(':')) "[$host]" else host) + ":" + port

    val title: String
        get() = name.ifBlank { host }

    fun sameOrigin(uri: Uri?): Boolean {
        if (uri == null) return false
        val scheme = uri.scheme?.lowercase() ?: return false
        val p = if (uri.port != -1) uri.port else if (scheme == "https") 443 else 80
        return scheme == (if (https) "https" else "http") &&
            uri.host.orEmpty().trim('[', ']').equals(host, ignoreCase = true) && p == port
    }

    fun httpsUpgrade(uri: Uri?): Boolean {
        if (https || uri == null || uri.scheme?.lowercase() != "https") return false
        val p = if (uri.port != -1) uri.port else 443
        return uri.host.orEmpty().trim('[', ']').equals(host, ignoreCase = true) && p == port
    }

    fun toJson(): JSONObject = JSONObject()
        .put("id", id).put("name", name).put("host", host)
        .put("port", port).put("https", https).put("pin", pin)

    companion object {
        const val DEFAULT_PORT = 8993
        private val HOST_RE = Regex("^[A-Za-z0-9]([A-Za-z0-9.-]{0,252})$|^[0-9A-Fa-f:.]{2,45}$")

        fun fromJson(o: JSONObject) = Node(
            o.optString("id").ifEmpty { UUID.randomUUID().toString() },
            o.optString("name"),
            o.optString("host"),
            o.optInt("port", DEFAULT_PORT),
            o.optBoolean("https"),
            o.optString("pin"),
        )

        fun validHost(h: String) = HOST_RE.matches(h)

        fun parseAddress(text: String): Triple<String, Int?, Boolean?> {
            val t = text.trim()
            if (!t.contains("://")) return Triple(t.trim('[', ']'), null, null)
            val u = Uri.parse(t)
            val https = u.scheme?.equals("https", ignoreCase = true)
            return Triple(u.host.orEmpty().trim('[', ']'), if (u.port != -1) u.port else null, https)
        }
    }
}

data class AudioSettings(val mode: String, val bufferMs: Int, val earpiece: Boolean, val voiceMic: Boolean = true) {
    val app: Boolean
        get() = mode == APP

    companion object {
        const val APP = "app"
        const val PAGE = "page"
        const val DEFAULT_BUFFER = 300
        const val MIN_BUFFER = 100
        const val MAX_BUFFER = 1000
    }
}

object NodeStore {
    private const val PREFS = "nodetalker"
    private const val KEY_NODES = "nodes"
    private const val KEY_KEEP_ON = "keep_screen_on"
    private const val KEY_MODE = "audio_mode"
    private const val KEY_BUFFER = "rx_buffer_ms"
    private const val KEY_EARPIECE = "earpiece"
    private const val KEY_VOICE_MIC = "voice_mic"

    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun all(c: Context): List<Node> {
        val arr = try {
            JSONArray(prefs(c).getString(KEY_NODES, "[]"))
        } catch (e: org.json.JSONException) {
            JSONArray()
        }
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it)?.let(Node::fromJson) }
            .filter { Node.validHost(it.host) && it.port in 1..65535 }
    }

    private fun write(c: Context, nodes: List<Node>) {
        val arr = JSONArray()
        nodes.forEach { arr.put(it.toJson()) }
        prefs(c).edit().putString(KEY_NODES, arr.toString()).apply()
    }

    fun get(c: Context, id: String?) = all(c).firstOrNull { it.id == id }

    fun put(c: Context, node: Node) {
        val list = all(c).toMutableList()
        val i = list.indexOfFirst { it.id == node.id }
        if (i >= 0) list[i] = node else list.add(node)
        write(c, list)
    }

    fun delete(c: Context, id: String) = write(c, all(c).filter { it.id != id })

    fun keepScreenOn(c: Context) = prefs(c).getBoolean(KEY_KEEP_ON, false)

    fun audio(c: Context) = prefs(c).let {
        AudioSettings(
            it.getString(KEY_MODE, AudioSettings.APP) ?: AudioSettings.APP,
            it.getInt(KEY_BUFFER, AudioSettings.DEFAULT_BUFFER).coerceIn(AudioSettings.MIN_BUFFER, AudioSettings.MAX_BUFFER),
            it.getBoolean(KEY_EARPIECE, false),
            it.getBoolean(KEY_VOICE_MIC, true),
        )
    }

    fun setAudio(c: Context, a: AudioSettings) = prefs(c).edit()
        .putString(KEY_MODE, a.mode).putInt(KEY_BUFFER, a.bufferMs).putBoolean(KEY_EARPIECE, a.earpiece)
        .putBoolean(KEY_VOICE_MIC, a.voiceMic).apply()

    fun setKeepScreenOn(c: Context, on: Boolean) = prefs(c).edit().putBoolean(KEY_KEEP_ON, on).apply()
}

object Certs {
    fun fingerprint(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString(":") { "%02X".format(it) }

    fun der(cert: SslCertificate?): ByteArray? {
        if (cert == null) return null
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            cert.x509Certificate?.encoded
        } else {
            SslCertificate.saveState(cert).getByteArray("x509-certificate")
        }
    }

    fun pretty(fp: String): String = fp.split(":").chunked(8).joinToString("\n") { it.joinToString(":") }
}
