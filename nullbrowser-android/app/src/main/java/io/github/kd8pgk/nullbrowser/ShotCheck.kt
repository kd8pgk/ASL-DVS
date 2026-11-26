package io.github.kd8pgk.nullbrowser

import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object ShotCheck {
    const val MAX_BYTES = 64 * 1024 * 1024
    const val MIN_BYTES = 1024
    const val MAX_PAGES = 500

    class Result(val ok: Boolean, val reason: String = "", val pages: Int = 0)

    fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    fun check(bytes: ByteArray, recordedSha: String): Result {
        if (bytes.size < MIN_BYTES) return Result(false, "the screenshot is too small to be a PDF")
        if (bytes.size > MAX_BYTES) return Result(false, "the screenshot is too big")
        if (String(bytes, 0, 5, Charsets.ISO_8859_1) != "%PDF-") return Result(false, "the file does not start like a PDF")
        val tail = String(bytes, maxOf(0, bytes.size - 1024), minOf(1024, bytes.size), Charsets.ISO_8859_1)
        if (!tail.contains("%%EOF")) return Result(false, "the file does not end like a PDF")
        val pages = Regex("/Type\\s*/Page(?!s)").findAll(String(bytes, Charsets.ISO_8859_1)).count()
        if (pages < 1 || pages > MAX_PAGES) return Result(false, "the screenshot has no readable page")
        if (recordedSha.isEmpty() || sha256(bytes) != recordedSha) return Result(false, "the file changed after it was made")
        return Result(true, "", pages)
    }

    fun downloadName(millis: Long): String {
        val stamp = SimpleDateFormat("yyyy-MM-dd-HHmmss", Locale.US).format(Date(millis))
        return "Null-Browser-$stamp.pdf"
    }

    fun uniqueName(name: String, exists: (String) -> Boolean): String? {
        if (!exists(name)) return name
        val dot = name.lastIndexOf('.')
        val stem = if (dot > 0) name.substring(0, dot) else name
        val ext = if (dot > 0) name.substring(dot) else ""
        for (i in 2 until 1000) {
            val next = "$stem-$i$ext"
            if (!exists(next)) return next
        }
        return null
    }
}
