package io.github.kd8pgk.nodetalker

import kotlin.math.PI
import kotlin.math.log10
import kotlin.math.sin
import kotlin.math.sqrt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DecimatorTest {
    private fun gainDb(factor: Int, hz: Double): Double {
        val rate = 8000 * factor
        val d = Decimator(factor)
        var inSq = 0.0
        var outSq = 0.0
        var outN = 0
        val total = rate * 2
        for (i in 0 until total) {
            val x = sin(2 * PI * hz * i / rate)
            val y = d.push(x)
            if (i > rate / 2) inSq += x * x
            if (y != null && i > rate / 2) {
                outSq += y * y
                outN++
            }
        }
        val inRms = sqrt(inSq / (total - rate / 2))
        val outRms = sqrt(outSq / outN)
        return 20 * log10(outRms / inRms)
    }

    @Test
    fun givesOneOutputPerFactorInputs() {
        val d = Decimator(6)
        var n = 0
        for (i in 0 until 600) if (d.push(0.1) != null) n++
        assertEquals(100, n)
    }

    @Test
    fun passesTheSpeechBand() {
        assertTrue(gainDb(6, 1000.0) > -0.5)
        assertTrue(gainDb(6, 3000.0) > -1.0)
        assertTrue(gainDb(2, 1000.0) > -0.5)
    }

    @Test
    fun keepsAliasingDownAboveTheNewNyquist() {
        assertTrue(gainDb(6, 4600.0) < -40.0)
        assertTrue(gainDb(6, 6000.0) < -60.0)
        assertTrue(gainDb(2, 4600.0) < -40.0)
    }

    @Test
    fun passesDcAtUnity() {
        val d = Decimator(6)
        var last = 0.0
        for (i in 0 until 2000) d.push(1.0)?.let { last = it }
        assertEquals(1.0, last, 0.001)
    }
}
