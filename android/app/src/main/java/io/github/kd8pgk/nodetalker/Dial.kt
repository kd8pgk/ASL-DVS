package io.github.kd8pgk.nodetalker

import java.io.IOException
import java.net.ConnectException
import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket

object Dial {
    private const val PER_TRY_MS = 3000

    fun order(all: List<InetAddress>): List<InetAddress> {
        fun rank(a: InetAddress) = when {
            a is Inet4Address -> 0
            a is Inet6Address && !a.isLinkLocalAddress -> 1
            else -> 2
        }
        return all.withIndex().sortedWith(compareBy({ rank(it.value) }, { it.index })).map { it.value }
    }

    fun connect(
        host: String,
        port: Int,
        totalMs: Int,
        resolve: (String) -> Array<InetAddress> = { InetAddress.getAllByName(it) },
    ): Socket {
        val list = order(resolve(host).toList())
        val deadline = System.nanoTime() + totalMs * 1_000_000L
        var last: IOException? = null
        for ((i, addr) in list.withIndex()) {
            val left = ((deadline - System.nanoTime()) / 1_000_000L).toInt()
            if (left <= 0) break
            val tryMs = if (i == list.lastIndex) left else minOf(left, PER_TRY_MS)
            val s = Socket()
            try {
                s.connect(InetSocketAddress(addr, port), tryMs)
                return s
            } catch (e: IOException) {
                last = e
                runCatching { s.close() }
            }
        }
        val cause = last ?: throw ConnectException("failed to connect to $host: no address to try")
        if (list.size < 2) throw cause
        val tried = list.joinToString(", ") { it.hostAddress ?: "?" }
        throw ConnectException("failed to connect to $host ($tried): ${cause.message}").also { it.initCause(cause) }
    }
}
