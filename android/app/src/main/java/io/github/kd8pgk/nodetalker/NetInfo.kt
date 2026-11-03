package io.github.kd8pgk.nodetalker

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.PowerManager

class NetInfo(ctx: Context, private val onChange: () -> Unit) {
    private val app = ctx.applicationContext
    private val cm = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    @Suppress("DEPRECATION")
    private val wm = app.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val pm = app.getSystemService(Context.POWER_SERVICE) as PowerManager
    private var current: Network? = null
    private var caps: NetworkCapabilities? = null
    private var rssiMin = 0
    private var linkMin = 0
    private var mhz = 0
    private var started = false

    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            val had = current
            current = network
            if (had != null && had != network) onChange()
        }

        override fun onLost(network: Network) {
            if (current == network) {
                current = null
                caps = null
                onChange()
            }
        }

        override fun onCapabilitiesChanged(network: Network, c: NetworkCapabilities) {
            if (current == network) caps = c
        }
    }

    @Synchronized
    fun start() {
        if (started) return
        try {
            cm.registerDefaultNetworkCallback(callback)
            started = true
        } catch (e: RuntimeException) {
            started = false
        }
    }

    @Synchronized
    fun stop() {
        if (!started) return
        started = false
        try {
            cm.unregisterNetworkCallback(callback)
        } catch (e: RuntimeException) {
            return
        }
    }

    @Suppress("DEPRECATION")
    @Synchronized
    fun sample() {
        val c = caps ?: return
        if (!c.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return
        try {
            val i = wm.connectionInfo ?: return
            val r = i.rssi
            if (r in -126..-1 && (rssiMin == 0 || r < rssiMin)) rssiMin = r
            val l = i.linkSpeed
            if (l > 0 && (linkMin == 0 || l < linkMin)) linkMin = l
            if (i.frequency > 0) mhz = i.frequency
        } catch (e: RuntimeException) {
            return
        }
    }

    @Synchronized
    fun take(): String {
        val c = caps
        val kind = when {
            c == null -> "none"
            c.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            c.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cell"
            c.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "eth"
            else -> "other"
        }
        val metered = if (c != null && !c.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) 1 else 0
        val vpn = if (c != null && c.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) 1 else 0
        val save = if (pm.isPowerSaveMode) 1 else 0
        val idle = if (pm.isDeviceIdleMode) 1 else 0
        val s = ",\"net\":\"$kind\",\"metered\":$metered,\"vpn\":$vpn,\"psave\":$save,\"idle\":$idle," +
            "\"rssi_min\":$rssiMin,\"link_mbps\":$linkMin,\"mhz\":$mhz"
        rssiMin = 0
        linkMin = 0
        return s
    }
}
