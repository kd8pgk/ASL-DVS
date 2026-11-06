package io.github.kd8pgk.nodetalker

import java.util.Calendar

class NetLog {
    private val entries = ArrayList<String>()

    fun add(from: String, to: String, atMs: Long) {
        entries.add(entry(from, to, atMs))
        trim()
    }

    fun take(): List<String> {
        val out = entries.toList()
        entries.clear()
        return out
    }

    fun restore(old: List<String>) {
        entries.addAll(0, old)
        trim()
    }

    fun size(): Int = entries.size

    fun clear() {
        entries.clear()
    }

    private fun trim() {
        while (entries.size > MAX) entries.removeAt(0)
    }

    companion object {
        const val MAX = 8

        fun entry(from: String, to: String, atMs: Long): String {
            val c = Calendar.getInstance().apply { timeInMillis = atMs }
            return String.format(
                "%s>%s %02d:%02d:%02d", from, to,
                c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE), c.get(Calendar.SECOND)
            )
        }
    }
}
