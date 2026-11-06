package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlayStatsTest {

    @Test
    fun a_quiet_stream_sends_nothing_unless_forced() {
        val s = PlayStats()
        s.probe(40)
        assertNull(s.take(false, ""))
        assertEquals(40L, s.take(true, "")!!.probeMs)
    }

    @Test
    fun the_slowest_probe_wins_until_taken() {
        val s = PlayStats()
        s.probe(40)
        s.probe(900)
        s.probe(120)
        assertEquals(900L, s.take(true, "")!!.probeMs)
        assertEquals(0L, s.take(true, "")!!.probeMs)
    }

    @Test
    fun a_network_change_is_logged_and_counts_as_notable() {
        val s = PlayStats()
        s.netKind("wifi", "cell")
        val snap = s.take(false, "")!!
        assertEquals(1, snap.netLog.size)
        assertTrue(snap.json().contains("\"net_log\":\"wifi>cell "))
        assertNull(s.take(false, ""))
    }

    @Test
    fun a_failed_send_puts_the_log_and_probe_back() {
        val s = PlayStats()
        s.netKind("cell", "wifi")
        s.probe(300)
        val snap = s.take(true, "")!!
        s.put(snap)
        val again = s.take(true, "")!!
        assertEquals(1, again.netLog.size)
        assertEquals(300L, again.probeMs)
    }
}
