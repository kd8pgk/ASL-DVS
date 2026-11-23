package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class RouteTest {
    private fun home(id: String = "n1", away: String = "node.example.com") =
        Node(id, "Pi", "192.168.1.50", 8993, true, "pin", away)

    @Test
    fun aNodeWithoutAnAwayAddressIsNeverRerouted() {
        val n = Node("a", "Pi", "192.168.1.50", 8993, false)
        assertFalse(n.hasAway)
        assertSame(n, NodeRoute.decide(n, false))
        assertSame(n, NodeRoute.pick(n, 0L) { false })
    }

    @Test
    fun theHomeAddressIsKeptWhenItAnswers() {
        val n = home()
        assertSame(n, NodeRoute.decide(n, true))
    }

    @Test
    fun theAwayAddressIsUsedWhenHomeDoesNotAnswer() {
        val n = NodeRoute.decide(home(), false)
        assertEquals("node.example.com", n.host)
        assertEquals(443, n.port)
        assertTrue(n.https)
        assertTrue(n.viaAway)
        assertEquals("", n.pin)
        assertEquals("https://node.example.com:443", n.origin)
    }

    @Test
    fun aRoutedCopyHasNoAwayAddressOfItsOwn() {
        assertFalse(home().useAway().hasAway)
    }

    @Test
    fun theAnswerIsKeptForAWhile() {
        var probes = 0
        val n = home("keep")
        NodeRoute.forget("keep")
        val first = NodeRoute.pick(n, 1000L) { probes++; false }
        val second = NodeRoute.pick(n, 1000L + NodeRoute.KEEP_MS - 1) { probes++; true }
        assertEquals(1, probes)
        assertTrue(first.viaAway)
        assertTrue(second.viaAway)
        val third = NodeRoute.pick(n, 1000L + NodeRoute.KEEP_MS + 1) { probes++; true }
        assertEquals(2, probes)
        assertFalse(third.viaAway)
    }

    @Test
    fun forgettingMakesTheNextCallAskAgain() {
        var probes = 0
        val n = home("forget")
        NodeRoute.forget("forget")
        NodeRoute.pick(n, 0L) { probes++; true }
        NodeRoute.forget("forget")
        NodeRoute.pick(n, 1L) { probes++; true }
        assertEquals(2, probes)
    }

    @Test
    fun eachNodeKeepsItsOwnAnswer() {
        val a = home("a1")
        val b = home("b1")
        NodeRoute.forget("a1")
        NodeRoute.forget("b1")
        assertTrue(NodeRoute.pick(a, 0L) { false }.viaAway)
        assertFalse(NodeRoute.pick(b, 0L) { true }.viaAway)
    }

    @Test
    fun anInvalidAwayAddressIsIgnored() {
        assertFalse(home(away = "bad host").hasAway)
        assertFalse(Node("a", "Pi", "h.local", 8993, true, "", "x.example.com", 0).hasAway)
        assertFalse(Node("a", "Pi", "h.local", 8993, true, "", "x.example.com", 70000).hasAway)
    }

    @Test
    fun theAwayAddressIsShownWithoutItsStandardPort() {
        assertEquals("https://node.example.com", home().awayText)
        assertEquals("https://node.example.com:8443", Node("a", "n", "h", 1, true, "", "node.example.com", 8443).awayText)
        assertEquals("http://node.example.com", Node("a", "n", "h", 1, true, "", "node.example.com", 80, false).awayText)
        assertEquals("", Node("a", "n", "h", 1, true).awayText)
    }
}

class AwayLearnTest {
    private fun node(host: String = "", auto: Boolean = true, port: Int = 443) =
        Node("n", "Pi", "192.168.1.50", 8993, true, "", host, port, true, auto)

    @Test
    fun anHttpsAddressFromTheNodeIsUsed() {
        assertEquals(Triple("node.example.com", 443, true), AwayLearn.candidate("https://node.example.com", true))
        assertEquals(Triple("calm-river-1.trycloudflare.com", 443, true), AwayLearn.candidate("https://calm-river-1.trycloudflare.com", true))
    }

    @Test
    fun nothingIsLearnedWhileTheInternetIsOffOrTheAddressIsOdd() {
        assertNull(AwayLearn.candidate("https://node.example.com", false))
        assertNull(AwayLearn.candidate("", true))
        assertNull(AwayLearn.candidate("http://node.example.com", true))
        assertNull(AwayLearn.candidate("https://bad host", true))
        assertNull(AwayLearn.candidate("ftp://node.example.com", true))
    }

    @Test
    fun aLearnedAddressIsStored() {
        val changed = AwayLearn.apply(node(), Triple("node.example.com", 443, true))!!
        assertEquals("node.example.com", changed.awayHost)
        assertTrue(changed.awayAuto)
    }

    @Test
    fun aNewQuickAddressReplacesTheOldOne() {
        val changed = AwayLearn.apply(node("old-one.trycloudflare.com"), Triple("new-one.trycloudflare.com", 443, true))!!
        assertEquals("new-one.trycloudflare.com", changed.awayHost)
    }

    @Test
    fun theSameAddressChangesNothing() {
        assertNull(AwayLearn.apply(node("node.example.com"), Triple("NODE.example.com", 443, true)))
    }

    @Test
    fun anAddressTypedByHandIsNeverOverwritten() {
        assertNull(AwayLearn.apply(node("mine.example.com", auto = false), Triple("node.example.com", 443, true)))
    }

    @Test
    fun aRoutedCopyIsNeverUpdated() {
        assertNull(AwayLearn.apply(node("a.example.com").copy(viaAway = true), Triple("b.example.com", 443, true)))
    }

    @Test
    fun nothingFoundChangesNothing() {
        assertNull(AwayLearn.apply(node(), null))
    }
}
