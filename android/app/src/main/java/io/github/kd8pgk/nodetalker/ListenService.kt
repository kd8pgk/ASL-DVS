package io.github.kd8pgk.nodetalker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.Manifest
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.media.audiofx.LoudnessEnhancer
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.PowerManager
import android.webkit.CookieManager
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.roundToInt

object Listen {
    const val OFF = "off"
    const val CONNECTING = "connecting"
    const val PLAYING = "playing"
    const val RECONNECTING = "reconnecting"
    const val PAUSED = "paused"

    @Volatile var nodeId: String? = null
    @Volatile var state: String = OFF
    @Volatile var error: String = ""
    @Volatile var level: Double = -120.0
    @Volatile var muted = false
    @Volatile var volume = 1f

    val listeners = CopyOnWriteArrayList<() -> Unit>()

    fun json(): String = JSONObject().put("state", state).put("error", error)
        .put("level", if (state == PLAYING) level else -120.0).toString()

    fun changed() = listeners.forEach { it() }

    fun start(c: Context, node: Node) {
        NodeStore.setLastNode(c, node.id)
        val i = Intent(c, ListenService::class.java).setAction(ListenService.ACTION_START).putExtra(ListenService.EXTRA_NODE, node.id)
        c.startForegroundService(i)
    }

    fun stop(c: Context) {
        if (state == OFF) return
        c.startService(Intent(c, ListenService::class.java).setAction(ListenService.ACTION_LISTEN_STOP))
    }
}

object Talk {
    @Volatile var nodeId: String? = null
    @Volatile var open = false
    @Volatile var talking = false
    @Volatile var error = ""
    @Volatile var svc: ListenService? = null

    val listeners = CopyOnWriteArrayList<(String) -> Unit>()

    fun emit(json: String) = listeners.forEach { it(json) }

    fun json(): String = JSONObject().put("open", open).put("talking", talking).put("error", error).toString()

    fun open(c: Context, node: Node) {
        val i = Intent(c, ListenService::class.java).setAction(ListenService.ACTION_TALK).putExtra(ListenService.EXTRA_NODE, node.id)
        c.startForegroundService(i)
    }

    fun close(c: Context) {
        if (svc == null) return
        c.startService(Intent(c, ListenService::class.java).setAction(ListenService.ACTION_TALK_CLOSE))
    }
}

class ListenService : Service() {
    private var node: Node? = null
    private var net: Thread? = null
    private var player: Thread? = null
    @Volatile private var running = false
    @Volatile private var gen = 0
    private var playerSettings: AudioSettings? = null
    @Volatile private var focusLost = false
    private var session: MediaSession? = null
    private val queue = ArrayBlockingQueue<ShortArray>(QUEUE_FRAMES)
    private var wake: PowerManager.WakeLock? = null
    private var wifi: WifiManager.WifiLock? = null
    private var wifiLow: WifiManager.WifiLock? = null
    private var focus: AudioFocusRequest? = null
    @Volatile private var stream: InputStream? = null
    private val handler by lazy { Handler(mainLooper) }
    @Volatile private var talkWanted = false
    @Volatile private var talkGen = 0
    private var talkThread: Thread? = null
    @Volatile private var ws: WsClient? = null
    private var mic: Mic? = null
    private val talkLock = Any()
    @Volatile private var talking = false
    @Volatile private var keyed = false
    private val preKey = ArrayList<ByteArray>()
    private var guardMs = 0L
    private val guardRun = Runnable {
        if (talking && keyed) {
            Talk.emit("{\"ev\":\"guard\"}")
            unkey()
        }
    }
    private val unmute = Runnable { if (!talking) Listen.muted = false }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Talk.svc = this
        session = MediaSession(this, "NodeTalker").apply {
            setCallback(object : MediaSession.Callback() {})
            setPlaybackState(PlaybackState.Builder().setState(PlaybackState.STATE_PAUSED, PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f).build())
            setActive(true)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                shutdown()
                return START_NOT_STICKY
            }
            ACTION_LISTEN_STOP -> {
                listenStop()
                return START_NOT_STICKY
            }
            ACTION_TALK_CLOSE -> {
                talkClose()
                if (!running) shutdown() else node?.let { notifyState(it) }
                return START_NOT_STICKY
            }
        }
        val n = NodeStore.get(this, intent?.getStringExtra(EXTRA_NODE))
        if (n == null) {
            if (!running && !talkWanted) shutdown()
            return START_NOT_STICKY
        }
        if (node != null && node?.id != n.id) {
            talkClose()
            stopWorkers()
            Listen.nodeId = null
            Listen.level = -120.0
            set(Listen.OFF, "")
        }
        node = n
        startInForeground(n)
        locks(true)
        if (focus == null) requestFocus()
        if (intent?.action == ACTION_TALK) {
            talkOpen(n)
            return START_NOT_STICKY
        }
        if (running && node?.id == n.id) {
            if (NodeStore.audio(this) != playerSettings) restartPlayer()
            if (focusLost) requestFocus()
            return START_NOT_STICKY
        }
        stopWorkers()
        Listen.nodeId = n.id
        Listen.error = ""
        set(Listen.CONNECTING)
        running = true
        val g = ++gen
        queue.clear()
        net = Thread({ netLoop(n, g) }, "nt-listen-net").apply { start() }
        player = Thread({ playLoop(g) }, "nt-listen-play").apply { start() }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        shutdown()
        if (Talk.svc === this) Talk.svc = null
        session?.release()
        session = null
        super.onDestroy()
    }

    private fun listenStop() {
        stopWorkers()
        Listen.nodeId = null
        Listen.level = -120.0
        set(Listen.OFF, "")
        if (!talkWanted) shutdown() else node?.let { notifyState(it) }
    }

    private fun talkOpen(n: Node) {
        Talk.nodeId = n.id
        if (talkWanted && talkThread?.isAlive == true) {
            if (Talk.open) Talk.emit("{\"ev\":\"open\"}")
            return
        }
        talkWanted = true
        val g = ++talkGen
        talkThread = Thread({ talkLoop(n, g) }, "nt-talk").apply { start() }
    }

    private fun talkClose() {
        unkey()
        talkWanted = false
        talkGen++
        val c = ws
        ws = null
        if (c != null) Thread({ c.close() }, "nt-talk-close").start()
        talkThread?.interrupt()
        talkThread = null
        Talk.open = false
        Talk.nodeId = null
    }

    private fun talkLoop(n: Node, g: Int) {
        var delayMs = 2000L
        while (talkWanted && g == talkGen) {
            val c = WsClient(n, CookieManager.getInstance().getCookie(n.origin))
            try {
                c.connect()
                if (!(talkWanted && g == talkGen)) {
                    c.close()
                    return
                }
                ws = c
                if (!(talkWanted && g == talkGen)) {
                    ws = null
                    c.close()
                    return
                }
                Talk.open = true
                Talk.error = ""
                delayMs = 2000L
                Talk.emit("{\"ev\":\"open\"}")
                node?.let { notifyState(it) }
                c.read { onTalkText(it) }
            } catch (e: IOException) {
                Talk.error = e.message ?: e.javaClass.simpleName
            }
            ws = null
            if (talking) stopTalk()
            c.close()
            val was = Talk.open
            Talk.open = false
            if (!(talkWanted && g == talkGen)) return
            if (was) Talk.emit(JSONObject().put("ev", "closed").put("error", Talk.error).toString())
            node?.let { notifyState(it) }
            try {
                Thread.sleep(delayMs)
            } catch (e: InterruptedException) {
                return
            }
            delayMs = minOf(delayMs * 2, 10000L)
        }
    }

    private fun onTalkText(t: String) {
        val m = try {
            JSONObject(t)
        } catch (e: org.json.JSONException) {
            return
        }
        when (m.optString("ev")) {
            "keyed" -> {
                val pk: List<ByteArray>
                synchronized(talkLock) {
                    keyed = talking
                    pk = preKey.toList()
                    preKey.clear()
                }
                val c = ws
                try {
                    pk.forEach { c?.sendBinary(it) }
                } catch (e: IOException) {
                    Talk.error = e.message ?: ""
                }
                if (guardMs > 0) handler.postDelayed(guardRun, guardMs)
            }
            "denied", "unkeyed" -> if (talking) stopTalk()
        }
        Talk.emit(t)
    }

    fun key(guardSec: Double, gainDb: Double): Boolean {
        val c = ws ?: return false
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return false
        synchronized(talkLock) {
            if (talking) return true
            talking = true
            keyed = false
            preKey.clear()
            guardMs = (guardSec * 1000).toLong()
        }
        handler.removeCallbacks(unmute)
        handler.removeCallbacks(guardRun)
        Listen.muted = true
        try {
            c.sendText("{\"op\":\"key\"}")
        } catch (e: IOException) {
            stopTalk()
            return false
        }
        val m = Mic(NodeStore.audio(this).voiceMic, gainDb, ::micFrame) { db ->
            Talk.emit(JSONObject().put("ev", "level").put("db", db).toString())
        }
        if (!m.start()) {
            unkey()
            Talk.emit("{\"ev\":\"micfail\"}")
            return false
        }
        mic = m
        Talk.talking = true
        node?.let { notifyState(it) }
        return true
    }

    private fun micFrame(f: ByteArray) {
        synchronized(talkLock) {
            if (!talking) return
            if (!keyed) {
                if (preKey.size < PRE_KEY_FRAMES) preKey.add(f)
                return
            }
        }
        try {
            ws?.sendBinary(f)
        } catch (e: IOException) {
            Talk.error = e.message ?: ""
        }
    }

    fun unkey() {
        if (!talking) return
        if (android.os.Looper.myLooper() == mainLooper) {
            Thread({ unkey() }, "nt-unkey").start()
            return
        }
        try {
            ws?.sendText("{\"op\":\"unkey\"}")
        } catch (e: IOException) {
            Talk.error = e.message ?: ""
        }
        stopTalk()
    }

    private fun stopTalk() {
        synchronized(talkLock) {
            talking = false
            keyed = false
            preKey.clear()
        }
        handler.removeCallbacks(guardRun)
        mic?.stop()
        mic = null
        Talk.talking = false
        handler.postDelayed(unmute, 1000)
        node?.let { notifyState(it) }
    }

    private fun set(state: String, err: String = Listen.error) {
        val changed = state != Listen.state || err != Listen.error
        Listen.state = state
        Listen.error = err
        session?.setPlaybackState(
            PlaybackState.Builder()
                .setState(if (state == Listen.PLAYING) PlaybackState.STATE_PLAYING else PlaybackState.STATE_PAUSED, PlaybackState.PLAYBACK_POSITION_UNKNOWN, 1f)
                .build(),
        )
        if (changed) {
            node?.let { notifyState(it) }
            Listen.changed()
        }
    }

    private fun shutdown() {
        talkClose()
        stopWorkers()
        locks(false)
        focus?.let { (getSystemService(AUDIO_SERVICE) as AudioManager).abandonAudioFocusRequest(it) }
        focus = null
        Listen.nodeId = null
        Listen.level = -120.0
        Listen.muted = false
        node = null
        set(Listen.OFF)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun stopWorkers() {
        running = false
        gen++
        val s = stream
        stream = null
        if (s != null) Thread({
            try {
                s.close()
            } catch (e: IOException) {
                return@Thread
            } catch (e: RuntimeException) {
                return@Thread
            }
        }, "nt-listen-close").start()
        net?.interrupt()
        player?.interrupt()
        net?.join(2000)
        player?.join(2000)
        net = null
        player = null
    }

    private fun restartPlayer() {
        player?.interrupt()
        player?.join(2000)
        val g = gen
        player = Thread({ playLoop(g) }, "nt-listen-play").apply { start() }
    }

    private fun live(g: Int) = running && g == gen

    private fun netLoop(n: Node, g: Int) {
        var delayMs = 1000L
        while (live(g)) {
            try {
                val cookie = CookieManager.getInstance().getCookie(n.origin)
                val c = NodeHttp.open(n, "/api/listen?fmt=s16", cookie)
                c.readTimeout = 6000
                c.useCaches = false
                val code = c.responseCode
                if (!live(g)) {
                    c.disconnect()
                    return
                }
                if (code == 401) {
                    c.disconnect()
                    set(Listen.OFF, getString(R.string.listen_login))
                    running = false
                    mainHandler().post { shutdown() }
                    return
                }
                if (code != 200) {
                    val msg = try {
                        JSONObject(c.errorStream?.bufferedReader()?.readText() ?: "").optString("error")
                    } catch (e: org.json.JSONException) {
                        ""
                    }
                    c.disconnect()
                    throw IOException(msg.ifEmpty { "HTTP $code" })
                }
                val pcm = c.getHeaderField("X-Audio-Format").orEmpty().startsWith("s16le")
                val input = c.inputStream
                if (!live(g)) {
                    c.disconnect()
                    return
                }
                stream = input
                delayMs = 1000L
                Listen.error = ""
                readFrames(input, pcm, g)
                c.disconnect()
                if (live(g)) throw IOException(getString(R.string.listen_ended))
            } catch (e: IOException) {
                if (!live(g)) return
                set(Listen.RECONNECTING, getString(R.string.listen_retry, e.message ?: e.javaClass.simpleName, delayMs / 1000))
                try {
                    Thread.sleep(delayMs)
                } catch (x: InterruptedException) {
                    return
                }
                delayMs = minOf(delayMs * 2, 10000L)
            }
        }
    }

    private fun readFrames(input: InputStream, pcm: Boolean, g: Int) {
        val bytesPer = if (pcm) FRAME * 2 else FRAME
        val buf = ByteArray(bytesPer)
        while (live(g)) {
            var got = 0
            while (got < bytesPer) {
                val r = input.read(buf, got, bytesPer - got)
                if (r < 0) return
                got += r
            }
            val f = ShortArray(FRAME)
            if (pcm) {
                for (i in 0 until FRAME) f[i] = ((buf[2 * i].toInt() and 0xff) or (buf[2 * i + 1].toInt() shl 8)).toShort()
            } else {
                for (i in 0 until FRAME) f[i] = ULAW[buf[i].toInt() and 0xff]
            }
            if (!queue.offer(f)) {
                queue.poll()
                queue.offer(f)
            }
        }
    }

    private fun playLoop(g: Int) {
        val s = NodeStore.audio(this)
        playerSettings = s
        val attrs = AudioAttributes.Builder()
            .setUsage(if (s.earpiece) AudioAttributes.USAGE_VOICE_COMMUNICATION else AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
        val fmt = AudioFormat.Builder().setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build()
        val min = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val track = AudioTrack.Builder().setAudioAttributes(attrs).setAudioFormat(fmt)
            .setBufferSizeInBytes(max(min, RATE * 2 / 5)).setTransferMode(AudioTrack.MODE_STREAM).build()
        val enh = try {
            LoudnessEnhancer(track.audioSessionId).apply { enabled = true }
        } catch (e: RuntimeException) {
            null
        }
        var boostMb = -1
        val target = (s.bufferMs / FRAME_MS).coerceAtLeast(2)
        val silence = ShortArray(FRAME)
        var filling = true
        var peak = 0
        var n = 0
        try {
            track.play()
            while (live(g) && !Thread.currentThread().isInterrupted) {
                if (filling) {
                    if (queue.size < target) {
                        Thread.sleep(FRAME_MS.toLong())
                        continue
                    }
                    filling = false
                }
                while (queue.size > target * 3 + 5) queue.poll()
                val f = queue.poll(FRAME_MS * 4L, TimeUnit.MILLISECONDS)
                if (f == null) {
                    filling = true
                    continue
                }
                val vol = Listen.volume
                track.setVolume(vol.coerceAtMost(1f))
                val mb = ((s.boostDb + overDb(vol)) * 100).roundToInt().coerceIn(0, MAX_GAIN_MB)
                if (mb != boostMb) {
                    boostMb = mb
                    enh?.setTargetGain(mb)
                }
                val quiet = Listen.muted || focusLost
                track.write(if (quiet) silence else f, 0, FRAME)
                for (v in f) peak = max(peak, abs(v.toInt()))
                if (++n >= LEVEL_FRAMES) {
                    Listen.level = if (peak == 0) -120.0 else 20 * log10(peak / 32768.0)
                    peak = 0
                    n = 0
                    val st = if (focusLost) Listen.PAUSED else Listen.PLAYING
                    if (Listen.state != st) set(st, "") else Listen.changed()
                }
            }
        } catch (e: InterruptedException) {
            Listen.level = -120.0
        } finally {
            track.pause()
            track.flush()
            track.release()
            enh?.release()
        }
    }

    private fun overDb(v: Float): Double = if (v > 1f) 20 * log10(v.toDouble()) else 0.0

    private fun requestFocus() {
        val am = getSystemService(AUDIO_SERVICE) as AudioManager
        val req = focus ?: AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            .setWillPauseWhenDucked(false)
            .setAcceptsDelayedFocusGain(true)
            .setOnAudioFocusChangeListener { change ->
                focusLost = change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT
                if (focusLost && talking) handler.post { unkey() }
                if (running && Listen.state != Listen.RECONNECTING && Listen.state != Listen.CONNECTING) {
                    set(if (focusLost) Listen.PAUSED else Listen.PLAYING, "")
                }
            }
            .build()
        focus = req
        focusLost = am.requestAudioFocus(req) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    }

    @Suppress("DEPRECATION")
    @android.annotation.SuppressLint("WakelockTimeout", "Wakelock")
    private fun locks(on: Boolean) {
        if (on) {
            if (wake == null) {
                wake = (getSystemService(POWER_SERVICE) as PowerManager)
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "NodeTalker:listen").apply { setReferenceCounted(false); acquire() }
            }
            val wm = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
            if (wifi == null) {
                wifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "NodeTalker:listen")
                    .apply { setReferenceCounted(false); acquire() }
            }
            if (wifiLow == null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                wifiLow = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_LOW_LATENCY, "NodeTalker:listen-low")
                    .apply { setReferenceCounted(false); acquire() }
            }
        } else {
            wake?.let { if (it.isHeld) it.release() }
            wifi?.let { if (it.isHeld) it.release() }
            wifiLow?.let { if (it.isHeld) it.release() }
            wake = null
            wifi = null
            wifiLow = null
        }
    }

    private fun mainHandler() = android.os.Handler(mainLooper)

    private fun startInForeground(n: Node) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, getString(R.string.channel_listen), NotificationManager.IMPORTANCE_LOW)
                    .apply { setShowBadge(false) },
            )
        }
        val notif = build(n)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val micOk = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK or
                (if (micOk) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0))
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    private fun notifyState(n: Node) {
        if (Listen.state == Listen.OFF && !talkWanted) return
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, build(n))
    }

    private fun build(n: Node): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, TalkerActivity::class.java).putExtra(TalkerActivity.EXTRA_NODE, n.id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, ListenService::class.java).setAction(ACTION_STOP), PendingIntent.FLAG_IMMUTABLE,
        )
        val text = when {
            talking -> getString(R.string.notif_talking)
            Listen.state == Listen.OFF -> getString(if (Talk.open) R.string.notif_talk_ready else R.string.notif_connecting)
            else -> listenText()
        }
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_listen)
            .setContentTitle(n.title)
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_TRANSPORT)
            .addAction(Notification.Action.Builder(null, getString(R.string.stop), stop).build())
            .build()
    }

    private fun listenText(): String {
        return when (Listen.state) {
            Listen.PLAYING -> getString(R.string.notif_playing)
            Listen.PAUSED -> getString(R.string.notif_paused)
            Listen.RECONNECTING -> getString(R.string.notif_reconnecting)
            else -> getString(R.string.notif_connecting)
        }
    }

    companion object {
        const val ACTION_START = "io.github.kd8pgk.nodetalker.LISTEN"
        const val ACTION_STOP = "io.github.kd8pgk.nodetalker.STOP"
        const val ACTION_LISTEN_STOP = "io.github.kd8pgk.nodetalker.LISTEN_STOP"
        const val ACTION_TALK = "io.github.kd8pgk.nodetalker.TALK"
        const val ACTION_TALK_CLOSE = "io.github.kd8pgk.nodetalker.TALK_CLOSE"
        private const val PRE_KEY_FRAMES = 25
        const val EXTRA_NODE = "node"
        private const val CHANNEL = "listen"
        private const val NOTIF_ID = 1
        private const val RATE = 8000
        private const val FRAME = 160
        private const val FRAME_MS = 20
        private const val QUEUE_FRAMES = 150
        private const val LEVEL_FRAMES = 10
        private const val MAX_GAIN_MB = 1800

        private val ULAW = ShortArray(256) { i ->
            val u = i.inv() and 0xff
            val t = ((u and 0x0f) shl 3) + 0x84 shl ((u and 0x70) shr 4)
            (if (u and 0x80 != 0) 0x84 - t else t - 0x84).toShort()
        }
    }
}
