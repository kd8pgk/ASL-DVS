package io.github.kd8pgk.nodetalker

class PlayStats {
    private var under = 0
    private var reset = 0
    private var silenceMs = 0L
    private var underLocal = 0
    private var stallMs = 0L

    class Snapshot(val under: Int, val reset: Int, val silenceMs: Long, val underLocal: Int, val stallMs: Long) {
        fun json(): String = "{\"client\":\"android\",\"under\":$under,\"reset\":$reset,\"silence_ms\":$silenceMs," +
            "\"under_local\":$underLocal,\"stall_ms\":$stallMs}"
    }

    @Synchronized
    fun underrun(count: Int, silence: Long, local: Boolean = false) {
        if (count <= 0) return
        under = (under + count).coerceAtMost(LIMIT)
        if (local) underLocal = (underLocal + count).coerceAtMost(LIMIT)
        silenceMs = (silenceMs + silence.coerceAtLeast(0)).coerceAtMost(LIMIT.toLong())
    }

    @Synchronized
    fun stall(ms: Long) {
        stallMs = maxOf(stallMs, ms.coerceIn(0, LIMIT.toLong()))
    }

    @Synchronized
    fun reset(count: Int = 1) {
        if (count > 0) reset = (reset + count).coerceAtMost(LIMIT)
    }

    @Synchronized
    fun take(): Snapshot? {
        if (under == 0 && reset == 0) {
            stallMs = 0
            return null
        }
        val s = Snapshot(under, reset, silenceMs, underLocal, stallMs)
        under = 0
        reset = 0
        silenceMs = 0
        underLocal = 0
        stallMs = 0
        return s
    }

    @Synchronized
    fun put(s: Snapshot) {
        under = (under + s.under).coerceAtMost(LIMIT)
        reset = (reset + s.reset).coerceAtMost(LIMIT)
        silenceMs = (silenceMs + s.silenceMs).coerceAtMost(LIMIT.toLong())
        underLocal = (underLocal + s.underLocal).coerceAtMost(LIMIT)
        stallMs = maxOf(stallMs, s.stallMs)
    }

    @Synchronized
    fun clear() {
        under = 0
        reset = 0
        silenceMs = 0
        underLocal = 0
        stallMs = 0
    }

    companion object {
        const val LIMIT = 100000
    }
}
