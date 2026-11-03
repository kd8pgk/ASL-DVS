package io.github.kd8pgk.nodetalker

import android.util.Base64
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt

class Spectrum {
    private val ring = FloatArray(N)
    private var pos = 0
    private val re = FloatArray(N)
    private val im = FloatArray(N)
    private val smooth = FloatArray(N / 2)
    private val bars = ByteArray(BARS)
    private var peak = 0f

    fun push(f: ShortArray) {
        for (v in f) {
            ring[pos] = v / 32768f
            pos = (pos + 1) % N
        }
    }

    fun encode(): String {
        var pk = 0f
        for (i in 0 until N) {
            val v = ring[(pos + i) % N]
            pk = max(pk, abs(v))
            re[i] = v * WINDOW[i]
            im[i] = 0f
        }
        peak = pk
        fft()
        for (k in 0 until N / 2) {
            val mag = sqrt(re[k] * re[k] + im[k] * im[k]) / N
            smooth[k] = SMOOTHING * smooth[k] + (1 - SMOOTHING) * mag
        }
        val per = N / 2 / BARS
        for (b in 0 until BARS) {
            var m = 0f
            for (j in 0 until per) m = max(m, smooth[b * per + j])
            val db = if (m > 0f) 20 * log10(m.toDouble()) else -200.0
            bars[b] = (((db - DB_LO) / (DB_HI - DB_LO)) * 255).coerceIn(0.0, 255.0).toInt().toByte()
        }
        return Base64.encodeToString(bars, Base64.NO_WRAP)
    }

    fun peakDb(): Double = if (peak <= 0f) -120.0 else 20 * log10(peak.toDouble())

    private fun fft() {
        for (i in 0 until N) {
            val j = REV[i]
            if (j > i) {
                val tr = re[i]
                re[i] = re[j]
                re[j] = tr
            }
        }
        var len = 2
        while (len <= N) {
            val half = len / 2
            val step = N / len
            var i = 0
            while (i < N) {
                for (k in 0 until half) {
                    val wr = COS[k * step]
                    val wi = -SIN[k * step]
                    val a = i + k
                    val b = a + half
                    val tr = re[b] * wr - im[b] * wi
                    val ti = re[b] * wi + im[b] * wr
                    re[b] = re[a] - tr
                    im[b] = im[a] - ti
                    re[a] += tr
                    im[a] += ti
                }
                i += len
            }
            len = len shl 1
        }
    }

    companion object {
        const val N = 512
        const val BARS = 128
        const val SMOOTHING = 0.5f
        const val DB_LO = -100.0
        const val DB_HI = -25.0
        private val WINDOW = FloatArray(N) { i ->
            (0.42 - 0.5 * cos(2 * PI * i / N) + 0.08 * cos(4 * PI * i / N)).toFloat()
        }
        private val COS = FloatArray(N / 2) { k -> cos(2 * PI * k / N).toFloat() }
        private val SIN = FloatArray(N / 2) { k -> sin(2 * PI * k / N).toFloat() }
        private val REV = IntArray(N) { i ->
            var x = i
            var r = 0
            for (b in 0 until 9) {
                r = (r shl 1) or (x and 1)
                x = x shr 1
            }
            r
        }
    }
}
