package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SlowTest {
    @Test
    fun meterTurnsSlowOnDialUpAndBack() {
        val m = Meter()
        repeat(3) { m.transfer(20000, 4000) }
        assertTrue(m.slow)
        m.transfer(500000, 1000)
        assertTrue(m.slow)
        m.transfer(500000, 1000)
        assertFalse(m.slow)
    }

    @Test
    fun longFirstByteTurnsSlowOn() {
        val m = Meter()
        m.firstByte(4000)
        assertTrue(m.slow)
    }

    @Test
    fun modeOverridesMeter() {
        assertTrue(Slow.isActive(SlowMode.ON, false))
        assertFalse(Slow.isActive(SlowMode.OFF, true))
        assertTrue(Slow.isActive(SlowMode.AUTO, true))
    }

    @Test
    fun imagesGoInViewingOrder() {
        val layout = Layout(800.0, 1000.0, listOf(
            Spot("banner", -900.0, 100.0, 800.0, 200.0),
            Spot("ad", 100.0, 880.0, 120.0, 600.0),
            Spot("icon", 10.0, 400.0, 32.0, 32.0),
            Spot("p1", 50.0, 200.0, 600.0, 500.0),
            Spot("p2", 600.0, 200.0, 600.0, 500.0),
            Spot("p3", 1200.0, 200.0, 600.0, 500.0),
        ))
        var queue = listOf("banner", "ad", "icon", "p3", "p2", "p1", "unknown").mapIndexed { i, u -> Waiting(u, i) }
        val order = ArrayList<String>()
        while (queue.isNotEmpty()) {
            val next = Slow.pickNext(queue, layout)!!
            order.add(next.url)
            queue = queue - next
        }
        assertEquals(listOf("p1", "p2", "p3", "banner", "unknown", "ad", "icon"), order)
    }

    @Test
    fun scrollingMovesOnScreenFirst() {
        val items = (1..7).map { Spot("p$it", (it - 7) * 600.0 + 100, 200.0, 600.0, 500.0) }
        val queue = items.mapIndexed { i, s -> Waiting(s.src, i) }
        assertEquals("p7", Slow.pickNext(queue, Layout(800.0, 1000.0, items))!!.url)
    }

    @Test
    fun failedPanelGoesLast() {
        val items = listOf(Spot("a", 10.0, 0.0, 900.0, 500.0), Spot("b", 900.0, 0.0, 900.0, 500.0))
        val queue = listOf(Waiting("a", 0, late = true), Waiting("b", 1))
        assertEquals("b", Slow.pickNext(queue, Layout(800.0, 1000.0, items))!!.url)
    }

    @Test
    fun noLayoutKeepsPageOrder() {
        assertEquals("y", Slow.pickNext(listOf(Waiting("x", 2), Waiting("y", 1)), null)!!.url)
    }

    @Test
    fun rangesAndBackoff() {
        assertEquals(Range(100, 199, 400), Slow.parseContentRange("bytes 100-199/400"))
        assertEquals(Range(0, 9, 0), Slow.parseContentRange("bytes 0-9/*"))
        assertNull(Slow.parseContentRange("garbage"))
        assertEquals(listOf(2000L, 4000L, 8000L, 16000L, 32000L, 32000L), (1..6).map { Slow.backoffMs(it) })
    }

    @Test
    fun nextLinkSameSiteOnly() {
        val page = "https://comic.test/strip/5"
        assertEquals("https://comic.test/strip/6", Slow.pickNextLink(listOf(Link("next", "https://comic.test/strip/6", "")), page))
        assertEquals("https://comic.test/strip/6", Slow.pickNextLink(listOf(Link("", "/strip/6", "Next ›")), page))
        assertEquals("", Slow.pickNextLink(listOf(Link("next", "https://ads.test/x", "")), page))
        assertEquals("", Slow.pickNextLink(listOf(Link("", "https://comic.test/strip/4", "Previous")), page))
    }

    @Test
    fun imageAddressesInOrder() {
        val html = "<img src=\"/a.png\"><p><img alt=x src='b.jpg'><img src=https://cdn.test/c.webp><img src=\"data:x\"><img src=\"/a.png\">"
        assertEquals(listOf("https://comic.test/a.png", "https://comic.test/s/b.jpg", "https://cdn.test/c.webp"), Slow.imageUrlsIn(html, "https://comic.test/s/1"))
    }

    @Test
    fun extrasRecognised() {
        assertTrue(Slow.isFont("https://x.test/f.woff2?v=1"))
        assertFalse(Slow.isFont("https://x.test/a.png"))
        assertTrue(Slow.isPrefetch(mapOf("Sec-Purpose" to "prefetch")))
        assertTrue(Slow.isPing(mapOf("Ping-To" to "https://x.test/")))
        assertEquals("4.9 KB/s", Slow.rateLabel(5000.0))
    }
}
