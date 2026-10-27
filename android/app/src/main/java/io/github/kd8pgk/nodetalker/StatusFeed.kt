package io.github.kd8pgk.nodetalker

import android.os.Handler
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList

class StatusFeed(private val ui: Handler, private val node: () -> Node) {
    interface Listener {
        fun onStatus(s: NodeStatus)

        fun onLost()
    }

    private val listeners = CopyOnWriteArrayList<Listener>()
    private val lock = Object()
    private var kick = false
    private var resumed = false
    @Volatile private var active = false
    private var thread: Thread? = null

    fun add(l: Listener) {
        if (!listeners.contains(l)) listeners.add(l)
        update()
    }

    fun remove(l: Listener) {
        listeners.remove(l)
        update()
    }

    fun setResumed(on: Boolean) {
        resumed = on
        update()
    }

    fun pokeAfter(ms: Long) {
        ui.postDelayed({ poke() }, ms)
    }

    fun poke() {
        synchronized(lock) {
            kick = true
            lock.notifyAll()
        }
    }

    private fun update() {
        val want = resumed && listeners.isNotEmpty()
        if (want && !active) {
            active = true
            val n = node()
            thread = Thread({ loop(n) }, "nt-status").also { it.start() }
        } else if (!want && active) {
            active = false
            synchronized(lock) { lock.notifyAll() }
            thread?.interrupt()
            thread = null
        }
    }

    private fun loop(n: Node) {
        val api = NodeApi(n)
        while (active) {
            try {
                val s = NodeStatus.parse(api.status())
                ui.post { listeners.forEach { it.onStatus(s) } }
            } catch (e: IOException) {
                ui.post { listeners.forEach { it.onLost() } }
            }
            try {
                synchronized(lock) {
                    if (!kick) lock.wait(POLL_MS)
                    kick = false
                }
            } catch (e: InterruptedException) {
                return
            }
        }
    }

    companion object {
        private const val POLL_MS = 1500L
    }
}
