package io.github.kd8pgk.nodetalker

class PlayStats {
    private var under = 0
    private var reset = 0
    private var silenceMs = 0L
    private var underLocal = 0
    private var stallMs = 0L
    private var reconn = 0
    private var why = ""
    private var ttfbMs = 0L
    private var gapMs = 0L
    private var netChg = 0
    private var probeMs = 0L
    private val netLog = NetLog()

    class Snapshot(
        val under: Int, val reset: Int, val silenceMs: Long, val underLocal: Int, val stallMs: Long,
        val reconn: Int = 0, val why: String = "", val ttfbMs: Long = 0, val gapMs: Long = 0, val netChg: Int = 0,
        val extra: String = "", val probeMs: Long = 0, val netLog: List<String> = emptyList()
    ) {
        fun json(): String = "{\"client\":\"android\",\"under\":$under,\"reset\":$reset,\"silence_ms\":$silenceMs," +
            "\"under_local\":$underLocal,\"stall_ms\":$stallMs,\"reconn\":$reconn,\"why\":\"$why\"," +
            "\"ttfb_ms\":$ttfbMs,\"gap_ms\":$gapMs,\"net_chg\":$netChg,\"probe_ms\":$probeMs," +
            "\"net_log\":\"${netLog.joinToString(";")}\"$extra}"
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
    fun reconnect(reason: String) {
        reconn = (reconn + 1).coerceAtMost(LIMIT)
        why = reason
    }

    @Synchronized
    fun firstByte(ms: Long) {
        ttfbMs = maxOf(ttfbMs, ms.coerceIn(0, LIMIT.toLong()))
    }

    @Synchronized
    fun gap(ms: Long) {
        if (ms > gapMs) gapMs = ms.coerceAtMost(LIMIT.toLong())
    }

    @Synchronized
    fun netChange() {
        netChg = (netChg + 1).coerceAtMost(LIMIT)
    }

    @Synchronized
    fun netKind(from: String, to: String) {
        netLog.add(from, to, System.currentTimeMillis())
    }

    @Synchronized
    fun probe(ms: Long) {
        probeMs = maxOf(probeMs, ms.coerceIn(0, LIMIT.toLong()))
    }

    @Synchronized
    fun take(force: Boolean = false, extra: String = ""): Snapshot? {
        val notable = under > 0 || reset > 0 || reconn > 0 || netChg > 0 || gapMs >= GAP_NOTE_MS || netLog.size() > 0
        if (!notable && !force) {
            stallMs = 0
            ttfbMs = 0
            gapMs = 0
            return null
        }
        val s = Snapshot(under, reset, silenceMs, underLocal, stallMs, reconn, why, ttfbMs, gapMs, netChg, extra,
            probeMs, netLog.take())
        clearLocked()
        return s
    }

    @Synchronized
    fun put(s: Snapshot) {
        under = (under + s.under).coerceAtMost(LIMIT)
        reset = (reset + s.reset).coerceAtMost(LIMIT)
        silenceMs = (silenceMs + s.silenceMs).coerceAtMost(LIMIT.toLong())
        underLocal = (underLocal + s.underLocal).coerceAtMost(LIMIT)
        stallMs = maxOf(stallMs, s.stallMs)
        reconn = (reconn + s.reconn).coerceAtMost(LIMIT)
        if (s.why.isNotEmpty()) why = s.why
        ttfbMs = maxOf(ttfbMs, s.ttfbMs)
        gapMs = maxOf(gapMs, s.gapMs)
        netChg = (netChg + s.netChg).coerceAtMost(LIMIT)
        probeMs = maxOf(probeMs, s.probeMs)
        netLog.restore(s.netLog)
    }

    @Synchronized
    fun clear() {
        clearLocked()
    }

    private fun clearLocked() {
        under = 0
        reset = 0
        silenceMs = 0
        underLocal = 0
        stallMs = 0
        reconn = 0
        why = ""
        ttfbMs = 0
        gapMs = 0
        netChg = 0
        probeMs = 0
        netLog.clear()
    }

    companion object {
        const val LIMIT = 100000
        const val GAP_NOTE_MS = 1000L
    }
}
