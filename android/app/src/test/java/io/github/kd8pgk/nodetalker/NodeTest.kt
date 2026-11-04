package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeTest {

    @Test
    fun origin_brackets_an_ipv6_host_and_follows_the_scheme() {
        assertEquals("https://[::1]:8993", Node("a", "n", "::1", 8993, true).origin)
        assertEquals("http://node.local:8993", Node("a", "n", "node.local", 8993, false).origin)
    }

    @Test
    fun title_falls_back_to_the_host_when_unnamed() {
        assertEquals("10.0.0.5", Node("a", "", "10.0.0.5", 8993, false).title)
        assertEquals("pi", Node("a", "pi", "10.0.0.5", 8993, false).title)
    }

    @Test
    fun host_check_accepts_names_and_addresses_only() {
        listOf("node.local", "192.168.1.10", "fe80::1", "pi-node").forEach {
            assertTrue(it, Node.validHost(it))
        }
        listOf("", "bad host", "-x", "a/b", "http://x").forEach {
            assertFalse(it, Node.validHost(it))
        }
    }
}
