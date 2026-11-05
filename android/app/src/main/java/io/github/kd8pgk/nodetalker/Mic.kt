package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.roundToInt

class MicOpts(val hp: Boolean, val eq: Boolean, val gate: Int, val lev: Boolean, val voice: Boolean)

class Mic(
    private val voice: Boolean,
    private val preset: Boolean,
    private val opts: MicOpts?,
    gainDb: Double,
    private val sink: (ByteArray) -> Unit,
    private val level: (Double) -> Unit,
    private val stats: ((String) -> Unit)?,
) {
    private val gain = 10.0.pow(gainDb.coerceIn(-20.0, 20.0) / 20.0)
    @Volatile private var running = false
    private var thread: Thread? = null
    @Volatile var rate = 0
        private set

    fun start(): Boolean {
        val rec = open() ?: return false
        rate = rec.sampleRate
        running = true
        thread = Thread({ loop(rec) }, "nt-mic").apply { start() }
        return true
    }

    fun stop() {
        running = false
        thread?.join(500)
        thread = null
    }

    @SuppressLint("MissingPermission")
    private fun open(): AudioRecord? {
        val src = if (voice) MediaRecorder.AudioSource.VOICE_COMMUNICATION else MediaRecorder.AudioSource.MIC
        for (rate in intArrayOf(8000, 16000, 48000)) {
            val min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            if (min <= 0) continue
            val r = try {
                AudioRecord(src, rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(min, rate / 5 * 2))
            } catch (e: IllegalArgumentException) {
                continue
            } catch (e: SecurityException) {
                return null
            }
            if (r.state == AudioRecord.STATE_INITIALIZED) return r
            r.release()
        }
        return null
    }

    private fun round2(v: Double) = (v * 100).roundToInt() / 100.0

    private fun loop(rec: AudioRecord) {
        val step = rec.sampleRate / 8000
        val buf = ShortArray(rec.sampleRate / 50)
        val frame = ByteArray(FRAME * 2)
        val fir = Fir(rec.sampleRate, 3400.0, 63)
        val fixed = if (preset) VoiceChain(8000) else null
        val dyn = if (!preset && opts != null) MicDyn(opts.hp, opts.eq, opts.gate, opts.lev) else null
        val gateOn = opts != null && opts.gate != 0
        var rows = JSONArray()
        var n = 0
        var cnt = 0
        var peak = 0
        var frames = 0
        var fss = 0.0
        var fpk = 0.0
        try {
            rec.startRecording()
            while (running) {
                val got = rec.read(buf, 0, buf.size)
                if (got < 0) break
                if (got == 0) continue
                for (k in 0 until got) {
                    val y = fir.run(buf[k].toDouble() / 32768.0)
                    if (++cnt < step) continue
                    cnt = 0
                    var x = y * gain
                    if (fixed != null) x = fixed.run(x) else if (dyn != null) x = dyn.run(x)
                    val a = abs(x)
                    if (a > fpk) fpk = a
                    fss += x * x
                    val v = (x * 32768.0).roundToInt().coerceIn(-32768, 32767)
                    peak = max(peak, abs(v))
                    frame[2 * n] = v.toByte()
                    frame[2 * n + 1] = (v shr 8).toByte()
                    if (++n == FRAME) {
                        sink(frame.copyOf())
                        n = 0
                        if (stats != null) {
                            val lim = if (dyn != null) -20 * log10(dyn.minLimiter) else 0.0
                            val closed = gateOn && dyn != null && dyn.minGate < 0.5
                            rows.put(
                                JSONArray()
                                    .put(round2(if (fss > 0) 10 * log10(fss / FRAME) else -120.0))
                                    .put(round2(if (fpk > 0) 20 * log10(fpk) else -120.0))
                                    .put(round2(lim))
                                    .put(if (closed) 1 else 0),
                            )
                            dyn?.resetFrame()
                            fss = 0.0
                            fpk = 0.0
                            if (rows.length() >= BATCH) {
                                stats(JSONObject().put("ev", "mic").put("f", rows).toString())
                                rows = JSONArray()
                            }
                        } else if (++frames >= 10) {
                            level(if (peak == 0) -120.0 else 20 * log10(peak / 32768.0))
                            peak = 0
                            frames = 0
                        }
                    }
                }
            }
        } catch (e: IllegalStateException) {
            running = false
        } finally {
            try {
                rec.stop()
            } catch (e: IllegalStateException) {
                running = false
            }
            rec.release()
        }
    }

    companion object {
        private const val FRAME = 160
        private const val BATCH = 5
    }
}
