package io.github.kd8pgk.nodetalker

import java.io.IOException

object RxReport {
    const val SENT = 0
    const val FAILED = 1
    const val UNSUPPORTED = 2

    fun send(node: Node, cookie: String?, s: PlayStats.Snapshot): Int {
        val c = NodeHttp.open(node, "/api/rxhealth/client", cookie)
        return try {
            val body = s.json().toByteArray(Charsets.UTF_8)
            c.requestMethod = "POST"
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.setRequestProperty("X-Requested-With", "XMLHttpRequest")
            c.setFixedLengthStreamingMode(body.size)
            c.outputStream.use { it.write(body) }
            when (c.responseCode) {
                200 -> SENT
                404 -> UNSUPPORTED
                else -> FAILED
            }
        } catch (e: IOException) {
            FAILED
        } finally {
            c.disconnect()
        }
    }
}
