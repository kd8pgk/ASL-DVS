package io.github.kd8pgk.nodetalker

import kotlin.math.sin
import kotlin.math.sqrt

class Plc {
    private val hist = DoubleArray(HIST)
    private var filled = 0
    private var syn: DoubleArray? = null
    private var used = 0
    private var tried = false

    val concealing: Boolean
        get() = used > 0

    fun reset() {
        filled = 0
        syn = null
        used = 0
        tried = false
        hist.fill(0.0)
    }

    fun next(): ShortArray? {
        if (!tried) {
            tried = true
            syn = build()
        }
        val s = syn ?: return null
        if (used + FRAME > s.size) return null
        val out = ShortArray(FRAME) { i -> clip(s[used + i] * SCALE) }
        used += FRAME
        return out
    }

    fun accept(real: ShortArray): ShortArray {
        val out = if (used > 0) blend(real) else real
        push(real)
        syn = null
        used = 0
        tried = false
        return out
    }

    private fun push(f: ShortArray) {
        System.arraycopy(hist, f.size, hist, 0, HIST - f.size)
        for (i in f.indices) hist[HIST - f.size + i] = f[i] / SCALE
        filled = minOf(HIST, filled + f.size)
    }

    private fun blend(real: ShortArray): ShortArray {
        val s = syn
        val out = real.copyOf()
        val n = minOf(BLEND, real.size)
        for (i in 0 until n) {
            val w = (i + 1).toDouble() / (n + 1)
            val sv = if (s != null && used + i < s.size) s[used + i] * SCALE else 0.0
            out[i] = clip(sv * (1 - w) + real[i] * w)
        }
        return out
    }

    private fun build(): DoubleArray? {
        if (filled < MAX_LAG + WIN + 1) return null
        val n = HIST
        var e0 = 0.0
        for (i in n - WIN until n) e0 += hist[i] * hist[i]
        if (e0 / WIN < MIN_POWER) return null
        var best = 0.0
        var bestLag = 0
        for (lag in MIN_LAG..MAX_LAG) {
            var c = 0.0
            var e1 = 0.0
            for (i in n - WIN until n) {
                c += hist[i] * hist[i - lag]
                e1 += hist[i - lag] * hist[i - lag]
            }
            val r = if (e1 > 0) c / sqrt(e0 * e1) else 0.0
            if (r > best) {
                best = r
                bestLag = lag
            }
        }
        if (best < MIN_CORR || bestLag == 0) return null
        return DoubleArray(LEN) { i ->
            val gain = if (i < FADE_FROM) 1.0 else maxOf(0.0, 1.0 - (i - FADE_FROM).toDouble() / (LEN - FADE_FROM))
            hist[n - bestLag + (i % bestLag)] * gain
        }
    }

    private fun clip(v: Double): Short = v.coerceIn(-32768.0, 32767.0).toInt().toShort()

    companion object {
        const val FRAME = 160
        const val HIST = 480
        const val LEN = 480
        const val MIN_LAG = 40
        const val MAX_LAG = 120
        const val WIN = 80
        const val FADE_FROM = 80
        const val BLEND = 32
        const val SCALE = 32768.0
        const val MIN_POWER = 1e-5
        const val MIN_CORR = 0.5
    }
}

class Decimator(private val factor: Int, cutoffHz: Double = CUTOFF_HZ) {
    private val half = HALF_OUT * factor
    private val taps = 2 * half + 1
    private val h = DoubleArray(taps)
    private val hist = DoubleArray(taps)
    private var pos = 0
    private var count = 0

    init {
        val fc = cutoffHz / (OUT_RATE * factor)
        val beta = KAISER_BETA
        val i0b = bessel(beta)
        var sum = 0.0
        for (i in 0 until taps) {
            val t = (i - half).toDouble()
            val sinc = if (t == 0.0) 2 * fc else sin(2 * Math.PI * fc * t) / (Math.PI * t)
            val r = t / half
            val w = bessel(beta * sqrt(maxOf(0.0, 1 - r * r))) / i0b
            h[i] = sinc * w
            sum += h[i]
        }
        for (i in 0 until taps) h[i] /= sum
    }

    fun push(x: Double): Double? {
        hist[pos] = x
        pos = if (pos == taps - 1) 0 else pos + 1
        if (++count < factor) return null
        count = 0
        var acc = 0.0
        var j = if (pos == 0) taps - 1 else pos - 1
        for (k in 0 until taps) {
            acc += h[k] * hist[j]
            j = if (j == 0) taps - 1 else j - 1
        }
        return acc
    }

    private fun bessel(x: Double): Double {
        var sum = 1.0
        var term = 1.0
        val q = x * x / 4
        var k = 1
        while (k < 60) {
            term *= q / (k.toDouble() * k)
            sum += term
            if (term < 1e-12 * sum) break
            k++
        }
        return sum
    }

    companion object {
        const val OUT_RATE = 8000
        const val HALF_OUT = 16
        const val CUTOFF_HZ = 3500.0
        const val KAISER_BETA = 5.65
    }
}
