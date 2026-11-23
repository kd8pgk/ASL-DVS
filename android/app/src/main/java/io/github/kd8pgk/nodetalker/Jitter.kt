package io.github.kd8pgk.nodetalker

import kotlin.math.abs
import kotlin.math.roundToInt

class JitterEst {
    private var last = 0L
    private var j = 0.0
    private var n = 0

    @Synchronized
    fun note(nowMs: Long) {
        if (last != 0L) {
            val gap = nowMs - last
            if (gap < GAP_MAX_MS) {
                j += (abs(gap - FRAME_MS) - j) / SMOOTH
                n++
            }
        }
        last = nowMs
    }

    @Synchronized
    fun reset() {
        last = 0L
        j = 0.0
        n = 0
    }

    @Synchronized
    fun leadMs(capMs: Int): Int {
        if (n < WARM) return capMs
        val want = (BASE_MS + 4 * j).roundToInt()
        return want.coerceIn(minOf(FLOOR_MS, capMs), capMs)
    }

    companion object {
        const val FRAME_MS = 20
        const val GAP_MAX_MS = 1500
        const val SMOOTH = 16.0
        const val WARM = 150
        const val BASE_MS = 40
        const val FLOOR_MS = 100
    }
}

object Adapt {
    const val DROP = -1
    const val PLAY = 0
    const val PAD = 1
    const val QUIET_PEAK = 300

    fun framesFor(leadMs: Int): Int = (leadMs / JitterEst.FRAME_MS).coerceAtLeast(3)

    fun quiet(f: ShortArray): Boolean {
        for (v in f) if (abs(v.toInt()) > QUIET_PEAK) return false
        return true
    }

    fun step(quiet: Boolean, queued: Int, want: Int): Int {
        if (!quiet) return PLAY
        if (queued > want + 4) return DROP
        if (queued < want - 2) return PAD
        return PLAY
    }
}
