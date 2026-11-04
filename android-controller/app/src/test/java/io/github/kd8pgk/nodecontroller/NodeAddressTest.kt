package io.github.kd8pgk.nodecontroller

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeAddressTest {
    @Test
    fun bareHostUsesHttpAndDashboardPort() {
        assertEquals(NodeAddress("192.168.1.20", 8989, false), NodeAddress.parse("192.168.1.20"))
    }

    @Test
    fun hostWithPort() {
        assertEquals(NodeAddress("node.local", 8990, false), NodeAddress.parse("node.local:8990"))
    }

    @Test
    fun httpUrlKeepsPortAndIgnoresPath() {
        assertEquals(NodeAddress("node.local", 8989, false), NodeAddress.parse("http://node.local:8989/"))
        assertEquals(NodeAddress("node.local", 8989, false), NodeAddress.parse("http://node.local/"))
    }

    @Test
    fun httpsUrlDefaultsToPort443() {
        assertEquals(NodeAddress("node.example.net", 443, true), NodeAddress.parse("https://node.example.net"))
        assertEquals(NodeAddress("node.example.net", 8443, true), NodeAddress.parse("https://node.example.net:8443"))
    }

    @Test
    fun ipv6NeedsBrackets() {
        assertEquals(NodeAddress("fe80::1", 8989, false), NodeAddress.parse("[fe80::1]"))
        assertEquals(NodeAddress("fe80::1", 8991, false), NodeAddress.parse("[fe80::1]:8991"))
        assertEquals(NodeAddress("fe80::1", 8989, false), NodeAddress.parse("fe80::1"))
    }

    @Test
    fun surroundingSpacesAndCaseAreAccepted() {
        assertEquals(NodeAddress("node.local", 8989, false), NodeAddress.parse("  HTTP://node.local  "))
    }

    @Test
    fun rejectsBadInput() {
        assertNull(NodeAddress.parse(""))
        assertNull(NodeAddress.parse("   "))
        assertNull(NodeAddress.parse("ftp://node.local"))
        assertNull(NodeAddress.parse("user@node.local"))
        assertNull(NodeAddress.parse("bad host"))
        assertNull(NodeAddress.parse("-leading-dash"))
        assertNull(NodeAddress.parse("node.local:0"))
        assertNull(NodeAddress.parse("node.local:70000"))
        assertNull(NodeAddress.parse("node.local:+80"))
        assertNull(NodeAddress.parse("node.local:abc"))
        assertNull(NodeAddress.parse("[fe80::1"))
        assertNull(NodeAddress.parse("[fe80::1]x"))
    }

    @Test
    fun originBracketsIpv6() {
        assertEquals("http://[fe80::1]:8989", NodeAddress("fe80::1", 8989, false).origin)
        assertEquals("https://node.example.net:443", NodeAddress("node.example.net", 443, true).origin)
    }

    @Test
    fun sameOriginMatchesSchemeHostAndPort() {
        val n = NodeAddress("node.local", 8989, false)
        assertTrue(n.isOrigin("http", "node.local", 8989))
        assertTrue(n.isOrigin("HTTP", "Node.Local", 8989))
        assertFalse(n.isOrigin("http", "node.local", -1))
        assertTrue(NodeAddress("node.local", 80, false).isOrigin("http", "node.local", -1))
        assertFalse(n.isOrigin("https", "node.local", 8989))
        assertFalse(n.isOrigin("http", "node.local", 8990))
        assertFalse(n.isOrigin("http", "other.local", 8989))
        assertFalse(n.isOrigin(null, "node.local", 8989))
        assertFalse(n.isOrigin("http", null, 8989))
    }

    @Test
    fun sameOriginIpv6UsesBareHost() {
        assertTrue(NodeAddress("fe80::1", 8989, false).isOrigin("http", "[fe80::1]", 8989))
    }
}
