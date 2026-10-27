package io.github.kd8pgk.nodetalker

import android.webkit.CookieManager
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

class NodeApi(private val node: Node, private val cookie: () -> String? = { webViewCookie(node) }) {
    open class ApiException(val code: Int, message: String) : IOException(message)

    class NotLoggedIn : ApiException(401, "Log in first.")

    fun health(): JSONObject = request("GET", "/api/health", null, false)

    fun whoami(): JSONObject = request("GET", "/api/whoami", null, true)

    fun status(): JSONObject = request("GET", "/api/status", null, true)

    fun get(path: String): JSONObject = request("GET", path, null, true)

    fun post(path: String, body: JSONObject = JSONObject()): JSONObject = request("POST", path, body, true)

    fun getLoose(path: String): JSONObject = request("GET", path, null, true, true)

    fun postLoose(path: String, body: JSONObject = JSONObject(), readMs: Int = 0): JSONObject =
        request("POST", path, body, true, true, readMs)

    private fun request(method: String, path: String, body: JSONObject?, withSession: Boolean, loose: Boolean = false, readMs: Int = 0): JSONObject {
        val c = NodeHttp.open(node, path, if (withSession) cookie() else null)
        if (readMs > 0) c.readTimeout = readMs
        try {
            c.requestMethod = method
            c.setRequestProperty("X-Requested-With", "XMLHttpRequest")
            c.setRequestProperty("Accept", "application/json")
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = c.responseCode
            val ok = code in 200..299
            val text = (if (ok) c.inputStream else c.errorStream)?.use { it.readBytes().toString(Charsets.UTF_8) }.orEmpty()
            val json = try {
                JSONObject(text)
            } catch (e: JSONException) {
                null
            }
            if (code == 401) throw NotLoggedIn()
            if (!ok && loose) return json ?: JSONObject().put("ok", false).put("error", "HTTP $code")
            if (!ok) throw ApiException(code, json?.optString("error").orEmpty().ifEmpty { "HTTP $code" })
            return json ?: throw IOException("The node did not answer with JSON")
        } finally {
            c.disconnect()
        }
    }

    companion object {
        fun webViewCookie(node: Node): String? = CookieManager.getInstance().getCookie(node.origin)
    }
}
