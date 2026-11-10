package io.github.kd8pgk.nodetalker

import android.content.Context
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioManager
import android.os.Build
import java.text.DateFormat
import java.util.Date
import java.util.concurrent.CopyOnWriteArrayList

object Bluetooth {
    data class Change(val connected: Boolean, val name: String, val at: Long)

    @Volatile var last: Change? = null
    @Volatile private var resumePending = false
    @Volatile private var app: Context? = null
    val listeners = CopyOnWriteArrayList<() -> Unit>()

    private val callback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = changed(added, true)
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = changed(removed, false)
    }

    fun watch(c: Context) {
        app = c.applicationContext
        c.getSystemService(AudioManager::class.java).registerAudioDeviceCallback(callback, null)
    }

    private fun changed(devices: Array<out AudioDeviceInfo>, connected: Boolean) {
        val bt = devices.firstOrNull { it.isSink && isBluetooth(it.type) } ?: return
        last = Change(connected, bt.productName?.toString().orEmpty(), System.currentTimeMillis())
        app?.let { if (connected) onConnect(it) else onDisconnect(it) }
        listeners.forEach { it() }
    }

    private fun onConnect(c: Context) {
        val s = NodeStore.bluetooth(c)
        val start = s.autoStart || (s.resume && resumePending)
        resumePending = false
        if (!start || Listen.state != Listen.OFF) return
        val n = NodeStore.get(c, NodeStore.lastNode(c)) ?: return
        try {
            Listen.start(c, n, "system", "bluetooth_connect")
        } catch (e: IllegalStateException) {
            return
        } catch (e: SecurityException) {
            return
        }
    }

    private fun onDisconnect(c: Context) {
        if (outputs(c).isNotEmpty()) return
        val s = NodeStore.bluetooth(c)
        if (!s.autoStop || Listen.state == Listen.OFF) return
        resumePending = s.resume
        Listen.stop(c, "system", "bluetooth_gone")
    }

    fun isBluetooth(type: Int): Boolean =
        type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP ||
            type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
            (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && type == AudioDeviceInfo.TYPE_HEARING_AID) ||
            (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && (type == AudioDeviceInfo.TYPE_BLE_HEADSET || type == AudioDeviceInfo.TYPE_BLE_SPEAKER)) ||
            (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && type == AudioDeviceInfo.TYPE_BLE_BROADCAST)

    private fun isWired(type: Int): Boolean =
        type == AudioDeviceInfo.TYPE_WIRED_HEADSET || type == AudioDeviceInfo.TYPE_WIRED_HEADPHONES || type == AudioDeviceInfo.TYPE_USB_HEADSET

    fun outputs(c: Context): List<AudioDeviceInfo> =
        c.getSystemService(AudioManager::class.java).getDevices(AudioManager.GET_DEVICES_OUTPUTS).filter { isBluetooth(it.type) }

    fun micAvailable(c: Context): Boolean =
        c.getSystemService(AudioManager::class.java).getDevices(AudioManager.GET_DEVICES_INPUTS).any { isBluetooth(it.type) }

    fun wiredConnected(c: Context): Boolean =
        c.getSystemService(AudioManager::class.java).getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { isWired(it.type) }

    fun profileRes(type: Int): Int = when (type) {
        AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> R.string.bt_profile_sco
        AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> R.string.bt_profile_a2dp
        else -> R.string.bt_profile_other
    }

    data class Dev(
        val kind: String,
        val name: String,
        val id: Int,
        val sink: Boolean,
        val source: Boolean,
        val rates: List<Int>,
        val channels: List<Int>,
        val encodings: List<String>,
    )

    data class Snap(
        val hasBt: Boolean,
        val hasBle: Boolean,
        val devices: List<Dev>,
        val comm: String?,
        val scoOn: Boolean,
        val a2dpOn: Boolean,
        val scoAvailable: Boolean,
        val mode: String,
        val mediaNow: Int,
        val mediaMax: Int,
        val callNow: Int,
        val callMax: Int,
        val lastConnected: Boolean?,
        val lastName: String,
        val lastAt: Long,
    )

    fun kindName(type: Int): String = when {
        type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP -> "a2dp"
        type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "sco"
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.P && type == AudioDeviceInfo.TYPE_HEARING_AID -> "hearing_aid"
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && type == AudioDeviceInfo.TYPE_BLE_HEADSET -> "ble_headset"
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && type == AudioDeviceInfo.TYPE_BLE_SPEAKER -> "ble_speaker"
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && type == AudioDeviceInfo.TYPE_BLE_BROADCAST -> "ble_broadcast"
        else -> "other"
    }

    fun encodingName(e: Int): String = when (e) {
        AudioFormat.ENCODING_PCM_16BIT -> "pcm16"
        AudioFormat.ENCODING_PCM_8BIT -> "pcm8"
        AudioFormat.ENCODING_PCM_FLOAT -> "pcm_float"
        AudioFormat.ENCODING_AC3 -> "ac3"
        AudioFormat.ENCODING_E_AC3 -> "eac3"
        AudioFormat.ENCODING_DTS -> "dts"
        AudioFormat.ENCODING_AAC_LC -> "aac"
        else -> "enc$e"
    }

    fun modeName(m: Int): String = when (m) {
        AudioManager.MODE_NORMAL -> "normal"
        AudioManager.MODE_RINGTONE -> "ringtone"
        AudioManager.MODE_IN_CALL -> "in_call"
        AudioManager.MODE_IN_COMMUNICATION -> "in_communication"
        else -> "mode$m"
    }

    @Suppress("DEPRECATION")
    fun snapshot(c: Context): Snap {
        val am = c.getSystemService(AudioManager::class.java)
        val pm = c.packageManager
        val devices = am.getDevices(AudioManager.GET_DEVICES_ALL)
            .filter { isBluetooth(it.type) }
            .map {
                Dev(
                    kindName(it.type), it.productName?.toString().orEmpty(), it.id, it.isSink, it.isSource,
                    it.sampleRates.toList(), it.channelCounts.toList(), it.encodings.map(::encodingName),
                )
            }
        val comm = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) am.communicationDevice?.let { kindName(it.type) } else null
        val l = last
        return Snap(
            pm.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH),
            pm.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE),
            devices, comm,
            am.isBluetoothScoOn, am.isBluetoothA2dpOn, am.isBluetoothScoAvailableOffCall, modeName(am.mode),
            am.getStreamVolume(AudioManager.STREAM_MUSIC), am.getStreamMaxVolume(AudioManager.STREAM_MUSIC),
            am.getStreamVolume(AudioManager.STREAM_VOICE_CALL), am.getStreamMaxVolume(AudioManager.STREAM_VOICE_CALL),
            l?.connected, l?.name.orEmpty(), l?.at ?: 0L,
        )
    }

    fun quote(s: String): String {
        val b = StringBuilder("\"")
        for (ch in s) {
            when {
                ch == '"' -> b.append("\\\"")
                ch == '\\' -> b.append("\\\\")
                ch < ' ' -> b.append(' ')
                else -> b.append(ch)
            }
        }
        return b.append('"').toString()
    }

    fun json(s: Snap): String {
        val d = s.devices.joinToString(",") {
            "{\"kind\":${quote(it.kind)},\"name\":${quote(it.name)},\"id\":${it.id},\"out\":${it.sink},\"in\":${it.source}," +
                "\"rates\":[${it.rates.joinToString(",")}],\"channels\":[${it.channels.joinToString(",")}]," +
                "\"encodings\":[${it.encodings.joinToString(",") { e -> quote(e) }}]}"
        }
        val last = if (s.lastConnected == null) "null" else
            "{\"connected\":${s.lastConnected},\"name\":${quote(s.lastName)},\"at\":${s.lastAt}}"
        return "{\"bluetooth\":${s.hasBt},\"ble\":${s.hasBle},\"devices\":[$d]," +
            "\"comm\":${s.comm?.let { quote(it) } ?: "null"},\"sco_on\":${s.scoOn},\"a2dp_on\":${s.a2dpOn}," +
            "\"sco_available\":${s.scoAvailable},\"mode\":${quote(s.mode)}," +
            "\"media\":{\"now\":${s.mediaNow},\"max\":${s.mediaMax}},\"call\":{\"now\":${s.callNow},\"max\":${s.callMax}}," +
            "\"last\":$last}"
    }

    fun time(at: Long): String = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(at))
}
