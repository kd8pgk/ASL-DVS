package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BluetoothJsonTest {
    private fun snap(devices: List<Bluetooth.Dev>, last: Boolean? = null) = Bluetooth.Snap(
        true, true, devices, null, false, true, true, "normal", 5, 15, 3, 7, last, "Buds \"X\"", 1000L,
    )

    @Test
    fun quote_escapes_quotes_backslashes_and_control_characters() {
        assertEquals("\"a\\\"b\\\\c d\"", Bluetooth.quote("a\"b\\c\nd"))
    }

    @Test
    fun no_devices_gives_an_empty_list_and_null_fields() {
        val j = Bluetooth.json(snap(emptyList()))
        assertTrue(j, j.contains("\"devices\":[]"))
        assertTrue(j, j.contains("\"comm\":null"))
        assertTrue(j, j.contains("\"last\":null"))
        assertTrue(j, j.contains("\"media\":{\"now\":5,\"max\":15}"))
    }

    @Test
    fun a_device_lists_its_rates_channels_and_encodings() {
        val d = Bluetooth.Dev("a2dp", "Speaker", 7, true, false, listOf(44100, 48000), listOf(2), listOf("pcm16"))
        val j = Bluetooth.json(snap(listOf(d), true))
        assertTrue(j, j.contains("\"kind\":\"a2dp\""))
        assertTrue(j, j.contains("\"rates\":[44100,48000]"))
        assertTrue(j, j.contains("\"encodings\":[\"pcm16\"]"))
        assertTrue(j, j.contains("\"last\":{\"connected\":true,\"name\":\"Buds \\\"X\\\"\",\"at\":1000}"))
    }
}

class BluetoothDetailJsonTest {
    @Test
    fun without_the_permission_only_granted_false_is_sent() {
        assertEquals("{\"granted\":false}", Bluetooth.detailJson(null))
    }

    @Test
    fun detail_lists_the_adapter_paired_devices_and_profiles() {
        val d = Bluetooth.Detail(
            true, "on", "Phone \"A\"", "supported", "not_supported",
            listOf(Bluetooth.Bonded("Buds", "audio_video", "dual")),
            listOf(Bluetooth.Prof("a2dp", listOf("Buds")), Bluetooth.Prof("headset", emptyList()), Bluetooth.Prof("le_audio", null)),
        )
        val j = Bluetooth.detailJson(d)
        assertTrue(j, j.startsWith("{\"granted\":true,\"adapter\":{\"on\":true,\"state\":\"on\",\"name\":\"Phone \\\"A\\\"\""))
        assertTrue(j, j.contains("\"le_audio\":\"supported\",\"le_broadcast\":\"not_supported\""))
        assertTrue(j, j.contains("\"bonded\":[{\"name\":\"Buds\",\"class\":\"audio_video\",\"link\":\"dual\"}]"))
        assertTrue(j, j.contains("{\"name\":\"a2dp\",\"devices\":[\"Buds\"]}"))
        assertTrue(j, j.contains("{\"name\":\"headset\",\"devices\":[]}"))
        assertTrue(j, j.contains("{\"name\":\"le_audio\",\"devices\":null}"))
    }
}
