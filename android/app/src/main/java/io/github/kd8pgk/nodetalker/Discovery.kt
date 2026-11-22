package io.github.kd8pgk.nodetalker

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object Discovery {
    const val TYPE = "_asl-dvs._tcp."

    @Suppress("DEPRECATION")
    fun advertised(c: Context, pin: String, timeoutMs: Long): List<String> {
        val nsd = c.applicationContext.getSystemService(Context.NSD_SERVICE) as? NsdManager ?: return emptyList()
        val lock = Any()
        val found = ArrayList<String>()
        val pending = ArrayDeque<NsdServiceInfo>()
        val done = CountDownLatch(1)
        var resolving = false
        var stopped = false

        fun resolveNext() {
            val info = synchronized(lock) {
                if (stopped || resolving) null else pending.pollFirst()?.also { resolving = true }
            } ?: return
            nsd.resolveService(info, object : NsdManager.ResolveListener {
                override fun onResolveFailed(si: NsdServiceInfo, errorCode: Int) {
                    synchronized(lock) { resolving = false }
                    resolveNext()
                }

                override fun onServiceResolved(si: NsdServiceInfo) {
                    val fp = si.attributes["fp"]?.let { String(it, Charsets.UTF_8) }.orEmpty()
                    val ip = si.host?.hostAddress
                    synchronized(lock) {
                        resolving = false
                        if (ip != null && NodeLink.sameFingerprint(fp, pin) && !found.contains(ip)) found.add(ip)
                        if (found.isNotEmpty()) done.countDown()
                    }
                    resolveNext()
                }
            })
        }

        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
            }

            override fun onDiscoveryStopped(serviceType: String) {
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                done.countDown()
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
            }

            override fun onServiceFound(si: NsdServiceInfo) {
                if (si.serviceType.trimEnd('.') != TYPE.trimEnd('.')) return
                synchronized(lock) { pending.add(si) }
                resolveNext()
            }

            override fun onServiceLost(si: NsdServiceInfo) {
            }
        }

        try {
            nsd.discoverServices(TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: IllegalArgumentException) {
            return emptyList()
        }
        done.await(timeoutMs, TimeUnit.MILLISECONDS)
        synchronized(lock) { stopped = true }
        runCatching { nsd.stopServiceDiscovery(listener) }
        return synchronized(lock) { found.toList() }
    }
}
