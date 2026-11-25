package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SniffTest {
    @Test
    fun classifiesByMimeThenByName() {
        assertEquals(Kind.PDF, classify("application/pdf", "x.bin"))
        assertEquals(Kind.AUDIO, classify("audio/mpeg; charset=x", "a"))
        assertEquals(Kind.VIDEO, classify("video/mp4", "a"))
        assertEquals(Kind.AUDIO, classify("application/octet-stream", "talk.MP3"))
        assertEquals(Kind.VIDEO, classify("", "film.webm"))
        assertNull(classify("application/octet-stream", "setup.exe"))
        assertNull(classify("application/zip", "x.pdf"))
        assertNull(classify("text/html", "x.pdf"))
    }

    @Test
    fun contentMustMatchItsClaimedType() {
        val pdf = "%PDF-1.7\n...".toByteArray()
        val mp3 = byteArrayOf(0x49, 0x44, 0x33, 4, 0, 0)
        val frame = byteArrayOf(0xff.toByte(), 0xfb.toByte(), 0x90.toByte(), 0x00)
        val mp4 = byteArrayOf(0, 0, 0, 0x18) + "ftypisom".toByteArray() + ByteArray(8)
        val m4a = byteArrayOf(0, 0, 0, 0x18) + "ftypM4A ".toByteArray() + ByteArray(8)
        val webm = byteArrayOf(0x1a, 0x45, 0xdf.toByte(), 0xa3.toByte(), 1, 2)
        val wav = "RIFF".toByteArray() + ByteArray(4) + "WAVEfmt ".toByteArray()
        val html = "<!doctype html><script>".toByteArray()

        assertTrue(contentMatches(Kind.PDF, pdf))
        assertFalse(contentMatches(Kind.PDF, html))
        assertFalse(contentMatches(Kind.PDF, mp4))
        for (b in listOf(mp3, frame, m4a, wav, webm, mp4)) assertTrue(contentMatches(Kind.AUDIO, b))
        for (b in listOf(mp4, webm)) assertTrue(contentMatches(Kind.VIDEO, b))
        assertFalse(contentMatches(Kind.VIDEO, mp3))
    }

    @Test
    fun safeNameStripsDangerousCharacters() {
        assertEquals("a_b", safeName("a/b"))
        assertEquals("file", safeName(""))
        assertEquals("file", safeName(null))
        assertEquals("report.pdf", safeName("report.pdf"))
        assertEquals("_.._x", safeName("../../x"))
    }

    @Test
    fun humanSizeIsReadable() {
        assertEquals("", humanSize(0))
        assertEquals("500 bytes", humanSize(500))
        assertEquals("2 KB", humanSize(2048))
        assertEquals("1.0 MB", humanSize(1024L * 1024))
    }
}
