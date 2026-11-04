package io.github.kd8pgk.nodetalker

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

class Biquad private constructor(
    private val b0: Double,
    private val b1: Double,
    private val b2: Double,
    private val a1: Double,
    private val a2: Double,
) {
    private var x1 = 0.0
    private var x2 = 0.0
    private var y1 = 0.0
    private var y2 = 0.0

    fun run(x: Double): Double {
        val y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y
        return y
    }

    companion object {
        private const val Q_BUTTER = 0.7071067811865476

        private fun norm(b0: Double, b1: Double, b2: Double, a0: Double, a1: Double, a2: Double) =
            Biquad(b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)

        fun highPass(rate: Int, hz: Double): Biquad {
            val w = 2 * PI * hz / rate
            val c = cos(w)
            val al = sin(w) / (2 * Q_BUTTER)
            return norm((1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + al, -2 * c, 1 - al)
        }

        fun lowPass(rate: Int, hz: Double): Biquad {
            val w = 2 * PI * hz / rate
            val c = cos(w)
            val al = sin(w) / (2 * Q_BUTTER)
            return norm((1 - c) / 2, 1 - c, (1 - c) / 2, 1 + al, -2 * c, 1 - al)
        }

        fun peaking(rate: Int, hz: Double, gainDb: Double, q: Double): Biquad {
            val a = 10.0.pow(gainDb / 40)
            val w = 2 * PI * hz / rate
            val c = cos(w)
            val al = sin(w) / (2 * q)
            return norm(1 + al * a, -2 * c, 1 - al * a, 1 + al / a, -2 * c, 1 - al / a)
        }
    }
}

class Fir(rate: Int, cutoffHz: Double, private val taps: Int) {
    private val h: DoubleArray
    private val hist = DoubleArray(taps)
    private var pos = 0

    init {
        val m = taps - 1
        val fc = cutoffHz / rate
        h = DoubleArray(taps) { i ->
            val n = i - m / 2.0
            val sinc = if (n == 0.0) 2 * fc else sin(2 * PI * fc * n) / (PI * n)
            sinc * (0.54 - 0.46 * cos(2 * PI * i / m))
        }
        val sum = h.sum()
        for (i in h.indices) h[i] /= sum
    }

    fun run(x: Double): Double {
        hist[pos] = x
        var acc = 0.0
        var j = pos
        for (k in 0 until taps) {
            acc += h[k] * hist[j]
            j = if (j == 0) taps - 1 else j - 1
        }
        pos = if (pos == taps - 1) 0 else pos + 1
        return acc
    }
}

class Gate(rate: Int) {
    private val rmsK = 1 - exp(-1.0 / (0.02 * rate))
    private val openDb = -40.0
    private val closeDb = -46.0
    private val holdSamples = (0.08 * rate).toInt()
    private val upK = 1 - exp(-1.0 / (0.002 * rate))
    private val downK = 1 - exp(-1.0 / (0.02 * rate))
    private var ms = 0.0
    private var open = false
    private var hold = 0
    private var gain = 0.0

    fun run(x: Double): Double {
        ms += (x * x - ms) * rmsK
        val db = 10 * log10(ms + 1e-12)
        if (!open) {
            if (db > openDb) {
                open = true
                hold = holdSamples
            }
        } else if (db > closeDb) {
            hold = holdSamples
        } else if (--hold <= 0) {
            open = false
        }
        val target = if (open) 1.0 else 0.0
        gain += (target - gain) * (if (target > gain) upK else downK)
        return x * gain
    }
}

class VoiceChain(rate: Int) {
    private val high = Biquad.highPass(rate, 150.0)
    private val low = Biquad.lowPass(rate, 3400.0)
    private val presence = Biquad.peaking(rate, 2500.0, 3.0, 1.2)
    private val gate = Gate(rate)

    fun run(x: Double): Double = gate.run(presence.run(low.run(high.run(x))))

    fun process(src: ShortArray): ShortArray {
        val out = ShortArray(src.size)
        for (i in src.indices) {
            out[i] = (run(src[i] / 32768.0) * 32768.0).toInt().coerceIn(-32768, 32767).toShort()
        }
        return out
    }
}
