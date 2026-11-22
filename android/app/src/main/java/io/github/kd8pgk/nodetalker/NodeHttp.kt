package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import java.io.IOException
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URL
import java.security.GeneralSecurityException
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.X509TrustManager

object NodeHttp {
    @SuppressLint("CustomX509TrustManager")
    fun fingerprintAt(ip: String, port: Int, timeoutMs: Int): String? {
        var seen: X509Certificate? = null
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            }

            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                seen = chain?.firstOrNull()
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val raw = Socket()
        return try {
            raw.connect(InetSocketAddress(InetAddress.getByName(ip), port), timeoutMs)
            raw.soTimeout = timeoutMs
            val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }
            val ss = ctx.socketFactory.createSocket(raw, ip, port, true) as SSLSocket
            ss.use { it.startHandshake() }
            seen?.let { NodeLink.fingerprint(it.encoded) }
        } catch (e: IOException) {
            null
        } catch (e: GeneralSecurityException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        } finally {
            runCatching { raw.close() }
        }
    }

    fun open(node: Node, path: String, cookie: String?): HttpURLConnection {
        val c = URL(node.origin + path).openConnection() as HttpURLConnection
        if (c is HttpsURLConnection && node.pin.isNotEmpty()) {
            c.sslSocketFactory = pinned(node.pin).socketFactory
            c.hostnameVerifier = HostnameVerifier { _, session ->
                session.peerCertificates.firstOrNull()?.let { Certs.fingerprint(it.encoded) == node.pin } == true
            }
        }
        if (!cookie.isNullOrEmpty()) c.setRequestProperty("Cookie", cookie)
        c.connectTimeout = 8000
        c.readTimeout = 20000
        return c
    }

    @SuppressLint("CustomX509TrustManager")
    fun pinned(pin: String): SSLContext {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                throw CertificateException("client certificates are not used")
            }

            override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
                val leaf = chain?.firstOrNull() ?: throw CertificateException("no certificate")
                if (Certs.fingerprint(leaf.encoded) != pin) throw CertificateException("certificate does not match the trusted one")
            }

            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        return SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), null) }
    }
}
