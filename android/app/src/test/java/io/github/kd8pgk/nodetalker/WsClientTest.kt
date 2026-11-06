package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.EOFException
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Base64
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread

class WsClientTest {

    private class Frame(val fin: Boolean, val op: Int, val masked: Boolean, val payload: ByteArray)

    private class Peer(private val sock: Socket) {
        private val input = DataInputStream(sock.getInputStream())
        private val out = sock.getOutputStream()

        fun readHead(): String {
            val sb = StringBuilder()
            while (!sb.endsWith("\r\n\r\n")) {
                val b = input.read()
                if (b < 0) break
                sb.append(b.toChar())
            }
            return sb.toString()
        }

        fun accept(head: String, accept: String? = null) {
            val key = head.lines().first { it.startsWith("Sec-WebSocket-Key:", ignoreCase = true) }
                .substringAfter(':').trim()
            val value = accept ?: WsClient.acceptFor(key)
            out.write(
                ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
                    "Sec-WebSocket-Accept: $value\r\n\r\n").toByteArray(Charsets.ISO_8859_1)
            )
            out.flush()
        }

        fun answer(status: String) {
            out.write("HTTP/1.1 $status\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n".toByteArray(Charsets.ISO_8859_1))
            out.flush()
        }

        fun readFrame(): Frame {
            val b0 = input.readUnsignedByte()
            val b1 = input.readUnsignedByte()
            var len = (b1 and 0x7f).toLong()
            if (len == 126L) len = input.readUnsignedShort().toLong()
            else if (len == 127L) len = input.readLong()
            val masked = b1 and 0x80 != 0
            val mask = if (masked) ByteArray(4).also { input.readFully(it) } else null
            val data = ByteArray(len.toInt())
            input.readFully(data)
            if (mask != null) for (i in data.indices) data[i] = (data[i].toInt() xor mask[i and 3].toInt()).toByte()
            return Frame(b0 and 0x80 != 0, b0 and 0x0f, masked, data)
        }

        fun write(bytes: ByteArray) {
            out.write(bytes)
            out.flush()
        }
    }

    private class Harness : AutoCloseable {
        private val server = ServerSocket(0, 4, InetAddress.getLoopbackAddress())
        private val sessions = CopyOnWriteArrayList<Socket>()
        private var worker: Thread? = null
        val failure = AtomicReference<Throwable?>(null)
        val port: Int get() = server.localPort

        fun node() = Node("test", "test", "127.0.0.1", port, false)

        fun serve(script: (Peer) -> Unit) {
            worker = thread(isDaemon = true) {
                try {
                    val s = server.accept()
                    sessions.add(s)
                    script(Peer(s))
                    s.close()
                } catch (e: Throwable) {
                    failure.set(e)
                }
            }
        }

        fun finish() {
            worker?.join(5000)
            failure.get()?.let { throw it }
        }

        override fun close() {
            sessions.forEach { it.close() }
            server.close()
        }
    }

    private fun frameBytes(op: Int, payload: ByteArray, fin: Boolean = true): ByteArray {
        val b = ByteArrayOutputStream()
        b.write((if (fin) 0x80 else 0) or op)
        val n = payload.size
        when {
            n < 126 -> b.write(n)
            n < 65536 -> {
                b.write(126)
                b.write(n shr 8)
                b.write(n and 0xff)
            }
            else -> {
                b.write(127)
                for (k in 7 downTo 0) b.write((n.toLong() shr (8 * k)).toInt() and 0xff)
            }
        }
        b.write(payload)
        return b.toByteArray()
    }

    private fun longBytes(v: Long): ByteArray = ByteArray(8) { (v shr (56 - 8 * it)).toByte() }

    private fun drain(c: WsClient, onText: (String) -> Unit): IOException {
        try {
            c.read(onText)
        } catch (e: IOException) {
            return e
        }
        throw AssertionError("read returned without an error")
    }

    private fun pattern(n: Int) = ByteArray(n) { (it * 7).toByte() }

    @Test
    fun upgrade_request_carries_the_key_origin_and_cookie() {
        Harness().use { h ->
            val head = AtomicReference("")
            h.serve { p ->
                val req = p.readHead()
                head.set(req)
                p.accept(req)
            }
            val c = WsClient(h.node(), "session=abc")
            c.connect()
            c.close()
            h.finish()
            val text = head.get()
            assertTrue(text.startsWith("GET /api/talk HTTP/1.1\r\n"))
            assertTrue(text.contains("\r\nHost: 127.0.0.1:${h.port}\r\n"))
            assertTrue(text.contains("\r\nOrigin: http://127.0.0.1:${h.port}\r\n"))
            assertTrue(text.contains("\r\nCookie: session=abc\r\n"))
            assertTrue(text.contains("\r\nUpgrade: websocket\r\n"))
            assertTrue(text.contains("\r\nSec-WebSocket-Version: 13\r\n"))
            val key = text.lines().first { it.startsWith("Sec-WebSocket-Key: ") }
                .removePrefix("Sec-WebSocket-Key: ").trim()
            assertEquals(16, Base64.getDecoder().decode(key).size)
        }
    }

    @Test
    fun no_cookie_header_when_there_is_no_session() {
        Harness().use { h ->
            val head = AtomicReference("")
            h.serve { p ->
                val req = p.readHead()
                head.set(req)
                p.accept(req)
            }
            WsClient(h.node(), null).apply { connect(); close() }
            h.finish()
            assertFalse(head.get().contains("Cookie:"))
        }
    }

    @Test
    fun a_401_says_to_log_in_first() {
        Harness().use { h ->
            h.serve { p ->
                p.readHead()
                p.answer("401 Unauthorized")
            }
            val e = assertThrows(IOException::class.java) { WsClient(h.node(), null).connect() }
            assertEquals("log in on the page first", e.message)
            assertEquals("login", SocketErrors.classify(e))
            assertEquals(401, SocketErrors.httpCode(e))
            h.finish()
        }
    }

    @Test
    fun any_other_refusal_names_the_code() {
        Harness().use { h ->
            h.serve { p ->
                p.readHead()
                p.answer("503 Service Unavailable")
            }
            val e = assertThrows(IOException::class.java) { WsClient(h.node(), null).connect() }
            assertEquals("the node refused the talk channel (HTTP 503)", e.message)
            assertEquals("http", SocketErrors.classify(e))
            assertEquals(503, SocketErrors.httpCode(e))
            h.finish()
        }
    }

    @Test
    fun a_node_that_closes_before_answering_is_reported() {
        Harness().use { h ->
            h.serve { p -> p.readHead() }
            val e = assertThrows(IOException::class.java) { WsClient(h.node(), null).connect() }
            assertEquals("the node closed the talk channel", e.message)
            assertEquals("closed", SocketErrors.classify(e))
            h.finish()
        }
    }

    @Test
    fun masked_binary_frames_are_correct_at_every_length_form() {
        Harness().use { h ->
            val sizes = listOf(0, 1, 125, 126, 300, 65535, 65536, 70000)
            val got = CopyOnWriteArrayList<Frame>()
            h.serve { p ->
                p.accept(p.readHead())
                repeat(sizes.size) { got.add(p.readFrame()) }
            }
            val c = WsClient(h.node(), null)
            c.connect()
            sizes.forEach { c.sendBinary(pattern(it)) }
            c.close()
            h.finish()
            assertEquals(sizes.size, got.size)
            sizes.forEachIndexed { i, n ->
                assertTrue(got[i].fin)
                assertEquals(2, got[i].op)
                assertTrue("frame $n must be masked", got[i].masked)
                assertArrayEquals("payload of $n bytes", pattern(n), got[i].payload)
            }
        }
    }

    @Test
    fun send_text_uses_the_text_opcode() {
        Harness().use { h ->
            val got = AtomicReference<Frame?>(null)
            h.serve { p ->
                p.accept(p.readHead())
                got.set(p.readFrame())
            }
            val c = WsClient(h.node(), null)
            c.connect()
            c.sendText("héllo")
            h.finish()
            assertEquals(1, got.get()!!.op)
            assertArrayEquals("héllo".toByteArray(Charsets.UTF_8), got.get()!!.payload)
        }
    }

    @Test
    fun read_delivers_text_in_every_length_form() {
        Harness().use { h ->
            val received = mutableListOf<String>()
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(1, "hi".toByteArray()))
                p.write(frameBytes(1, "x".repeat(200).toByteArray()))
                p.write(frameBytes(1, "y".repeat(70000).toByteArray()))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            val e = drain(c) { received.add(it) }
            h.finish()
            assertEquals(listOf("hi", "x".repeat(200), "y".repeat(70000)), received)
            assertTrue(e is EOFException)
        }
    }

    @Test
    fun read_answers_a_ping_with_a_masked_pong_carrying_the_same_payload() {
        Harness().use { h ->
            val pong = AtomicReference<Frame?>(null)
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(9, "ping-data".toByteArray()))
                pong.set(p.readFrame())
            }
            val c = WsClient(h.node(), null)
            c.connect()
            drain(c) {}
            h.finish()
            assertEquals(10, pong.get()!!.op)
            assertTrue(pong.get()!!.masked)
            assertArrayEquals("ping-data".toByteArray(), pong.get()!!.payload)
        }
    }

    @Test
    fun a_close_frame_from_the_node_ends_read_with_closed() {
        Harness().use { h ->
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(8, ByteArray(0)))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            val e = drain(c) {}
            h.finish()
            assertEquals("the node closed the talk channel", e.message)
        }
    }

    @Test
    fun a_frame_longer_than_a_megabyte_is_refused() {
        Harness().use { h ->
            h.serve { p ->
                p.accept(p.readHead())
                p.write(byteArrayOf(0x81.toByte(), 127) + longBytes(1_000_001L))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            val e = drain(c) {}
            h.finish()
            assertEquals("bad frame from the node", e.message)
        }
    }

    @Test
    fun a_negative_64_bit_length_is_refused() {
        Harness().use { h ->
            h.serve { p ->
                p.accept(p.readHead())
                p.write(byteArrayOf(0x81.toByte(), 127) + longBytes(Long.MIN_VALUE))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            val e = drain(c) {}
            h.finish()
            assertEquals("bad frame from the node", e.message)
        }
    }

    @Test
    fun close_sends_a_close_frame_before_the_socket_goes() {
        Harness().use { h ->
            val got = AtomicReference<Frame?>(null)
            h.serve { p ->
                p.accept(p.readHead())
                got.set(p.readFrame())
            }
            val c = WsClient(h.node(), null)
            c.connect()
            c.close()
            h.finish()
            assertEquals(8, got.get()!!.op)
            assertTrue(got.get()!!.masked)
        }
    }

    @Test
    fun sending_before_connecting_is_refused() {
        val c = WsClient(Node("t", "t", "127.0.0.1", 1, false), null)
        val e = assertThrows(IOException::class.java) { c.sendBinary(ByteArray(1)) }
        assertEquals("not connected", e.message)
    }

    @Test
    fun a_fragmented_text_message_is_reassembled() {
        Harness().use { h ->
            val received = mutableListOf<String>()
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(1, "Hel".toByteArray(), fin = false))
                p.write(frameBytes(0, "lo".toByteArray(), fin = true))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            drain(c) { received.add(it) }
            h.finish()
            assertEquals(listOf("Hello"), received)
        }
    }

    @Test
    fun a_ping_between_fragments_is_answered_and_the_message_still_joins() {
        Harness().use { h ->
            val received = mutableListOf<String>()
            val pong = AtomicReference<Frame?>(null)
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(1, "Hel".toByteArray(), fin = false))
                p.write(frameBytes(9, "mid".toByteArray()))
                p.write(frameBytes(0, "lo".toByteArray(), fin = true))
                pong.set(p.readFrame())
            }
            val c = WsClient(h.node(), null)
            c.connect()
            drain(c) { received.add(it) }
            h.finish()
            assertEquals(listOf("Hello"), received)
            assertEquals(10, pong.get()!!.op)
            assertArrayEquals("mid".toByteArray(), pong.get()!!.payload)
        }
    }

    @Test
    fun a_continuation_with_nothing_to_continue_is_refused() {
        Harness().use { h ->
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(0, "lo".toByteArray(), fin = true))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            assertEquals("bad frame from the node", drain(c) {}.message)
            h.finish()
        }
    }

    @Test
    fun a_new_message_before_the_last_one_ended_is_refused() {
        Harness().use { h ->
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(1, "a".toByteArray(), fin = false))
                p.write(frameBytes(1, "b".toByteArray(), fin = true))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            assertEquals("bad frame from the node", drain(c) {}.message)
            h.finish()
        }
    }

    @Test
    fun a_message_that_grows_past_a_megabyte_in_pieces_is_refused() {
        Harness().use { h ->
            val piece = ByteArray(600_000) { 'a'.code.toByte() }
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(1, piece, fin = false))
                p.write(frameBytes(0, piece, fin = true))
            }
            val received = mutableListOf<String>()
            val c = WsClient(h.node(), null)
            c.connect()
            assertEquals("bad frame from the node", drain(c) { received.add(it) }.message)
            h.finish()
            assertTrue(received.isEmpty())
        }
    }

    @Test
    fun a_binary_message_is_not_delivered_as_text() {
        Harness().use { h ->
            val received = mutableListOf<String>()
            h.serve { p ->
                p.accept(p.readHead())
                p.write(frameBytes(2, byteArrayOf(1, 2, 3)))
                p.write(frameBytes(1, "x".toByteArray()))
            }
            val c = WsClient(h.node(), null)
            c.connect()
            drain(c) { received.add(it) }
            h.finish()
            assertEquals(listOf("x"), received)
        }
    }

    @Test
    fun a_wrong_accept_key_is_refused() {
        Harness().use { h ->
            h.serve { p -> p.accept(p.readHead(), "AAAAAAAAAAAAAAAAAAAAAAAAAAA=") }
            val e = assertThrows(IOException::class.java) { WsClient(h.node(), null).connect() }
            assertEquals("bad answer from the node", e.message)
            h.finish()
        }
    }

    @Test
    fun a_missing_accept_key_is_refused() {
        Harness().use { h ->
            h.serve { p ->
                p.readHead()
                p.answer("101 Switching Protocols")
            }
            val e = assertThrows(IOException::class.java) { WsClient(h.node(), null).connect() }
            assertEquals("bad answer from the node", e.message)
            h.finish()
        }
    }

    @Test
    fun the_accept_key_matches_the_rfc_6455_example() {
        assertEquals("s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", WsClient.acceptFor("dGhlIHNhbXBsZSBub25jZQ=="))
    }
}
