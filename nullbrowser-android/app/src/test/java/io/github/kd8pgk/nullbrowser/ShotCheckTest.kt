package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShotCheckTest {
    private fun pdf(pages: Int): ByteArray {
        val body = "%PDF-1.4\n" + "<</Type /Page /Parent 2 0 R>>\n".repeat(pages) + " ".repeat(2000) + "\n%%EOF\n"
        return body.toByteArray(Charsets.ISO_8859_1)
    }

    @Test
    fun aPdfMadeByUsPasses() {
        val b = pdf(2)
        val r = ShotCheck.check(b, ShotCheck.sha256(b))
        assertTrue(r.ok)
        assertEquals(2, r.pages)
    }

    @Test
    fun aChangedFileIsRefused() {
        val b = pdf(1)
        val sha = ShotCheck.sha256(b)
        val changed = b.copyOf()
        changed[10] = (changed[10].toInt() xor 1).toByte()
        val r = ShotCheck.check(changed, sha)
        assertFalse(r.ok)
        assertTrue(r.reason.contains("changed"))
    }

    @Test
    fun noRecordedHashIsRefused() {
        assertFalse(ShotCheck.check(pdf(1), "").ok)
    }

    @Test
    fun aProgramDressedAsAPdfIsRefused() {
        val mz = "MZ".toByteArray() + ByteArray(4096)
        assertTrue(ShotCheck.check(mz, ShotCheck.sha256(mz)).reason.contains("start like a PDF"))
    }

    @Test
    fun emptyAndHugeAreRefused() {
        assertFalse(ShotCheck.check(ByteArray(0), "x").ok)
        assertFalse(ShotCheck.check(ByteArray(10), "x").ok)
    }

    @Test
    fun aPdfWithNoPageIsRefused() {
        val b = ("%PDF-1.4\n/Type /Pages\n" + " ".repeat(2000) + "\n%%EOF\n").toByteArray(Charsets.ISO_8859_1)
        assertTrue(ShotCheck.check(b, ShotCheck.sha256(b)).reason.contains("no readable page"))
    }

    @Test
    fun theNameHasNoSiteAndTheDateOnly() {
        val name = ShotCheck.downloadName(1_700_000_000_000L)
        assertTrue(Regex("^Null-Browser-\\d{4}-\\d{2}-\\d{2}-\\d{6}\\.pdf$").matches(name))
    }

    @Test
    fun aTakenNameGetsANumberAndNeverOverwrites() {
        val taken = setOf("a.pdf", "a-2.pdf")
        assertEquals("a-3.pdf", ShotCheck.uniqueName("a.pdf") { taken.contains(it) })
        assertEquals("b.pdf", ShotCheck.uniqueName("b.pdf") { false })
    }
}
