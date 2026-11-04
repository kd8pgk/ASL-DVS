package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.PI
import kotlin.math.log10
import kotlin.math.sin
import kotlin.math.sqrt

class DspTest {

    private fun tone(rate: Int, hz: Double, n: Int, amp: Double = 0.5): DoubleArray =
        DoubleArray(n) { amp * sin(2 * PI * hz * it / rate) }

    private fun rmsDb(x: DoubleArray, from: Int): Double {
        var s = 0.0
        for (i in from until x.size) s += x[i] * x[i]
        return 20 * log10(sqrt(s / (x.size - from)) + 1e-12)
    }

    private fun filtered(x: DoubleArray, f: (Double) -> Double): DoubleArray = DoubleArray(x.size) { f(x[it]) }

    @Test
    fun high_pass_cuts_rumble_and_keeps_voice() {
        val rate = 8000
        val hp = Biquad.highPass(rate, 150.0)
        val low = filtered(tone(rate, 50.0, 8000)) { hp.run(it) }
        val mid = filtered(tone(rate, 1000.0, 8000)) { hp.run(it) }
        val ref = tone(rate, 1000.0, 8000)
        assertTrue(rmsDb(low, 4000) < rmsDb(ref, 4000) - 12)
        assertEquals(rmsDb(ref, 4000), rmsDb(mid, 4000), 1.0)
    }

    @Test
    fun low_pass_at_3400_passes_voice_and_cuts_hiss_above() {
        val rate = 8000
        val lp = Biquad.lowPass(rate, 3400.0)
        val pass = filtered(tone(rate, 1000.0, 8000)) { lp.run(it) }
        val lp2 = Biquad.lowPass(rate, 3400.0)
        val stop = filtered(tone(rate, 3900.0, 8000)) { lp2.run(it) }
        val ref = tone(rate, 1000.0, 8000)
        assertEquals(rmsDb(ref, 4000), rmsDb(pass, 4000), 1.0)
        assertTrue(rmsDb(stop, 4000) < rmsDb(ref, 4000) - 6)
    }

    @Test
    fun fir_anti_alias_passes_speech_band_and_rejects_aliasing_source() {
        val rate = 48000
        val fir = Fir(rate, 3400.0, 63)
        val voice = filtered(tone(rate, 1000.0, 48000)) { fir.run(it) }
        val fir2 = Fir(rate, 3400.0, 63)
        val alias = filtered(tone(rate, 6000.0, 48000)) { fir2.run(it) }
        val ref = tone(rate, 1000.0, 48000)
        assertEquals(rmsDb(ref, 8000), rmsDb(voice, 8000), 0.5)
        assertTrue(rmsDb(alias, 8000) < rmsDb(ref, 8000) - 40)
    }

    @Test
    fun fir_has_unity_dc_gain() {
        val fir = Fir(48000, 3400.0, 63)
        var last = 0.0
        for (i in 0 until 2000) last = fir.run(0.25)
        assertEquals(0.25, last, 1e-6)
    }

    @Test
    fun gate_mutes_a_quiet_noise_floor() {
        val rate = 8000
        val g = Gate(rate)
        val noise = DoubleArray(8000) { 0.002 * sin(it * 12.9898) }
        val out = filtered(noise) { g.run(it) }
        assertTrue(rmsDb(out, 4000) < -60)
    }

    @Test
    fun gate_passes_speech_level_audio() {
        val rate = 8000
        val g = Gate(rate)
        val speech = tone(rate, 800.0, 8000, 0.3)
        val out = filtered(speech) { g.run(it) }
        assertEquals(rmsDb(speech, 4000), rmsDb(out, 4000), 1.0)
    }

    @Test
    fun gate_has_hysteresis_between_open_and_close_levels() {
        val rate = 8000
        val between = tone(rate, 800.0, 8000, 0.01)
        val closedStart = filtered(between) { Gate(rate).run(it) }
        assertTrue(rmsDb(closedStart, 4000) < -60)
        val g = Gate(rate)
        filtered(tone(rate, 800.0, 4000, 0.3)) { g.run(it) }
        val openStart = filtered(between) { g.run(it) }
        assertEquals(rmsDb(between, 4000), rmsDb(openStart, 4000), 1.0)
    }

    @Test
    fun voice_chain_keeps_length_and_clips_safely() {
        val chain = VoiceChain(8000)
        val src = ShortArray(160) { if (it % 2 == 0) Short.MAX_VALUE else Short.MIN_VALUE }
        val out = chain.process(src)
        assertEquals(160, out.size)
        for (v in out) assertTrue(v >= Short.MIN_VALUE && v <= Short.MAX_VALUE)
    }
}
