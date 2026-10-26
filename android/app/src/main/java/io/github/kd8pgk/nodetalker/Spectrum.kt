package io.github.kd8pgk.nodetalker

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

class Spectrum {
    private val lock = Any()
    private val ring = FloatArray(SIZE)
    private var write = 0
    private var fedSinceUpdate = 0
    private var lastUpdateMs = -1L
    private val smooth = DoubleArray(BINS)
    private val re = DoubleArray(SIZE)
    private val im = DoubleArray(SIZE)
    private val window = FloatArray(SIZE)
    private var holdAt = 0L

    @Volatile var level = -120.0
        private set

    @Volatile var hold = -120.0
        private set

    fun feed(frame: ShortArray) {
        synchronized(lock) {
            for (v in frame) put(v / 32768f)
            fedSinceUpdate += frame.size
        }
    }

    fun clear() {
        synchronized(lock) {
            ring.fill(0f)
            write = 0
            fedSinceUpdate = 0
            lastUpdateMs = -1L
        }
        smooth.fill(0.0)
        level = -120.0
        hold = -120.0
    }

    fun update(nowMs: Long, bins: ByteArray?) {
        synchronized(lock) {
            if (lastUpdateMs >= 0) {
                val missing = ((nowMs - lastUpdateMs) * RATE / 1000).toInt() - fedSinceUpdate
                if (missing > FRAME) repeat(min(missing, SIZE)) { put(0f) }
            }
            lastUpdateMs = nowMs
            fedSinceUpdate = 0
            for (i in 0 until SIZE) window[i] = ring[(write + i) % SIZE]
        }
        var pk = 0f
        for (v in window) pk = max(pk, abs(v))
        val db = if (pk > 0f) max(-120.0, 20 * log10(pk.toDouble())) else -120.0
        level = max(db, level - DECAY_DB)
        if (level >= hold || nowMs - holdAt > HOLD_MS) {
            hold = level
            holdAt = nowMs
        }
        if (bins != null) analyse(bins)
    }

    private fun put(v: Float) {
        ring[write] = v
        write = (write + 1) % SIZE
    }

    private fun analyse(bins: ByteArray) {
        for (i in 0 until SIZE) {
            re[i] = window[i] * BLACKMAN[i]
            im[i] = 0.0
        }
        fft(re, im)
        for (k in 0 until BINS) {
            val mag = sqrt(re[k] * re[k] + im[k] * im[k]) / SIZE
            smooth[k] = SMOOTHING * smooth[k] + (1 - SMOOTHING) * mag
            val db = if (smooth[k] > 0.0) 20 * log10(smooth[k]) else -1000.0
            bins[k] = ((db - DB_LO) / (DB_HI - DB_LO) * 255).toInt().coerceIn(0, 255).toByte()
        }
    }

    companion object {
        const val RATE = 8000
        const val FRAME = 160
        const val SIZE = 512
        const val BINS = SIZE / 2
        const val DB_LO = -100.0
        const val DB_HI = -25.0
        const val SMOOTHING = 0.5
        const val DECAY_DB = 1.5
        const val HOLD_MS = 1000L

        private val BLACKMAN = DoubleArray(SIZE) { n ->
            0.42 - 0.5 * cos(2 * PI * n / SIZE) + 0.08 * cos(4 * PI * n / SIZE)
        }

        private val STOPS = arrayOf(
            intArrayOf(0, 10, 16, 22), intArrayOf(70, 18, 52, 96), intArrayOf(140, 34, 195, 166),
            intArrayOf(200, 244, 192, 78), intArrayOf(255, 255, 92, 92),
        )

        val PALETTE = IntArray(256) { i ->
            var k = 0
            while (k < STOPS.size - 2 && i > STOPS[k + 1][0]) k++
            val a = STOPS[k]
            val b = STOPS[k + 1]
            val t = ((i - a[0]).toDouble() / (b[0] - a[0])).coerceIn(0.0, 1.0)
            val c = IntArray(3) { (a[it + 1] + (b[it + 1] - a[it + 1]) * t).roundToInt().coerceIn(0, 255) }
            (0xFF shl 24) or (c[0] shl 16) or (c[1] shl 8) or c[2]
        }

        fun dbPct(db: Double): Double = ((db + 60) / 60 * 100).coerceIn(0.0, 100.0)

        fun fmtDb(db: Double): String = if (db <= -119) "-inf" else "${db.roundToInt()} dBFS"

        private fun fft(re: DoubleArray, im: DoubleArray) {
            val n = re.size
            var j = 0
            for (i in 1 until n) {
                var bit = n shr 1
                while (j and bit != 0) {
                    j = j xor bit
                    bit = bit shr 1
                }
                j = j xor bit
                if (i < j) {
                    val tr = re[i]; re[i] = re[j]; re[j] = tr
                    val ti = im[i]; im[i] = im[j]; im[j] = ti
                }
            }
            var len = 2
            while (len <= n) {
                val ang = -2 * PI / len
                val wr = cos(ang)
                val wi = sin(ang)
                var i = 0
                while (i < n) {
                    var cr = 1.0
                    var ci = 0.0
                    for (k in 0 until len / 2) {
                        val ur = re[i + k]
                        val ui = im[i + k]
                        val vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci
                        val vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr
                        re[i + k] = ur + vr
                        im[i + k] = ui + vi
                        re[i + k + len / 2] = ur - vr
                        im[i + k + len / 2] = ui - vi
                        val nr = cr * wr - ci * wi
                        ci = cr * wi + ci * wr
                        cr = nr
                    }
                    i += len
                }
                len = len shl 1
            }
        }
    }
}
