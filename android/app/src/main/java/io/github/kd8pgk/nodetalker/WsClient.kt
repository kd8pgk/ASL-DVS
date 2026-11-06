package io.github.kd8pgk.nodetalker

import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

class WsClient(private val node: Node, private val cookie: String?) {
    private var sock: Socket? = null
    private var out: OutputStream? = null
    private var input: DataInputStream? = null
    private val writeLock = Any()
    private val rnd = SecureRandom()

    fun connect() {
        val raw = Socket()
        raw.connect(InetSocketAddress(node.host, node.port), 8000)
        raw.tcpNoDelay = true
        val s: Socket = if (node.https) {
            val f = if (node.pin.isNotEmpty()) NodeHttp.pinned(node.pin).socketFactory else SSLSocketFactory.getDefault() as SSLSocketFactory
            val ss = f.createSocket(raw, node.host, node.port, true) as SSLSocket
            ss.startHandshake()
            if (node.pin.isEmpty() && !HttpsURLConnection.getDefaultHostnameVerifier().verify(node.host, ss.session)) {
                ss.close()
                throw IOException("the certificate does not match ${node.host}")
            }
            ss
        } else {
            raw
        }
        s.soTimeout = 70000
        sock = s
        val o = s.getOutputStream()
        val i = DataInputStream(s.getInputStream())
        val key = ByteArray(16).also { rnd.nextBytes(it) }
        val keyText = Base64.getEncoder().encodeToString(key)
        val hostHdr = (if (node.host.contains(':')) "[${node.host}]" else node.host) + ":" + node.port
        val req = StringBuilder()
            .append("GET /api/talk HTTP/1.1\r\n")
            .append("Host: ").append(hostHdr).append("\r\n")
            .append("Upgrade: websocket\r\nConnection: Upgrade\r\n")
            .append("Sec-WebSocket-Key: ").append(keyText).append("\r\n")
            .append("Sec-WebSocket-Version: 13\r\n")
            .append("Origin: ").append(node.origin).append("\r\n")
        if (!cookie.isNullOrEmpty()) req.append("Cookie: ").append(cookie).append("\r\n")
        req.append("\r\n")
        o.write(req.toString().toByteArray(Charsets.ISO_8859_1))
        o.flush()
        val head = StringBuilder()
        while (!head.endsWith("\r\n\r\n")) {
            val b = i.read()
            if (b < 0) throw IOException("the node closed the talk channel")
            head.append(b.toChar())
            if (head.length > 8192) throw IOException("bad answer from the node")
        }
        val status = head.lineSequence().firstOrNull().orEmpty()
        val code = status.split(' ').getOrNull(1)?.toIntOrNull() ?: 0
        if (code != 101) {
            close()
            throw NodeHttpException(code, if (code == 401) "log in on the page first" else "the node refused the talk channel (HTTP $code)")
        }
        val accept = head.lineSequence()
            .firstOrNull { it.startsWith("Sec-WebSocket-Accept:", ignoreCase = true) }
            ?.substringAfter(':')?.trim()
        if (accept != acceptFor(keyText)) {
            close()
            throw IOException("bad answer from the node")
        }
        out = o
        input = i
    }

    fun sendText(text: String) = send(1, text.toByteArray(Charsets.UTF_8))

    fun sendBinary(data: ByteArray) = send(2, data)

    fun send(opcode: Int, payload: ByteArray) {
        val o = out ?: throw IOException("not connected")
        val n = payload.size
        val hdr = ByteArray(14)
        var p = 0
        hdr[p++] = (0x80 or opcode).toByte()
        when {
            n < 126 -> hdr[p++] = (0x80 or n).toByte()
            n < 65536 -> {
                hdr[p++] = (0x80 or 126).toByte()
                hdr[p++] = (n shr 8).toByte()
                hdr[p++] = n.toByte()
            }
            else -> {
                hdr[p++] = (0x80 or 127).toByte()
                for (k in 7 downTo 0) hdr[p++] = (n.toLong() shr (8 * k)).toByte()
            }
        }
        val mask = ByteArray(4).also { rnd.nextBytes(it) }
        System.arraycopy(mask, 0, hdr, p, 4)
        p += 4
        val body = ByteArray(n) { (payload[it].toInt() xor mask[it and 3].toInt()).toByte() }
        synchronized(writeLock) {
            o.write(hdr, 0, p)
            o.write(body)
            o.flush()
        }
    }

    fun read(onText: (String) -> Unit) {
        val i = input ?: throw IOException("not connected")
        val msg = ByteArrayOutputStream()
        var msgOp = 0
        while (true) {
            val b0 = i.readUnsignedByte()
            val b1 = i.readUnsignedByte()
            val fin = b0 and 0x80 != 0
            val op = b0 and 0x0f
            var len = (b1 and 0x7f).toLong()
            if (len == 126L) len = i.readUnsignedShort().toLong()
            else if (len == 127L) len = i.readLong()
            if (len < 0 || len > MAX_MESSAGE) throw IOException("bad frame from the node")
            val mask = if (b1 and 0x80 != 0) ByteArray(4).also { i.readFully(it) } else null
            val data = ByteArray(len.toInt())
            i.readFully(data)
            if (mask != null) for (k in data.indices) data[k] = (data[k].toInt() xor mask[k and 3].toInt()).toByte()
            when (op) {
                1, 2 -> {
                    if (msgOp != 0) throw IOException("bad frame from the node")
                    msgOp = op
                    msg.reset()
                    msg.write(data)
                }
                0 -> {
                    if (msgOp == 0 || msg.size() + data.size > MAX_MESSAGE) throw IOException("bad frame from the node")
                    msg.write(data)
                }
                8 -> throw IOException("the node closed the talk channel")
                9 -> send(10, data)
            }
            if ((op == 0 || op == 1 || op == 2) && fin) {
                if (msgOp == 1) onText(String(msg.toByteArray(), Charsets.UTF_8))
                msg.reset()
                msgOp = 0
            }
        }
    }

    fun close() {
        try {
            out?.let { send(8, ByteArray(0)) }
        } catch (e: IOException) {
            out = null
        }
        try {
            sock?.close()
        } catch (e: IOException) {
            sock = null
        }
        out = null
        input = null
    }

    companion object {
        const val MAX_MESSAGE = 1_000_000L
        private const val GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

        fun acceptFor(key: String): String =
            Base64.getEncoder().encodeToString(
                MessageDigest.getInstance("SHA-1").digest((key + GUID).toByteArray(Charsets.US_ASCII))
            )
    }
}
