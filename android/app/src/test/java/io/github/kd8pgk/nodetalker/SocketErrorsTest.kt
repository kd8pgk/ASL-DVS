package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.EOFException
import java.io.IOException
import java.net.ConnectException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertificateException
import javax.net.ssl.SSLException
import javax.net.ssl.SSLHandshakeException

class SocketErrorsTest {
    @Test
    fun timeoutWins() {
        assertEquals("timeout", SocketErrors.classify(SocketTimeoutException("Read timed out")))
        assertEquals("timeout", SocketErrors.classify(SSLException("handshake", SocketTimeoutException("timed out"))))
    }

    @Test
    fun cannotReachTheNode() {
        assertEquals("connect", SocketErrors.classify(ConnectException("Connection refused")))
        assertEquals("connect", SocketErrors.classify(UnknownHostException("Unable to resolve host \"pi.local\": No address associated with hostname")))
    }

    @Test
    fun certificateProblemsAreTls() {
        assertEquals("tls", SocketErrors.classify(SSLHandshakeException("bad").also { it.initCause(CertificateException("chain")) }))
        assertEquals("tls", SocketErrors.classify(IOException("the certificate does not match pi.local")))
        assertEquals("tls", SocketErrors.classify(IOException("certificate does not match the trusted one")))
        assertEquals("tls", SocketErrors.classify(SSLException("Hostname pi.local not verified")))
    }

    @Test
    fun resetsAreNotLumpedWithOther() {
        assertEquals("reset", SocketErrors.classify(SocketException("Connection reset")))
        assertEquals("reset", SocketErrors.classify(SocketException("Broken pipe")))
        assertEquals("reset", SocketErrors.classify(SSLException("read error", SocketException("Connection reset by peer"))))
    }

    @Test
    fun closedByTheNode() {
        assertEquals("closed", SocketErrors.classify(EOFException()))
        assertEquals("closed", SocketErrors.classify(IOException("the node closed the talk channel")))
        assertEquals("closed", SocketErrors.classify(SocketException("Socket closed")))
    }

    @Test
    fun httpAndLogin() {
        assertEquals("http", SocketErrors.classify(NodeHttpException(403, "the node refused the talk channel (HTTP 403)")))
        assertEquals("http", SocketErrors.classify(NodeHttpException(503, "All 3 listener slots are in use.")))
        assertEquals("login", SocketErrors.classify(NodeHttpException(401, "log in on the page first")))
        assertEquals("login", SocketErrors.classify(IOException("log in on the page first")))
        assertEquals("http", SocketErrors.classify(IOException("HTTP 502")))
        assertEquals(403, SocketErrors.httpCode(NodeHttpException(403, "x")))
        assertEquals(403, SocketErrors.httpCode(IOException("outer", NodeHttpException(403, "x"))))
        assertEquals(0, SocketErrors.httpCode(IOException("x")))
    }

    @Test
    fun everythingElseIsOther() {
        assertEquals("other", SocketErrors.classify(IOException("bad frame from the node")))
        assertEquals("other", SocketErrors.classify(IOException("bad answer from the node")))
        assertEquals("other", SocketErrors.classify(IOException(null as String?)))
    }

    @Test
    fun aCauseLoopDoesNotHang() {
        val a = IOException("a")
        val b = IOException("b", a)
        a.initCause(b)
        assertEquals("other", SocketErrors.classify(a))
    }

    @Test
    fun detailKeepsTheWholeAddressAndIsNeverEmpty() {
        assertEquals("IOException", SocketErrors.detail(IOException()))
        assertEquals("SocketTimeoutException", SocketErrors.detail(SocketTimeoutException("  ")))
        assertEquals(300, SocketErrors.detail(IOException("x".repeat(900))).length)
        val long = "failed to connect to MagicBox.local (192.168.0.50, fe80:0:0:0:a2b:cff:fe00:1%wlan0): " +
            "failed to connect to MagicBox.local/192.168.0.50 (port 8993) from /192.168.0.168 (port 40000) after 3000ms"
        assertEquals(long, SocketErrors.detail(ConnectException(long)))
    }

    @Test
    fun theFirstFailureIsReportedAtOnce() {
        val r = FailureReporter(60000L)
        assertEquals(1, r.fail(1000L)?.failures)
    }

    @Test
    fun repeatsAreHeldBackThenSummed() {
        val r = FailureReporter(60000L)
        assertNotNull(r.fail(0L))
        assertNull(r.fail(2000L))
        assertNull(r.fail(6000L))
        assertNull(r.fail(59999L))
        assertEquals(4, r.fail(60000L)?.failures)
        assertNull(r.fail(61000L))
    }

    @Test
    fun recoveryIsReportedOnlyForAReportedRun() {
        val r = FailureReporter(60000L)
        assertNotNull(r.fail(10000L))
        assertNull(r.fail(12000L))
        val up = r.up(25000L)
        assertEquals(15, up?.secs)
        assertEquals(2, up?.failures)
        assertNull(r.up(26000L))
    }

    @Test
    fun aFlappingConnectionIsBounded() {
        val r = FailureReporter(60000L)
        var sent = 0
        var t = 0L
        repeat(40) {
            if (r.fail(t) != null) sent++
            t += 1500L
            if (r.up(t) != null) sent++
            t += 1500L
        }
        assertEquals(4, sent)
    }

    @Test
    fun anUnreportedRunStaysSilentOnRecovery() {
        val r = FailureReporter(60000L)
        assertNotNull(r.fail(0L))
        assertNotNull(r.up(1000L))
        assertNull(r.fail(2000L))
        assertNull(r.up(3000L))
    }
}
