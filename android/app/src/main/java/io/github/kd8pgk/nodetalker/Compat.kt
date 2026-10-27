package io.github.kd8pgk.nodetalker

import java.util.concurrent.ConcurrentHashMap

object Compat {
    val MATCHES: Set<String> = setOf("0.9.35", "0.9.39", "0.9.40")
    val NATIVE_TABS: Set<String> = setOf("connect", "listen")

    private val seen = ConcurrentHashMap<String, String>()

    fun useNative(tab: String, nodeVersion: String?): Boolean =
        tab in NATIVE_TABS && nodeVersion != null && nodeVersion in MATCHES

    fun remember(nodeId: String, version: String) {
        if (version.isNotBlank()) seen[nodeId] = version
    }

    fun seen(nodeId: String): String? = seen[nodeId]
}
