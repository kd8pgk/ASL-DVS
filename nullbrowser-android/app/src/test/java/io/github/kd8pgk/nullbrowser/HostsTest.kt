package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HostsTest {
    @Test
    fun namedPrivateHosts() {
        assertTrue(isPrivateHost("localhost"))
        assertTrue(isPrivateHost("router.local"))
        assertTrue(isPrivateHost("box.lan"))
        assertTrue(isPrivateHost("node"))
        assertTrue(isPrivateHost(""))
        assertTrue(isPrivateHost(null))
        assertFalse(isPrivateHost("example.com"))
        assertFalse(isPrivateHost("www.example.com"))
    }

    @Test
    fun privateIpv4Ranges() {
        assertTrue(isPrivateHost("10.1.2.3"))
        assertTrue(isPrivateHost("192.168.1.1"))
        assertTrue(isPrivateHost("172.16.0.1"))
        assertTrue(isPrivateHost("172.31.255.255"))
        assertTrue(isPrivateHost("127.0.0.1"))
        assertTrue(isPrivateHost("169.254.1.1"))
        assertFalse(isPrivateHost("172.32.0.1"))
        assertFalse(isPrivateHost("8.8.8.8"))
        assertFalse(isPrivateHost("1.1.1.1"))
    }

    @Test
    fun ipv6Loopback() {
        assertTrue(isPrivateHost("::1"))
        assertTrue(isPrivateHost("fd00::1"))
    }
}
