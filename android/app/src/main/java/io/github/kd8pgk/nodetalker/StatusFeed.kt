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
    @Volatile private var gen = 0
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
            val mine = ++gen
            thread = Thread({ loop(n, mine) }, "nt-status").also { it.start() }
        } else if (!want && active) {
            active = false
            gen++
            synchronized(lock) { lock.notifyAll() }
            thread?.interrupt()
            thread = null
        }
    }

    private fun loop(n: Node, mine: Int) {
        val api = NodeApi(n)
        while (active && gen == mine) {
            try {
                val s = NodeStatus.parse(api.status())
                ui.post { if (gen == mine) listeners.forEach { it.onStatus(s) } }
            } catch (e: IOException) {
                ui.post { if (gen == mine) listeners.forEach { it.onLost() } }
            } catch (e: RuntimeException) {
                ui.post { if (gen == mine) listeners.forEach { it.onLost() } }
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
