package io.github.kd8pgk.nullbrowser

enum class Kind { PDF, AUDIO, VIDEO }

const val MAX_BYTES = 512L * 1024 * 1024

private val EXT_KIND = mapOf(
    "pdf" to Kind.PDF,
    "mp3" to Kind.AUDIO, "m4a" to Kind.AUDIO, "aac" to Kind.AUDIO, "ogg" to Kind.AUDIO,
    "oga" to Kind.AUDIO, "opus" to Kind.AUDIO, "flac" to Kind.AUDIO, "wav" to Kind.AUDIO,
    "mp4" to Kind.VIDEO, "m4v" to Kind.VIDEO, "webm" to Kind.VIDEO, "mkv" to Kind.VIDEO,
    "mov" to Kind.VIDEO, "ogv" to Kind.VIDEO,
)

fun kindOfMime(mime: String?): Kind? {
    val m = (mime ?: "").lowercase().substringBefore(';').trim()
    return when {
        m == "application/pdf" || m == "application/x-pdf" -> Kind.PDF
        m.startsWith("audio/") -> Kind.AUDIO
        m.startsWith("video/") -> Kind.VIDEO
        else -> null
    }
}

fun kindOfName(name: String?): Kind? {
    val ext = (name ?: "").substringAfterLast('.', "").lowercase()
    return EXT_KIND[ext]
}

fun classify(mime: String?, name: String?): Kind? {
    kindOfMime(mime)?.let { return it }
    val m = (mime ?: "").lowercase().substringBefore(';').trim()
    val generic = m.isEmpty() || m == "application/octet-stream" || m == "binary/octet-stream"
    return if (generic) kindOfName(name) else null
}

private fun at(b: ByteArray, i: Int, s: String): Boolean {
    if (b.size < i + s.length) return false
    for (j in s.indices) if ((b[i + j].toInt() and 0xff) != s[j].code) return false
    return true
}

private fun sniffRaw(b: ByteArray): String? {
    if (at(b, 0, "%PDF-")) return "pdf"
    if (b.size >= 4 && (b[0].toInt() and 0xff) == 0x1a && (b[1].toInt() and 0xff) == 0x45 &&
        (b[2].toInt() and 0xff) == 0xdf && (b[3].toInt() and 0xff) == 0xa3
    ) return "av"
    if (at(b, 4, "ftyp")) {
        val brand = if (b.size >= 12) String(b, 8, 4, Charsets.ISO_8859_1) else ""
        return if (brand == "M4A " || brand == "M4B " || brand == "M4P ") "audio" else "av"
    }
    if (at(b, 0, "OggS")) return "av"
    if (at(b, 0, "fLaC")) return "audio"
    if (at(b, 0, "RIFF") && at(b, 8, "WAVE")) return "audio"
    if (at(b, 0, "ID3")) return "audio"
    if (b.size >= 2 && (b[0].toInt() and 0xff) == 0xff && (b[1].toInt() and 0xe0) == 0xe0) return "audio"
    if (at(b, 4, "moov") || at(b, 4, "mdat") || at(b, 4, "free") || at(b, 4, "wide")) return "av"
    return null
}

fun contentMatches(kind: Kind, head: ByteArray): Boolean {
    val s = sniffRaw(head) ?: return false
    return when (kind) {
        Kind.PDF -> s == "pdf"
        Kind.AUDIO -> s == "audio" || s == "av"
        Kind.VIDEO -> s == "av"
    }
}

fun safeName(name: String?): String {
    var n = (name ?: "").replace(Regex("[\\\\/\\x00]"), "_").trimStart('.')
    n = n.replace(Regex("[^\\w.\\- ()\\[\\]]"), "_")
    if (n.length > 120) n = n.takeLast(120)
    return n.ifEmpty { "file" }
}

fun humanSize(bytes: Long): String {
    if (bytes <= 0) return ""
    if (bytes < 1024) return "$bytes bytes"
    if (bytes < 1024 * 1024) return "${bytes / 1024} KB"
    if (bytes < 1024L * 1024 * 1024) return String.format("%.1f MB", bytes / 1024.0 / 1024.0)
    return String.format("%.1f GB", bytes / 1024.0 / 1024.0 / 1024.0)
}

fun appLabel(kind: Kind): String = when (kind) {
    Kind.PDF -> "your PDF viewer"
    Kind.AUDIO -> "your music player"
    Kind.VIDEO -> "your video player"
}

fun kindLabel(kind: Kind): String = when (kind) {
    Kind.PDF -> "a PDF"
    Kind.AUDIO -> "audio"
    Kind.VIDEO -> "video"
}

fun withExtension(name: String, kind: Kind, mimeExt: String?): String {
    if (kindOfName(name) == kind) return name
    val ext = mimeExt?.lowercase()?.takeIf { EXT_KIND[it] == kind } ?: when (kind) {
        Kind.PDF -> "pdf"
        Kind.AUDIO -> "mp3"
        Kind.VIDEO -> "mp4"
    }
    return "$name.$ext"
}
