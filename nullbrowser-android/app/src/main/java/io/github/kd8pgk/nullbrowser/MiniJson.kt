package io.github.kd8pgk.nullbrowser

object MiniJson {
    private const val MAX_DEPTH = 24
    private const val MAX_LENGTH = 2_000_000

    fun parse(text: String?): Any? {
        if (text == null || text.length > MAX_LENGTH) return null
        val p = Parser(text)
        return try {
            p.skip()
            val v = p.value(0)
            p.skip()
            if (p.i != text.length) null else v
        } catch (_: IllegalStateException) {
            null
        }
    }

    fun unwrapString(json: String?): String? = parse(json) as? String

    @Suppress("UNCHECKED_CAST")
    fun map(v: Any?): Map<String, Any?>? = v as? Map<String, Any?>

    @Suppress("UNCHECKED_CAST")
    fun list(v: Any?): List<Any?>? = v as? List<Any?>

    fun text(v: Any?, max: Int): String = when (v) {
        null -> ""
        is String -> v.take(max)
        is Double -> if (v == Math.floor(v) && Math.abs(v) < 1e15) v.toLong().toString() else v.toString()
        is Boolean -> v.toString()
        else -> ""
    }

    fun number(v: Any?): Double = when (v) {
        is Double -> v
        is String -> v.toDoubleOrNull() ?: 0.0
        is Boolean -> if (v) 1.0 else 0.0
        else -> 0.0
    }

    private class Parser(val s: String) {
        var i = 0

        fun skip() {
            while (i < s.length && (s[i] == ' ' || s[i] == '\n' || s[i] == '\r' || s[i] == '\t')) i++
        }

        fun fail(): Nothing = throw IllegalStateException("bad json")

        fun value(depth: Int): Any? {
            if (depth > MAX_DEPTH || i >= s.length) fail()
            return when (val c = s[i]) {
                '{' -> obj(depth)
                '[' -> arr(depth)
                '"' -> str()
                't' -> lit("true", true)
                'f' -> lit("false", false)
                'n' -> lit("null", null)
                else -> if (c == '-' || c in '0'..'9') num() else fail()
            }
        }

        fun lit(word: String, v: Any?): Any? {
            if (!s.startsWith(word, i)) fail()
            i += word.length
            return v
        }

        fun num(): Double {
            val start = i
            if (s[i] == '-') i++
            while (i < s.length && (s[i] in '0'..'9' || s[i] == '.' || s[i] == 'e' || s[i] == 'E' || s[i] == '+' || s[i] == '-')) i++
            return s.substring(start, i).toDoubleOrNull() ?: fail()
        }

        fun str(): String {
            i++
            val b = StringBuilder()
            while (true) {
                if (i >= s.length) fail()
                val c = s[i++]
                when (c) {
                    '"' -> return b.toString()
                    '\\' -> {
                        if (i >= s.length) fail()
                        when (val e = s[i++]) {
                            '"', '\\', '/' -> b.append(e)
                            'b' -> b.append('\b')
                            'f' -> b.append('\u000c')
                            'n' -> b.append('\n')
                            'r' -> b.append('\r')
                            't' -> b.append('\t')
                            'u' -> {
                                if (i + 4 > s.length) fail()
                                b.append(s.substring(i, i + 4).toIntOrNull(16)?.toChar() ?: fail())
                                i += 4
                            }
                            else -> fail()
                        }
                    }
                    else -> b.append(c)
                }
            }
        }

        fun arr(depth: Int): List<Any?> {
            i++
            val out = ArrayList<Any?>()
            skip()
            if (i < s.length && s[i] == ']') {
                i++
                return out
            }
            while (true) {
                skip()
                out.add(value(depth + 1))
                skip()
                if (i >= s.length) fail()
                if (s[i] == ',') {
                    i++
                    continue
                }
                if (s[i] == ']') {
                    i++
                    return out
                }
                fail()
            }
        }

        fun obj(depth: Int): Map<String, Any?> {
            i++
            val out = LinkedHashMap<String, Any?>()
            skip()
            if (i < s.length && s[i] == '}') {
                i++
                return out
            }
            while (true) {
                skip()
                if (i >= s.length || s[i] != '"') fail()
                val k = str()
                skip()
                if (i >= s.length || s[i] != ':') fail()
                i++
                skip()
                out[k] = value(depth + 1)
                skip()
                if (i >= s.length) fail()
                if (s[i] == ',') {
                    i++
                    continue
                }
                if (s[i] == '}') {
                    i++
                    return out
                }
                fail()
            }
        }
    }
}
