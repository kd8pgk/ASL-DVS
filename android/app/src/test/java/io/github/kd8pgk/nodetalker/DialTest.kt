package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.ConnectException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class DialTest {
    private fun ip(text: String): InetAddress = InetAddress.getByName(text)

    @Test
    fun ipv4ComesFirstAndLinkLocalIpv6Last() {
        val given = listOf(ip("fe80::1"), ip("2001:db8::1"), ip("192.168.0.5"), ip("10.0.0.9"))
        assertEquals(
            listOf("192.168.0.5", "10.0.0.9", "2001:db8:0:0:0:0:0:1", "fe80:0:0:0:0:0:0:1"),
            Dial.order(given).map { it.hostAddress },
        )
    }

    @Test
    fun theGivenOrderIsKeptWithinAKind() {
        val given = listOf(ip("10.0.0.2"), ip("10.0.0.1"), ip("10.0.0.3"))
        assertEquals(given, Dial.order(given))
    }

    @Test
    fun aDeadFirstAddressDoesNotStopTheConnection() {
        ServerSocket(0, 4, InetAddress.getLoopbackAddress()).use { server ->
            val s = Dial.connect("node.local", server.localPort, 4000) { arrayOf(ip("127.0.0.2"), ip("127.0.0.1")) }
            assertTrue(s.isConnected)
            assertEquals("127.0.0.1", s.inetAddress.hostAddress)
            s.close()
        }
    }

    @Test
    fun aLinkLocalAddressTheNodeCannotUseIsTriedLast() {
        ServerSocket(0, 4, InetAddress.getLoopbackAddress()).use { server ->
            val s = Dial.connect("node.local", server.localPort, 4000) { arrayOf(ip("fe80::1"), ip("127.0.0.1")) }
            assertEquals("127.0.0.1", s.inetAddress.hostAddress)
            s.close()
        }
    }

    @Test
    fun whenEveryAddressFailsTheErrorNamesTheHostAndTheAddresses() {
        val port = ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { it.localPort }
        val e = assertThrows(ConnectException::class.java) {
            Dial.connect("node.local", port, 4000) { arrayOf(ip("127.0.0.1"), ip("127.0.0.2")) }
        }
        assertTrue(e.message!!.startsWith("failed to connect to node.local (127.0.0.1, 127.0.0.2)"))
        assertEquals("connect", SocketErrors.classify(e))
    }

    @Test
    fun aSingleAddressKeepsItsOwnError() {
        val port = ServerSocket(0, 1, InetAddress.getLoopbackAddress()).use { it.localPort }
        val e = assertThrows(ConnectException::class.java) {
            Dial.connect("node.local", port, 4000) { arrayOf(ip("127.0.0.1")) }
        }
        assertFalse(e.message!!.contains("node.local"))
    }

    @Test
    fun aNameThatDoesNotResolveStaysAConnectProblem() {
        val e = assertThrows(UnknownHostException::class.java) {
            Dial.connect("node.local", 8993, 4000) { throw UnknownHostException("Unable to resolve host \"node.local\"") }
        }
        assertEquals("connect", SocketErrors.classify(e))
    }

    @Test
    fun noAddressesAtAllIsAConnectError() {
        val e = assertThrows(ConnectException::class.java) { Dial.connect("node.local", 8993, 4000) { emptyArray() } }
        assertTrue(e.message!!.contains("no address to try"))
    }

    @Test
    fun aTimeoutInsideTheWrapperIsStillATimeout() {
        val wrapped = ConnectException("failed to connect to node.local (10.0.0.1, 10.0.0.2): timed out")
        wrapped.initCause(SocketTimeoutException("connect timed out"))
        assertEquals("timeout", SocketErrors.classify(wrapped))
    }
}
