package io.github.kd8pgk.nodetalker

import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

data class PttSettings(val mode: String = "hold", val guardSec: Int = 60, val gap: Boolean = true) {
    val tap: Boolean
        get() = mode == "tap"

    companion object {
        val GUARDS = setOf(30, 60, 90, 120, 180)
    }
}

enum class PttState { OFF, READY, KEYING, TALKING }

class Tick(val text: String, val warn: Boolean, val expired: Boolean)

class PttRules(private val now: () -> Long) {
    var settings = PttSettings()
    var totSec = 120.0
    var busy = ""
    var talking = false
    var keyed = false
    var keyedAt = 0L
    private var rxSeenAt = NEVER
    private var rxLocalAt = NEVER
    private var rxStatusOn = false
    private var ownUnkeyAt = NEVER
    private var warned = false

    fun begin() {
        talking = true
        keyed = false
        warned = false
    }

    fun end() {
        if (talking) ownUnkeyAt = now()
        talking = false
        keyed = false
    }

    fun sinceOwnUnkey(): Long = now() - ownUnkeyAt

    fun ownRecent(t: Long = now()): Boolean = talking || keyed || t - ownUnkeyAt < OWN_TX_IGNORE_MS

    fun busyFrom(tx: TxState?): String {
        if (tx == null || !tx.keyed || talking || keyed || sinceOwnUnkey() <= BUSY_AFTER_OWN_MS) return ""
        return "Busy: ${tx.who} ${fmtSecs(tx.secs)}"
    }

    fun rxStatus(on: Boolean) {
        val t = now()
        if (on && !ownRecent(t)) {
            rxStatusOn = true
            return
        }
        if (!rxStatusOn) return
        rxStatusOn = false
        if (t - rxLocalAt > RX_LOCAL_TRUST_MS && !ownRecent(t)) rxSeenAt = max(rxSeenAt, t - RX_HOLD_MS)
    }

    private fun rxRef(): Long {
        val t = now()
        return if (rxStatusOn && t - rxLocalAt > RX_LOCAL_TRUST_MS) t else rxSeenAt
    }

    fun gapLeft(): Long = if (settings.gap) max(0L, RX_GAP_MS - (now() - rxRef())) else 0L

    fun gapDigit(): String {
        val left = gapLeft()
        val since = now() - rxRef()
        return if (left > 0 && since >= RX_QUIET_MS) min(3L, left / 1000).toString() else ""
    }

    fun guardOn(): Boolean = settings.tap

    fun guardSecs(): Int = min(settings.guardSec.toDouble(), totSec).toInt()

    fun label(state: PttState): String = when {
        state == PttState.TALKING -> if (settings.tap) "TALKING · tap to stop" else "TALKING"
        state == PttState.KEYING -> "Keying..."
        busy.isNotEmpty() -> busy
        gapLeft() > 0 -> "Wait..."
        settings.tap -> "Tap to talk"
        else -> "Hold to talk"
    }

    fun waitText(): String = "Waiting after receive: talk in ${ceil(gapLeft() / 1000.0).toInt()} s."

    fun tick(): Tick? {
        if (!keyed) return null
        val secs = (now() - keyedAt) / 1000.0
        if (!guardOn()) return Tick("${fmtSecs(secs)} / ${fmtSecs(totSec)}", false, false)
        val left = guardSecs() - secs
        val warn = left <= GUARD_WARN_SEC && !warned
        if (warn) warned = true
        return Tick(fmtSecs(max(0.0, ceil(left))), warn, left <= 0)
    }

    fun guardText(): String = "Guard timer: unkeyed after ${fmtSecs(guardSecs().toDouble())}."

    companion object {
        const val NEVER = -1_000_000_000L
        const val RX_GAP_MS = 4000L
        const val RX_QUIET_MS = 300L
        const val OWN_TX_IGNORE_MS = 2500L
        const val BUSY_AFTER_OWN_MS = 2500L
        const val RX_LOCAL_TRUST_MS = 2000L
        const val RX_HOLD_MS = 600L
        const val GUARD_WARN_SEC = 10
        const val TAP_IGNORE_MS = 500L

        fun fmtSecs(s: Double): String {
            val t = max(0, floor(s).toInt())
            return "${t / 60}:${(t % 60).toString().padStart(2, '0')}"
        }

        fun denied(why: String): String = when (why) {
            "busy" -> "The node is busy (someone is talking). Try again when it is quiet."
            "in-use" -> "Someone else is transmitting from Node Talker."
            "not-ready" -> "Node 1921 is not set up yet (Setup tab)."
            "not-linked" ->
                "Node 1921 is not linked to the node yet. Restart Asterisk once after adding it; Node Talker relinks it within 20 s."
            else -> "Refused: $why"
        }

        fun unkeyed(why: String, secs: Double): String = when (why) {
            "timeout" -> "Time-out: transmission stopped after ${fmtSecs(secs)}. Release and press again."
            "deadman" -> "Audio stopped reaching the node, so it unkeyed."
            else -> ""
        }
    }
}
