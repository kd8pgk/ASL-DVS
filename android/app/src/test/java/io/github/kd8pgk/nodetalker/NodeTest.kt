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

    @Test
    fun a_web_address_without_a_port_uses_the_scheme_default() {
        assertEquals(Triple("node.example.com", 443, true), Node.parseAddress("https://node.example.com"))
        assertEquals(Triple("node.example.com", 443, true), Node.parseAddress("  HTTPS://node.example.com/  "))
        assertEquals(Triple("192.168.1.5", 80, false), Node.parseAddress("http://192.168.1.5"))
    }

    @Test
    fun a_web_address_with_a_port_keeps_it() {
        assertEquals(Triple("pi.local", 8993, true), Node.parseAddress("https://pi.local:8993"))
        assertEquals(Triple("pi.local", 8993, false), Node.parseAddress("http://pi.local:8993/some/path?x=1#y"))
        assertEquals(Triple("::1", 9000, true), Node.parseAddress("https://[::1]:9000/"))
        assertEquals(Triple("fe80::1", 443, true), Node.parseAddress("https://[fe80::1]"))
    }

    @Test
    fun a_plain_address_leaves_the_port_and_scheme_to_the_form() {
        assertEquals(Triple("pi.local", null, null), Node.parseAddress("pi.local"))
        assertEquals(Triple("fe80::1", null, null), Node.parseAddress("fe80::1"))
        assertEquals(Triple("::1", null, null), Node.parseAddress("[::1]"))
    }

    @Test
    fun host_and_port_without_a_scheme_is_split() {
        assertEquals(Triple("pi.local", 8993, null), Node.parseAddress("pi.local:8993"))
        assertEquals(Triple("node.example.com", 443, null), Node.parseAddress("node.example.com:443"))
        assertEquals(Triple("::1", 9000, null), Node.parseAddress("[::1]:9000"))
    }

    @Test
    fun a_login_part_in_an_address_is_dropped() {
        assertEquals(Triple("pi.local", 8993, true), Node.parseAddress("https://user:pw@pi.local:8993"))
    }

    @Test
    fun a_bad_port_or_scheme_is_left_for_the_host_check_to_refuse() {
        assertFalse(Node.validHost(Node.parseAddress("pi.local:abc").first))
        assertFalse(Node.validHost(Node.parseAddress("ftp://pi.local").first))
        assertEquals(null, Node.parseAddress("pi.local:abc").second)
    }
}
