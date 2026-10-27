package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.LayerDrawable
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.text.style.TypefaceSpan
import android.util.TypedValue
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.Executors
import kotlin.math.ceil
import kotlin.math.min
import kotlin.math.sin

class ListenTab(private val act: Activity, private val root: View, private val host: Host) : StatusFeed.Listener {
    interface Host {
        val node: Node
        val feed: StatusFeed
        fun readPage(js: String, done: (String?) -> Unit)
        fun openTalk(): Boolean
        fun startListen(): Boolean
    }

    private val ui = Handler(Looper.getMainLooper())
    private val rules = PttRules { SystemClock.elapsedRealtime() }
    private val d = act.resources.displayMetrics.density
    private val vibrator = act.getSystemService(Vibrator::class.java)

    private val listenBtn = root.findViewById<Button>(R.id.listen_btn)
    private val vol = root.findViewById<SeekBar>(R.id.vol)
    private val stNode = root.findViewById<TextView>(R.id.st_node)
    private val dotFeed = root.findViewById<DotView>(R.id.dot_feed)
    private val stFeed = root.findViewById<TextView>(R.id.st_feed)
    private val dotRx = root.findViewById<DotView>(R.id.dot_rx)
    private val dotTx = root.findViewById<DotView>(R.id.dot_tx)
    private val stListeners = root.findViewById<TextView>(R.id.st_listeners)
    private val spec = root.findViewById<SpectrumView>(R.id.spec)
    private val meter = root.findViewById<MeterView>(R.id.meter)
    private val stLevel = root.findViewById<TextView>(R.id.st_level)
    private val ptt = root.findViewById<LinearLayout>(R.id.ptt)
    private val pttLabel = root.findViewById<TextView>(R.id.ptt_label)
    private val pttTime = root.findViewById<TextView>(R.id.ptt_time)
    private val mark = root.findViewById<TextView>(R.id.ptt_mark)
    private val pttMsg = root.findViewById<TextView>(R.id.ptt_msg)
    private val pttInfo = root.findViewById<TextView>(R.id.ptt_info)

    private val texts = listOf(
        stNode to 13f, stFeed to 13f, stListeners to 13f, stLevel to 13f, pttLabel to 17f, pttTime to 15f,
        mark to 15f, pttMsg to 14f, pttInfo to 12f, listenBtn to 12.24f,
    )

    private var settings = PageSettings()
    private var status: NodeStatus? = null
    private var pttState = PttState.OFF
    private var shown = false
    private var resumed = false
    private var autoDone = false
    private var tapAt = 0L
    private var guardStop = ""
    private var guardWarn = false
    private var shownLabel = ""
    private var shownDigit = ""
    private var markShown = ""

    private val onListen: () -> Unit = { ui.post { listenChanged() } }
    private val onTalk: (String) -> Unit = { ev -> ui.post { talkEvent(ev) } }
    private val frame = object : Runnable {
        override fun run() {
            if (!active()) return
            frameTick()
            ui.postDelayed(this, FRAME_MS)
        }
    }
    private val tickRun = object : Runnable {
        override fun run() {
            if (!rules.talking) return
            talkTick()
            ui.postDelayed(this, TICK_MS)
        }
    }

    init {
        spec.bind(Listen.spectrum)
        listenBtn.stateListAnimator = null
        listenBtn.setOnClickListener { toggleListen() }
        vol.progress = (Listen.volume * 100).toInt().coerceIn(0, 200)
        vol.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(bar: SeekBar, progress: Int, fromUser: Boolean) {
                Listen.volume = progress / 100f
            }

            override fun onStartTrackingTouch(bar: SeekBar) {}

            override fun onStopTrackingTouch(bar: SeekBar) {}
        })
        ptt.setOnTouchListener { v, e -> pttTouch(v, e) }
        mark.setOnClickListener { markKerchunk() }
        mark.background = round(act.getColor(R.color.amber_bg), act.getColor(R.color.amber), 3, 16)
        applySettings(settings)
        renderListen()
        renderPtt()
    }

    private fun active() = shown && resumed

    fun show() {
        if (shown) return
        shown = true
        root.visibility = View.VISIBLE
        Listen.listeners.add(onListen)
        Talk.listeners.add(onTalk)
        host.feed.add(this)
        host.readPage(PageSettings.READ_JS) { raw ->
            if (!shown) return@readPage
            settings = PageSettings.parse(raw)
            rules.settings = settings.ptt
            applySettings(settings)
            if (!autoDone && settings.auto && !ownListen()) {
                autoDone = true
                host.startListen()
            }
            renderPtt()
        }
        openTalk()
        begin()
    }

    fun hide() {
        if (!shown) return
        shown = false
        root.visibility = View.GONE
        Listen.listeners.remove(onListen)
        Talk.listeners.remove(onTalk)
        host.feed.remove(this)
        ui.removeCallbacks(frame)
    }

    fun resume() {
        resumed = true
        if (shown) begin()
    }

    fun pause() {
        resumed = false
        ui.removeCallbacks(frame)
    }

    fun reset() {
        autoDone = false
        status = null
    }

    fun flash(color: Int, text: String) {
        setPttMsg(color, text)
    }

    fun flashIs(text: String): Boolean = pttMsg.text.toString() == text

    fun micGranted() {
        if (shown) openTalk()
    }

    private fun begin() {
        if (!active()) return
        listenChanged()
        syncTalk()
        ui.removeCallbacks(frame)
        ui.post(frame)
    }

    private fun ownListen() = Listen.state != Listen.OFF && (Listen.nodeId == null || Listen.nodeId == host.node.id)

    private fun talkReady() = Talk.open && Talk.nodeId == host.node.id

    private fun toggleListen() {
        if (ownListen()) Listen.stop(act) else host.startListen()
    }

    private fun listenChanged() {
        renderListen()
        if (rules.talking) return
        if (ownListen()) {
            meter.percent = Spectrum.dbPct(Listen.level)
            stLevel.text = Spectrum.fmtDb(Listen.level)
        } else {
            Listen.spectrum.clear()
            meter.percent = 0.0
        }
    }

    private fun renderListen() {
        val on = ownListen()
        listenBtn.text = act.getString(if (on) R.string.listen_disconnect else R.string.listen_connect)
        val fill = act.getColor(if (on) R.color.stop else R.color.go)
        listenBtn.background = round(fill, fill, 1, 10)
        listenBtn.setTextColor(if (on) Color.WHITE else act.getColor(R.color.go_ink))
    }

    override fun onLost() {
        dotFeed.level = NodeStatus.DOT_ERR
    }

    override fun onStatus(s: NodeStatus) {
        status = s
        stNode.text = s.node.ifEmpty { "(not set)" }
        stListeners.text = "${s.listeners} / ${s.maxListeners}"
        dotFeed.level = s.feedLevel
        stFeed.text = s.feedText
        dotRx.level = if (s.audioActive) NodeStatus.DOT_RX else NodeStatus.DOT_OFF
        dotTx.level = if (s.tx?.keyed == true) NodeStatus.DOT_TX else NodeStatus.DOT_OFF
        if (!rules.talking) {
            stLevel.text = Spectrum.fmtDb(s.peakDb)
            if (!ownListen()) meter.percent = Spectrum.dbPct(s.peakDb)
        }
        mark.visibility = if (s.kcTest) View.VISIBLE else View.GONE
        rules.busy = rules.busyFrom(s.tx)
        rules.rxStatus(s.audioActive || rules.busy.isNotEmpty())
        val tot = s.tx?.tot ?: 0.0
        if (tot > 0) rules.totSec = tot
        pttInfo.text = linkText(s.link)
        renderPtt()
    }

    private fun linkText(k: LinkInfo?): CharSequence {
        if (k == null) return "-"
        if (k.state == "unreachable") return "Node unreachable"
        if (k.state == "none") return "Not connected"
        val b = SpannableStringBuilder()
        if (k.state == "idle" || k.state == "noasl") {
            b.append(k.label)
        } else {
            if (k.mode.isNotEmpty()) {
                val at = b.length
                b.append(k.mode)
                b.setSpan(ForegroundColorSpan(act.getColor(R.color.badge)), at, b.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                b.setSpan(TypefaceSpan("monospace"), at, b.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                b.setSpan(StyleSpan(Typeface.BOLD), at, b.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                b.append(' ')
            }
            b.append(k.label + if (k.state == "linking") " (connecting)" else "")
        }
        if (k.tag.isNotEmpty()) b.append(" · ${k.tag}")
        return b
    }

    private fun frameTick() {
        val on = ownListen() && settings.spectrum
        val digit = rules.gapDigit()
        if (on) {
            spec.running = true
            spec.gapDigit = digit
            spec.tick(SystemClock.elapsedRealtime())
        } else {
            val was = spec.running
            spec.running = false
            if (was || spec.gapDigit != digit) {
                spec.gapDigit = digit
                spec.invalidate()
            }
        }
        if (digit != shownDigit) shownDigit = digit
        if (!rules.talking) {
            val specVisible = settings.spectrum
            val t = if (digit.isNotEmpty() && !specVisible) digit else ""
            if (pttTime.text.toString() != t) pttTime.text = t
        }
        if (rules.label(pttState) != shownLabel) renderPtt()
    }

    private fun applySettings(s: PageSettings) {
        val scale = (s.textPx / PageSettings.DEFAULT_TEXT).toFloat()
        for ((v, base) in texts) v.setTextSize(TypedValue.COMPLEX_UNIT_SP, base * scale)
        val h = (s.pttHeightDp * d).toInt()
        for (v in listOf(ptt, mark)) {
            val lp = v.layoutParams
            if (lp.height != h) {
                lp.height = h
                v.layoutParams = lp
            }
        }
        spec.visibility = if (s.spectrum) View.VISIBLE else View.GONE
    }

    private fun round(fill: Int, stroke: Int, strokeDp: Int, radiusDp: Int) = GradientDrawable().apply {
        setColor(fill)
        setStroke((strokeDp * d).toInt(), stroke)
        cornerRadius = radiusDp * d
    }

    private fun renderPtt() {
        val talking = pttState == PttState.TALKING || pttState == PttState.KEYING
        val label = rules.label(pttState)
        shownLabel = label
        pttLabel.text = label
        val busyIdle = !talking && rules.busy.isNotEmpty()
        val border = when {
            guardWarn -> act.getColor(R.color.amber)
            talking -> act.getColor(R.color.red_line)
            busyIdle -> act.getColor(R.color.amber)
            pttState == PttState.READY -> act.getColor(R.color.accent)
            else -> act.getColor(R.color.line2)
        }
        val body = round(act.getColor(if (talking) R.color.key_talk_bg else R.color.key_bg), border, 3, 16)
        val ringColor = when {
            guardWarn -> Color.argb(46, 244, 192, 78)
            talking -> Color.argb(38, 242, 84, 91)
            else -> 0
        }
        if (ringColor != 0) {
            val ring = GradientDrawable().apply {
                setColor(Color.TRANSPARENT)
                setStroke((6 * d).toInt(), ringColor)
                cornerRadius = 19 * d
            }
            val layers = LayerDrawable(arrayOf(ring, body))
            val out = (3 * d).toInt()
            layers.setLayerInset(0, -out, -out, -out, -out)
            ptt.background = layers
        } else {
            ptt.background = body
        }
        ptt.isEnabled = pttState != PttState.OFF
        ptt.alpha = if (pttState == PttState.OFF) 0.45f else 1f
    }

    private fun setPttMsg(color: Int, text: String) {
        pttMsg.setTextColor(act.getColor(color))
        pttMsg.text = text
        pttInfo.visibility = if (text.isEmpty()) View.VISIBLE else View.INVISIBLE
    }

    private fun pttUi(state: PttState, text: String? = null, color: Int = R.color.text) {
        pttState = state
        renderPtt()
        if (text != null) setPttMsg(color, text)
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun pttTouch(v: View, e: MotionEvent): Boolean {
        if (!v.isEnabled) return false
        if (!settings.ptt.tap) {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> pttDown()
                MotionEvent.ACTION_UP -> {
                    pttUp()
                    v.performClick()
                }
                MotionEvent.ACTION_CANCEL -> pttUp()
            }
            return true
        }
        if (e.actionMasked == MotionEvent.ACTION_DOWN) {
            if (rules.talking) {
                if (SystemClock.elapsedRealtime() - tapAt >= PttRules.TAP_IGNORE_MS) pttUp()
            } else {
                tapAt = SystemClock.elapsedRealtime()
                pttDown()
            }
        } else if (e.actionMasked == MotionEvent.ACTION_UP) {
            v.performClick()
        }
        return true
    }

    private fun openTalk() {
        if (talkReady()) {
            pttUi(PttState.READY, "")
            return
        }
        if (host.openTalk()) pttUi(PttState.OFF, "Opening the talk channel...")
        else pttUi(PttState.OFF, "Allow the microphone for Node Talker (Android asks), then press again.", R.color.amber)
    }

    private fun syncTalk() {
        if (talkReady() && pttState == PttState.OFF) pttUi(PttState.READY, "")
        else if (!talkReady() && pttState != PttState.OFF && !rules.talking) pttUi(PttState.OFF, "Talk channel closed. Reconnecting...")
        if (rules.talking && !Talk.talking) {
            endTalk()
            pttUi(if (talkReady()) PttState.READY else PttState.OFF, "")
        }
    }

    private fun pttDown() {
        if (rules.talking) return
        if (rules.gapLeft() > 0) {
            setPttMsg(R.color.amber, rules.waitText())
            buzz(longArrayOf(0, 15))
            return
        }
        if (!talkReady()) {
            openTalk()
            return
        }
        rules.begin()
        guardStop = ""
        guardWarn = false
        pttUi(PttState.KEYING, "")
        ui.removeCallbacks(tickRun)
        ui.postDelayed(tickRun, TICK_MS)
        val guard = if (rules.guardOn()) rules.guardSecs().toDouble() else 0.0
        val gain = settings.micGainDb
        talkIo.execute {
            val ok = Talk.svc?.key(guard, gain) ?: false
            if (!ok) ui.post { keyFailed() }
        }
    }

    private fun keyFailed() {
        if (!rules.talking || rules.keyed) return
        endTalk()
        pttUi(if (talkReady()) PttState.READY else PttState.OFF, "The app could not key up (talk channel or microphone).", R.color.red)
    }

    private fun unkey() {
        talkIo.execute { Talk.svc?.unkey() }
    }

    private fun pttUp() {
        if (!rules.talking) return
        unkey()
        endTalk()
        pttUi(if (talkReady()) PttState.READY else PttState.OFF)
    }

    private fun endTalk() {
        rules.end()
        ui.removeCallbacks(tickRun)
        guardWarn = false
        pttTime.text = ""
        pttTime.visibility = View.VISIBLE
        meter.transmitting = false
        stLevel.setTextColor(act.getColor(R.color.muted))
        stLevel.setTypeface(Typeface.MONOSPACE, Typeface.NORMAL)
        stLevel.text = "-"
    }

    private fun talkTick() {
        val t = rules.tick() ?: return
        pttTime.text = t.text
        if (rules.guardOn()) {
            pttTime.visibility = if (guardWarn && (SystemClock.elapsedRealtime() / 500) % 2 == 1L) View.INVISIBLE else View.VISIBLE
        }
        if (t.warn) {
            guardWarn = true
            renderPtt()
            Beep.guard()
            buzz(longArrayOf(0, 60, 60, 60))
        }
        if (t.expired) {
            guardStop = rules.guardText()
            unkey()
            endTalk()
            pttUi(if (talkReady()) PttState.READY else PttState.OFF, guardStop, R.color.amber)
        }
    }

    private fun talkEvent(raw: String) {
        val m = try {
            JSONObject(raw)
        } catch (e: JSONException) {
            return
        }
        when (m.optString("ev")) {
            "open" -> if (pttState == PttState.OFF) pttUi(PttState.READY, "")
            "closed" -> {
                if (rules.talking) endTalk()
                val err = m.optString("error")
                pttUi(PttState.OFF, if (err.isNotEmpty()) "Talk channel: $err. Reconnecting..." else "Talk channel closed. Reconnecting...")
            }
            "level" -> if (rules.talking) txMeter(m.optDouble("db", -120.0))
            "micfail" -> {
                endTalk()
                pttUi(if (talkReady()) PttState.READY else PttState.OFF, "The app could not open the microphone.", R.color.red)
            }
            "guard" -> if (rules.talking) {
                guardStop = rules.guardText()
                endTalk()
                pttUi(if (talkReady()) PttState.READY else PttState.OFF, guardStop, R.color.amber)
            }
            "keyed" -> {
                rules.keyed = true
                rules.keyedAt = SystemClock.elapsedRealtime()
                val tot = m.optDouble("tot", 0.0)
                if (tot > 0) rules.totSec = tot
                pttUi(PttState.TALKING, "")
                buzz(longArrayOf(0, 30))
            }
            "denied" -> {
                endTalk()
                pttUi(PttState.READY, PttRules.denied(m.optString("why")), R.color.amber)
            }
            "unkeyed" -> {
                endTalk()
                if (guardStop.isNotEmpty()) {
                    pttUi(PttState.READY, guardStop, R.color.amber)
                    guardStop = ""
                } else {
                    val why = PttRules.unkeyed(m.optString("why"), m.optDouble("secs", 0.0))
                    pttUi(PttState.READY, why, if (why.isEmpty()) R.color.text else R.color.amber)
                }
                buzz(longArrayOf(0, 20, 40, 20))
            }
        }
    }

    private fun txMeter(db: Double) {
        meter.transmitting = true
        meter.percent = Spectrum.dbPct(db)
        stLevel.setTextColor(act.getColor(R.color.red))
        stLevel.setTypeface(Typeface.MONOSPACE, Typeface.BOLD)
        stLevel.text = "TX ${Spectrum.fmtDb(db)}"
    }

    private fun markKerchunk() {
        val n = host.node
        Thread {
            val result = try {
                val r = NodeApi(n).post("/api/kerchunks/test/mark")
                Pair(true, r.optString("message"))
            } catch (e: IOException) {
                Pair(false, e.message ?: "Could not mark the key-up.")
            }
            ui.post {
                val text = result.second.ifEmpty { "Could not mark the key-up." }
                setPttMsg(if (result.first) R.color.accent else R.color.red, text)
                markShown = text
                ui.postDelayed({
                    if (markShown == text && pttMsg.text.toString() == text) setPttMsg(R.color.text, "")
                }, MARK_MS)
            }
        }.start()
    }

    private fun buzz(pattern: LongArray) {
        try {
            if (vibrator?.hasVibrator() == true) vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
        } catch (e: SecurityException) {
            return
        }
    }

    companion object {
        private val talkIo = Executors.newSingleThreadExecutor { r -> Thread(r, "nt-ptt") }
        private const val POLL_MS = 1500L
        private const val FRAME_MS = 40L
        private const val TICK_MS = 250L
        private const val MARK_MS = 4000L
    }
}

object Beep {
    private const val RATE = 8000

    fun guard() {
        val pcm = ShortArray((0.3 * RATE).toInt())
        val len = (0.08 * RATE).toInt()
        val edge = 0.005 * RATE
        for (start in intArrayOf(0, (0.2 * RATE).toInt())) {
            for (i in 0 until len) {
                val env = min(1.0, min(i / edge, (len - i) / edge))
                pcm[start + i] = (sin(2 * Math.PI * 1000 * i / RATE) * 0.18 * 32767 * env).toInt().toShort()
            }
        }
        val track = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
            .setBufferSizeInBytes(pcm.size * 2)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()
        track.write(pcm, 0, pcm.size)
        track.play()
        Handler(Looper.getMainLooper()).postDelayed({ track.release() }, ceil(0.5 * 1000).toLong())
    }
}
