package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NetLogTest {

    @Test
    fun entry_names_the_change_and_the_clock_time() {
        val e = NetLog.entry("wifi", "cell", 0L)
        assertTrue(e, Regex("wifi>cell \\d{2}:\\d{2}:\\d{2}").matches(e))
    }

    @Test
    fun keeps_only_the_newest_entries() {
        val n = NetLog()
        repeat(NetLog.MAX + 3) { n.add("wifi", "cell", it * 1000L) }
        assertEquals(NetLog.MAX, n.size())
    }

    @Test
    fun take_empties_the_log_and_restore_puts_entries_back_first() {
        val n = NetLog()
        n.add("wifi", "cell", 0L)
        val first = n.take()
        assertEquals(1, first.size)
        assertEquals(0, n.size())
        n.add("cell", "wifi", 0L)
        n.restore(first)
        val again = n.take()
        assertEquals(2, again.size)
        assertTrue(again[0].startsWith("wifi>cell"))
        assertTrue(again[1].startsWith("cell>wifi"))
    }
}
