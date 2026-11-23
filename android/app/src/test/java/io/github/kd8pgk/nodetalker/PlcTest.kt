package io.github.kd8pgk.nodetalker

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import kotlin.math.sqrt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlcTest {
    private fun wave(i: Int): Double = 9000 * sin(2 * PI * 130 * i / 8000) + 3500 * sin(2 * PI * 260 * i / 8000 + 0.7)

    private fun frames(from: Int, count: Int): List<ShortArray> =
        List(count) { k -> ShortArray(160) { i -> wave(from + k * 160 + i).toInt().toShort() } }

    @Test
    fun continuesAVoicedSoundAndFadesOut() {
        val plc = Plc()
        frames(0, 4).forEach { plc.accept(it) }
        val out = ArrayList<Short>()
        for (k in 0 until 3) out.addAll(plc.next()!!.toList())
        var c = 0.0
        var a = 0.0
        var b = 0.0
        for (i in 0 until 160) {
            val ref = wave(640 + i)
            c += out[i] * ref
            a += out[i].toDouble() * out[i]
            b += ref * ref
        }
        assertTrue(c / sqrt(a * b) > 0.95)
        var tail = 0
        for (i in 440 until 480) tail = maxOf(tail, abs(out[i].toInt()))
        assertTrue(tail < 1800)
        assertNull(plc.next())
    }

    @Test
    fun startsWhereTheSoundStopped() {
        val plc = Plc()
        val real = frames(0, 4)
        real.forEach { plc.accept(it) }
        val first = plc.next()!!
        assertTrue(abs(first[0] - real.last()[159]) < 2500)
    }

    @Test
    fun makesNothingFromSilenceOrNoise() {
        val quiet = Plc()
        repeat(4) { quiet.accept(ShortArray(160)) }
        assertNull(quiet.next())
        val noise = Plc()
        var seed = 12345L
        repeat(4) {
            noise.accept(ShortArray(160) {
                seed = (seed * 1664525L + 1013904223L) and 0xffffffffL
                ((seed / 4294967296.0 - 0.5) * 12000).toInt().toShort()
            })
        }
        assertNull(noise.next())
    }

    @Test
    fun needsEnoughHistory() {
        val plc = Plc()
        plc.accept(frames(0, 1)[0])
        assertNull(plc.next())
    }

    @Test
    fun blendsTheFirstFrameAfterAGap() {
        val plc = Plc()
        frames(0, 4).forEach { plc.accept(it) }
        assertNotNull(plc.next())
        assertTrue(plc.concealing)
        val real = frames(800, 1)[0]
        val out = plc.accept(real)
        assertEquals(160, out.size)
        assertTrue(!plc.concealing)
        assertTrue(out[0] != real[0] || out[1] != real[1])
        for (i in 40 until 160) assertEquals(real[i], out[i])
    }

    @Test
    fun aFrameThatIsNotAfterAGapIsUntouched() {
        val plc = Plc()
        val real = frames(0, 1)[0]
        val out = plc.accept(real)
        for (i in 0 until 160) assertEquals(real[i], out[i])
    }

    @Test
    fun resetForgetsTheHistory() {
        val plc = Plc()
        frames(0, 4).forEach { plc.accept(it) }
        plc.reset()
        assertNull(plc.next())
    }
}
