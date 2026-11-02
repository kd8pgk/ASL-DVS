package io.github.kd8pgk.nodetalker

class PlayStats {
    private var under = 0
    private var reset = 0
    private var silenceMs = 0L

    class Snapshot(val under: Int, val reset: Int, val silenceMs: Long) {
        fun json(): String = "{\"under\":$under,\"reset\":$reset,\"silence_ms\":$silenceMs}"
    }

    @Synchronized
    fun underrun(count: Int, silence: Long) {
        if (count <= 0) return
        under = (under + count).coerceAtMost(LIMIT)
        silenceMs = (silenceMs + silence.coerceAtLeast(0)).coerceAtMost(LIMIT.toLong())
    }

    @Synchronized
    fun reset(count: Int = 1) {
        if (count > 0) reset = (reset + count).coerceAtMost(LIMIT)
    }

    @Synchronized
    fun take(): Snapshot? {
        if (under == 0 && reset == 0) return null
        val s = Snapshot(under, reset, silenceMs)
        under = 0
        reset = 0
        silenceMs = 0
        return s
    }

    @Synchronized
    fun put(s: Snapshot) {
        under = (under + s.under).coerceAtMost(LIMIT)
        reset = (reset + s.reset).coerceAtMost(LIMIT)
        silenceMs = (silenceMs + s.silenceMs).coerceAtMost(LIMIT.toLong())
    }

    @Synchronized
    fun clear() {
        under = 0
        reset = 0
        silenceMs = 0
    }

    companion object {
        const val LIMIT = 100000
    }
}
