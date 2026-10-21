package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import java.net.HttpURLConnection
import java.net.URL
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

object NodeHttp {
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
