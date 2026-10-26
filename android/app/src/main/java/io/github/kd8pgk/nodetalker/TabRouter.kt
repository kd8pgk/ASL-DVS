package io.github.kd8pgk.nodetalker

class TabRouter(private val io: Io) {
    interface Io {
        fun clickPage(name: String)
        fun select(name: String)
        fun showNative()
        fun hideNative()
        fun nativeAllowed(): Boolean
    }

    var pageTab = ""
        private set

    var nativeOn = false
        private set

    private var parking = false

    private fun nativeOk() = pageTab.isNotEmpty() && io.nativeAllowed()

    fun pick(name: String) {
        parking = false
        if (name == "listen" && nativeOk()) {
            activate()
            return
        }
        deactivate()
        io.select(name)
        pageTab = name
        io.clickPage(name)
    }

    fun onPage(name: String) {
        if (parking && name == "connect") {
            parking = false
            return
        }
        pageTab = name
        if (name.isEmpty()) {
            deactivate()
            io.select("")
            return
        }
        if (name == "listen" && nativeOk()) {
            activate()
            return
        }
        deactivate()
        io.select(name)
    }

    fun reevaluate() {
        if (!nativeOn && pageTab == "listen" && nativeOk()) {
            activate()
        } else if (nativeOn && !nativeOk()) {
            deactivate()
            pick("listen")
        }
    }

    fun reset() {
        deactivate()
        pageTab = ""
        parking = false
        io.select("")
    }

    private fun activate() {
        if (nativeOn) return
        nativeOn = true
        if (pageTab == "listen") {
            parking = true
            pageTab = "connect"
            io.clickPage("connect")
        }
        io.showNative()
        io.select("listen")
    }

    private fun deactivate() {
        parking = false
        if (!nativeOn) return
        nativeOn = false
        io.hideNative()
    }
}
