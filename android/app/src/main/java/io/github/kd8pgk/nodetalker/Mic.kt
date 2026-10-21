package io.github.kd8pgk.nodetalker

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.pow
import kotlin.math.roundToInt

class Mic(private val voice: Boolean, gainDb: Double, private val sink: (ByteArray) -> Unit, private val level: (Double) -> Unit) {
    private val gain = 10.0.pow(gainDb.coerceIn(-20.0, 20.0) / 20.0)
    @Volatile private var running = false
    private var thread: Thread? = null

    fun start(): Boolean {
        val rec = open() ?: return false
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

    private fun loop(rec: AudioRecord) {
        val step = rec.sampleRate / 8000
        val buf = ShortArray(rec.sampleRate / 50)
        val frame = ByteArray(FRAME * 2)
        var n = 0
        var acc = 0
        var cnt = 0
        var peak = 0
        var frames = 0
        try {
            rec.startRecording()
            while (running) {
                val got = rec.read(buf, 0, buf.size)
                if (got <= 0) continue
                for (k in 0 until got) {
                    acc += buf[k]
                    if (++cnt < step) continue
                    val v = (acc.toDouble() / step * gain).roundToInt().coerceIn(-32768, 32767)
                    acc = 0
                    cnt = 0
                    peak = max(peak, abs(v))
                    frame[2 * n] = v.toByte()
                    frame[2 * n + 1] = (v shr 8).toByte()
                    if (++n == FRAME) {
                        sink(frame.copyOf())
                        n = 0
                        if (++frames >= 10) {
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
    }
}
