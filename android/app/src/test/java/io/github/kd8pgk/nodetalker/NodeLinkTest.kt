package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeLinkTest {
    private val pin = "AA:BB"
    private val other = "CC:DD"

    private fun fakes(vararg pairs: Pair<String, List<String>>): (String) -> List<String> {
        val m = pairs.toMap()
        return { m[it] ?: emptyList() }
    }

    private fun certs(vararg pairs: Pair<String, String>): (String, Int) -> String? {
        val m = pairs.toMap()
        return { ip, _ -> m[ip] }
    }

    @Test
    fun candidates_are_the_name_then_the_last_address_without_repeats() {
        assertEquals(listOf("pi.local", "10.0.0.5"), NodeLink.candidates("pi.local", "10.0.0.5"))
        assertEquals(listOf("10.0.0.5"), NodeLink.candidates("10.0.0.5", "10.0.0.5"))
        assertEquals(listOf("pi.local"), NodeLink.candidates("pi.local", ""))
        assertEquals(emptyList<String>(), NodeLink.candidates("", ""))
    }

    @Test
    fun identity_is_only_checked_for_https_nodes_with_a_pin() {
        assertTrue(NodeLink.needsIdentity(true, pin))
        assertFalse(NodeLink.needsIdentity(true, ""))
        assertFalse(NodeLink.needsIdentity(false, pin))
    }

    @Test
    fun the_name_wins_when_it_answers_with_the_pinned_certificate() {
        val f = NodeLink.locate(
            "pi.local", "10.0.0.5", 8993, pin,
            fakes("pi.local" to listOf("10.0.0.7"), "10.0.0.5" to listOf("10.0.0.5")),
            certs("10.0.0.7" to pin, "10.0.0.5" to pin),
        )
        assertEquals("pi.local", f!!.host)
        assertEquals("10.0.0.7", f.ip)
    }

    @Test
    fun the_last_address_is_used_when_the_name_does_not_resolve() {
        val f = NodeLink.locate(
            "pi.local", "10.0.0.5", 8993, pin,
            fakes("10.0.0.5" to listOf("10.0.0.5")),
            certs("10.0.0.5" to pin),
        )
        assertEquals("10.0.0.5", f!!.host)
        assertEquals("10.0.0.5", f.ip)
    }

    @Test
    fun the_last_address_is_used_when_the_name_answers_with_no_handshake() {
        val f = NodeLink.locate(
            "pi.local", "10.0.0.5", 8993, pin,
            fakes("pi.local" to listOf("10.0.0.7"), "10.0.0.5" to listOf("10.0.0.5")),
            certs("10.0.0.5" to pin),
        )
        assertEquals("10.0.0.5", f!!.ip)
    }

    @Test
    fun a_different_certificate_at_the_name_is_not_trusted() {
        val f = NodeLink.locate(
            "pi.local", "10.0.0.5", 8993, pin,
            fakes("pi.local" to listOf("10.0.0.9"), "10.0.0.5" to listOf("10.0.0.5")),
            certs("10.0.0.9" to other, "10.0.0.5" to pin),
        )
        assertEquals("10.0.0.5", f!!.ip)
        assertEquals("10.0.0.5", f.host)
    }

    @Test
    fun a_different_certificate_at_the_last_address_is_not_trusted() {
        val f = NodeLink.locate(
            "pi.local", "10.0.0.5", 8993, pin,
            fakes("pi.local" to listOf("10.0.0.7"), "10.0.0.5" to listOf("10.0.0.5")),
            certs("10.0.0.7" to pin, "10.0.0.5" to other),
        )
        assertEquals("10.0.0.7", f!!.ip)
        assertEquals("pi.local", f.host)
    }

    @Test
    fun the_second_address_of_a_name_is_tried() {
        val f = NodeLink.locate(
            "pi.local", "", 8993, pin,
            fakes("pi.local" to listOf("10.0.0.7", "10.0.0.8")),
            certs("10.0.0.8" to pin),
        )
        assertEquals("10.0.0.8", f!!.ip)
    }

    @Test
    fun nothing_is_found_when_no_candidate_has_the_pinned_certificate() {
        val f = NodeLink.locate(
            "pi.local", "10.0.0.5", 8993, pin,
            fakes("pi.local" to listOf("10.0.0.7")),
            certs("10.0.0.7" to other),
        )
        assertNull(f)
    }

    @Test
    fun the_fingerprint_is_the_sha256_of_the_certificate_as_upper_hex_pairs() {
        assertEquals(
            "E3:B0:C4:42:98:FC:1C:14:9A:FB:F4:C8:99:6F:B9:24:27:AE:41:E4:64:9B:93:4C:A4:95:99:1B:78:52:B8:55",
            NodeLink.fingerprint(ByteArray(0)),
        )
    }
}
