package io.github.kd8pgk.nodetalker

class Backoff(private val firstMs: Long, private val maxMs: Long = 10000L, private val stableMs: Long = 5000L) {
    private var delayMs = firstMs

    fun next(upMs: Long): Long {
        if (upMs >= stableMs) delayMs = firstMs
        val wait = delayMs
        delayMs = minOf(delayMs * 2, maxMs)
        return wait
    }
}
