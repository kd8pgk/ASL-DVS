package io.github.kd8pgk.nodetalker

import kotlin.math.PI
import kotlin.math.abs
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

        fun highPass(rate: Int, hz: Double, q: Double = Q_BUTTER): Biquad {
            val w = 2 * PI * hz / rate
            val c = cos(w)
            val al = sin(w) / (2 * q)
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
    private val holdSamples = (0.08 * rate).toInt()
    private val upK = 1 - exp(-1.0 / (0.002 * rate))
    private val downK = 1 - exp(-1.0 / (0.02 * rate))
    private val decay = 3.0 / rate
    private val d1 = Biquad.highPass(rate, 300.0, 0.5412)
    private val d2 = Biquad.highPass(rate, 300.0, 1.3066)
    private var ms = 0.0
    private var speech = -40.0
    private var open = false
    private var hold = 0
    private var gain = 0.0

    fun run(x: Double): Double {
        val d = d2.run(d1.run(x))
        ms += (d * d - ms) * rmsK
        val db = 10 * log10(ms + 1e-12)
        speech = if (db > speech) db else speech - decay
        val openDb = (speech - 20.0).coerceIn(-58.0, -40.0)
        val closeDb = openDb - 6.0
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


class MicDyn(private val hp: Boolean, private val eq: Boolean, private val gateLevel: Int, private val lev: Boolean, rate: Int = 8000) {
    private val hp250 = Biquad.highPass(rate, 250.0, 0.707)
    private val hp300 = Biquad.highPass(rate, 300.0, 0.707)
    private val presence = Biquad.peaking(rate, 2500.0, 4.0, 1.0)
    private val gateOpen = if (gateLevel == 2) -35.0 else -45.0
    private val gateFloor = if (gateLevel == 2) 0.03 else 0.18
    private var env = 0.0
    private var gg = 1.0
    private var hold = 0
    private var open = false
    private var rms = 0.0
    private var cg = 1.0
    private var lg = 1.0
    var minLimiter = 1.0
        private set
    var minGate = 1.0
        private set

    fun run(x: Double): Double {
        var v = x
        if (hp && !eq) v = hp250.run(v)
        if (eq) v = presence.run(hp300.run(v))
        if (gateLevel != 0) {
            val a = abs(v)
            env = if (a > env) env + (a - env) * 0.7 else env * 0.9975
            val db = if (env > 1e-6) 20 * log10(env) else -120.0
            if (db > gateOpen) {
                open = true
                hold = 2000
            } else if (db < gateOpen - 6) {
                if (hold > 0) hold-- else open = false
            }
            val want = if (open) 1.0 else gateFloor
            gg += (want - gg) * (if (want > gg) 0.06 else 0.0016)
            v *= gg
        }
        if (lev) {
            rms += (v * v - rms) * 0.004
            val lvl = if (rms > 1e-10) 10 * log10(rms) else -100.0
            val over = lvl + 24
            val want = 10.0.pow(((if (over > 0) -over * (2.0 / 3.0) else 0.0) + 9) / 20)
            cg += (want - cg) * (if (want < cg) 0.0125 else 0.000625)
            v *= cg
            val b = abs(v)
            if (b * lg > 0.89) lg = 0.89 / b else lg += (1 - lg) * 0.0025
            v *= lg
        }
        if (lg < minLimiter) minLimiter = lg
        if (gg < minGate) minGate = gg
        return v
    }

    fun resetFrame() {
        minLimiter = 1.0
        minGate = 1.0
    }
}

class FrameStats {
    private var prev = 0.0
    private var prev2 = 0.0

    fun of(f: ShortArray): DoubleArray {
        var ss = 0.0
        var pk = 0.0
        var x1 = 0.0
        var x2 = 0.0
        for (s in f) {
            val v = s / 32768.0
            ss += v * v
            val a = abs(v)
            if (a > pk) pk = a
            x1 += v * prev
            x2 += v * prev2
            prev2 = prev
            prev = v
        }
        return doubleArrayOf(
            if (ss > 0) 10 * log10(ss / f.size) else -120.0,
            if (pk > 0) 20 * log10(pk) else -120.0,
            if (ss > 0) x1 / ss else 1.0,
            if (ss > 0) x2 / ss else 1.0,
        )
    }
}

class Hum {
    private val ring = DoubleArray(N)
    private val tmp = DoubleArray(N)
    private var pos = 0

    fun push(f: ShortArray) {
        for (v in f) {
            ring[pos] = v / 32768.0
            pos = (pos + 1) % N
        }
    }

    fun db(): Double {
        for (i in 0 until N) tmp[i] = ring[(pos + i) % N] * WINDOW[i]
        var lo = 0.0
        var hi = 0.0
        for (k in 4..217) {
            var re = 0.0
            var im = 0.0
            for (i in 0 until N) {
                val a = (k * i) % N
                re += tmp[i] * COS[a]
                im -= tmp[i] * SIN[a]
            }
            val p = re * re + im * im
            if (k < 20) lo += p else hi += p
        }
        if (hi <= 1e-9) return Double.NaN
        return (10 * log10(maxOf(lo, hi * 1e-6) / hi)).coerceIn(-60.0, 20.0)
    }

    companion object {
        const val N = 512
        private val WINDOW = DoubleArray(N) { 0.5 - 0.5 * cos(2 * PI * it / N) }
        private val COS = DoubleArray(N) { cos(2 * PI * it / N) }
        private val SIN = DoubleArray(N) { sin(2 * PI * it / N) }
    }
}
