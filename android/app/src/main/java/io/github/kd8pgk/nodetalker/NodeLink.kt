package io.github.kd8pgk.nodetalker

import java.io.IOException
import java.net.InetAddress
import java.security.MessageDigest

object NodeLink {
    const val MAX_ADDRESSES = 4

    class Found(val host: String, val ip: String)

    fun candidates(host: String, addr: String): List<String> =
        listOf(host, addr).filter { it.isNotEmpty() }.distinct()

    fun needsIdentity(https: Boolean, pin: String): Boolean = https && pin.isNotEmpty()

    fun addressesOf(name: String): List<String> = try {
        Dial.order(InetAddress.getAllByName(name).toList()).mapNotNull { it.hostAddress }.distinct().take(MAX_ADDRESSES)
    } catch (e: IOException) {
        emptyList()
    }

    fun locate(
        host: String,
        addr: String,
        port: Int,
        pin: String,
        resolve: (String) -> List<String>,
        presented: (String, Int) -> String?,
    ): Found? {
        for (cand in candidates(host, addr)) {
            for (ip in resolve(cand)) {
                val fp = presented(ip, port) ?: continue
                if (fp == pin) return Found(cand, ip)
            }
        }
        return null
    }

    fun fingerprint(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString(":") { "%02X".format(it) }
}
