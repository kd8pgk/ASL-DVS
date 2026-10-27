package io.github.kd8pgk.nodetalker

class TabRouter(private val io: Io) {
    interface Io {
        fun clickPage(name: String)
        fun select(name: String)
        fun show(name: String)
        fun hide(name: String)
        fun nativeAllowed(name: String): Boolean
    }

    var pageTab = ""
        private set

    var native: String? = null
        private set

    private var parking = false

    private fun nativeOk(name: String) = pageTab.isNotEmpty() && name in NATIVE && io.nativeAllowed(name)

    fun pick(name: String) {
        parking = false
        if (nativeOk(name)) {
            activate(name)
            return
        }
        deactivate()
        io.select(name)
        pageTab = name
        io.clickPage(name)
    }

    fun onPage(name: String) {
        if (parking && name == PARK) {
            parking = false
            return
        }
        pageTab = name
        if (name.isEmpty()) {
            deactivate()
            io.select("")
            return
        }
        if (nativeOk(name)) {
            activate(name)
            return
        }
        deactivate()
        io.select(name)
    }

    fun reevaluate() {
        val on = native
        if (on == null) {
            if (nativeOk(pageTab)) activate(pageTab)
        } else if (!nativeOk(on)) {
            deactivate()
            pick(on)
        }
    }

    fun reset() {
        deactivate()
        pageTab = ""
        parking = false
        io.select("")
    }

    private fun activate(name: String) {
        if (native == name) return
        val was = native
        if (was != null) {
            io.hide(was)
        } else if (pageTab != PARK) {
            parking = true
            pageTab = PARK
            io.clickPage(PARK)
        }
        native = name
        io.show(name)
        io.select(name)
    }

    private fun deactivate() {
        parking = false
        val was = native ?: return
        native = null
        io.hide(was)
    }

    companion object {
        const val PARK = "setup"
        val NATIVE = setOf("connect", "listen")
    }
}
