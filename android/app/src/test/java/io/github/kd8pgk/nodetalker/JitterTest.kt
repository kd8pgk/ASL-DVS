package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class JitterTest {
    @Test
    fun startsAtTheCapUntilItHasSeenEnoughFrames() {
        val j = JitterEst()
        for (i in 0 until 100) j.note(i * 20L)
        assertEquals(300, j.leadMs(300))
    }

    @Test
    fun aSteadyLinkSettlesAtTheFloor() {
        val j = JitterEst()
        for (i in 0 until 400) j.note(i * 20L)
        assertEquals(100, j.leadMs(300))
    }

    @Test
    fun aJitteryLinkStaysNearTheCap() {
        val j = JitterEst()
        var t = 0L
        var seed = 7L
        for (i in 0 until 400) {
            seed = (seed * 1664525L + 1013904223L) and 0xffffffffL
            t += 5 + (seed % 90)
            j.note(t)
        }
        assertTrue(j.leadMs(400) > 150)
        assertTrue(j.leadMs(400) <= 400)
    }

    @Test
    fun theCapIsNeverExceeded() {
        val j = JitterEst()
        var t = 0L
        for (i in 0 until 400) {
            t += if (i % 2 == 0) 0 else 400
            j.note(t)
        }
        assertEquals(250, j.leadMs(250))
    }

    @Test
    fun aLongSilenceIsNotCountedAsJitter() {
        val j = JitterEst()
        for (i in 0 until 300) j.note(i * 20L)
        j.note(300 * 20L + 60000)
        for (i in 301 until 400) j.note(60000 + i * 20L)
        assertEquals(100, j.leadMs(300))
    }

    @Test
    fun resetStartsAgain() {
        val j = JitterEst()
        for (i in 0 until 400) j.note(i * 20L)
        j.reset()
        assertEquals(300, j.leadMs(300))
    }

    @Test
    fun aCapBelowTheFloorIsKept() {
        val j = JitterEst()
        for (i in 0 until 400) j.note(i * 20L)
        assertEquals(80, j.leadMs(80))
    }

    @Test
    fun framesForHasAMinimum() {
        assertEquals(3, Adapt.framesFor(20))
        assertEquals(5, Adapt.framesFor(100))
        assertEquals(15, Adapt.framesFor(300))
    }

    @Test
    fun onlyQuietFramesAreDroppedOrPadded() {
        assertEquals(Adapt.PLAY, Adapt.step(false, 30, 5))
        assertEquals(Adapt.PLAY, Adapt.step(false, 0, 5))
        assertEquals(Adapt.DROP, Adapt.step(true, 30, 5))
        assertEquals(Adapt.PAD, Adapt.step(true, 1, 5))
        assertEquals(Adapt.PLAY, Adapt.step(true, 6, 5))
    }

    @Test
    fun quietMeansEveryPeakIsLow() {
        assertTrue(Adapt.quiet(ShortArray(160)))
        assertTrue(Adapt.quiet(ShortArray(160) { 200 }))
        assertTrue(!Adapt.quiet(ShortArray(160) { if (it == 70) 5000 else 0 }))
    }
}
