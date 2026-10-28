package io.github.kd8pgk.nodetalker

import android.content.Context
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import java.text.DateFormat
import java.util.Date
import java.util.concurrent.CopyOnWriteArrayList

object Bluetooth {
    data class Change(val connected: Boolean, val name: String, val at: Long)

    @Volatile var last: Change? = null
    val listeners = CopyOnWriteArrayList<() -> Unit>()

    private val callback = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) = changed(added, true)
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) = changed(removed, false)
    }

    fun watch(c: Context) {
        c.getSystemService(AudioManager::class.java).registerAudioDeviceCallback(callback, null)
    }

    private fun changed(devices: Array<out AudioDeviceInfo>, connected: Boolean) {
        val bt = devices.firstOrNull { it.isSink && isBluetooth(it.type) } ?: return
        last = Change(connected, bt.productName?.toString().orEmpty(), System.currentTimeMillis())
        listeners.forEach { it() }
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

    fun time(at: Long): String = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(at))
}
