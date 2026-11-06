package io.github.kd8pgk.nodetalker

import java.io.EOFException
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertificateException
import javax.net.ssl.SSLException

class NodeHttpException(val code: Int, message: String) : IOException(message)

object SocketErrors {
    const val TIMEOUT = "timeout"
    const val CONNECT = "connect"
    const val TLS = "tls"
    const val RESET = "reset"
    const val CLOSED = "closed"
    const val HTTP = "http"
    const val LOGIN = "login"
    const val OTHER = "other"

    private const val MAX_DEPTH = 8
    private const val DETAIL_MAX = 300

    private fun chain(e: Throwable): List<Throwable> {
        val out = ArrayList<Throwable>()
        var t: Throwable? = e
        while (t != null && out.size < MAX_DEPTH && out.none { it === t }) {
            out.add(t)
            t = t.cause
        }
        return out
    }

    private fun has(m: String?, vararg words: String): Boolean {
        val s = (m ?: "").lowercase()
        return words.any { s.contains(it) }
    }

    fun classify(e: Throwable): String {
        val all = chain(e)
        val http = all.filterIsInstance<NodeHttpException>().firstOrNull()
        if (http != null) return if (http.code == 401) LOGIN else HTTP
        if (all.any { it is SocketTimeoutException }) return TIMEOUT
        if (all.any { it is CertificateException || has(it.message, "certificate", "trust anchor") }) return TLS
        if (all.any { it is ConnectException || it is UnknownHostException || it is NoRouteToHostException }) return CONNECT
        if (all.any { it is SocketException && has(it.message, "reset", "broken pipe", "abort") }) return RESET
        if (all.any { it is EOFException || has(it.message, "closed", "ended", "end of stream") }) return CLOSED
        if (all.any { it is SSLException }) return TLS
        if (all.any { has(it.message, "log in") }) return LOGIN
        if (all.any { Regex("http [0-9]{3}").containsMatchIn((it.message ?: "").lowercase()) }) return HTTP
        return OTHER
    }

    fun httpCode(e: Throwable): Int = chain(e).filterIsInstance<NodeHttpException>().firstOrNull()?.code ?: 0

    fun detail(e: Throwable): String = (e.message?.takeIf { it.isNotBlank() } ?: e.javaClass.simpleName).take(DETAIL_MAX)
}

class FailureReporter(private val gapMs: Long = 60000L) {
    class Down(val failures: Int)
    class Recovered(val secs: Int, val failures: Int)

    private var lastReportAt = Long.MIN_VALUE / 2
    private var runStart = 0L
    private var runCount = 0
    private var runReported = false
    private var pending = 0

    fun fail(nowMs: Long): Down? {
        if (runCount == 0) {
            runStart = nowMs
            runReported = false
        }
        runCount++
        pending++
        if (nowMs - lastReportAt < gapMs) return null
        lastReportAt = nowMs
        runReported = true
        val n = pending
        pending = 0
        return Down(n)
    }

    fun up(nowMs: Long): Recovered? {
        if (runCount == 0) return null
        val reported = runReported
        val out = Recovered(((nowMs - runStart) / 1000L).toInt().coerceAtLeast(0), runCount)
        runCount = 0
        pending = 0
        runReported = false
        return if (reported) out else null
    }
}
