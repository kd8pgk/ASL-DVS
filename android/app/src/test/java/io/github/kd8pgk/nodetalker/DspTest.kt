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
        val noise = DoubleArray(16000) { 0.0005 * sin(it * 12.9898) }
        val out = filtered(noise) { g.run(it) }
        assertTrue(rmsDb(out, 8000) < -80)
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
    fun gate_does_not_chop_a_quiet_station() {
        val rate = 8000
        val g = Gate(rate)
        val quiet = tone(rate, 800.0, 16000, 0.004)
        val out = filtered(quiet) { g.run(it) }
        assertEquals(rmsDb(quiet, 8000), rmsDb(out, 8000), 1.0)
    }

    @Test
    fun gate_has_hysteresis_between_open_and_close_levels() {
        val rate = 8000
        val between = tone(rate, 800.0, 8000, 0.01)
        val g = Gate(rate)
        filtered(tone(rate, 800.0, 4000, 0.3)) { g.run(it) }
        val openStart = filtered(between) { g.run(it) }
        assertEquals(rmsDb(between, 4000), rmsDb(openStart, 4000), 1.0)
    }

    @Test
    fun a_low_tone_does_not_hold_the_gate_open() {
        val rate = 8000
        val g = Gate(rate)
        filtered(tone(rate, 800.0, 4000, 0.3)) { g.run(it) }
        val ctcss = tone(rate, 100.0, 24000, 0.02)
        val out = filtered(ctcss) { g.run(it) }
        assertTrue(rmsDb(ctcss, 12000) > -45)
        assertTrue(rmsDb(out, 12000) < -70)
    }

    @Test
    fun mic_leveler_lifts_a_quiet_voice_about_nine_db() {
        val rate = 8000
        val d = MicDyn(false, false, 0, true)
        val x = tone(rate, 800.0, 40000, 0.01)
        val out = filtered(x) { d.run(it) }
        assertEquals(9.0, rmsDb(out, 24000) - rmsDb(x, 24000), 1.0)
    }

    @Test
    fun mic_limiter_never_passes_more_than_the_ceiling() {
        val d = MicDyn(false, false, 0, true)
        val quiet = tone(8000, 800.0, 8000, 0.01)
        quiet.forEach { d.run(it) }
        val loud = tone(8000, 800.0, 800, 0.95)
        var peak = 0.0
        loud.forEach { peak = maxOf(peak, kotlin.math.abs(d.run(it))) }
        assertTrue(peak <= 0.895)
        assertTrue(d.minLimiter < 0.95)
    }

    @Test
    fun mic_gate_pulls_a_pause_down_to_its_floor() {
        val d = MicDyn(false, false, 1, false)
        filtered(tone(8000, 800.0, 4000, 0.3)) { d.run(it) }
        val pause = DoubleArray(16000) { 0.001 * sin(it * 3.7) }
        val out = filtered(pause) { d.run(it) }
        assertEquals(20 * log10(0.18), rmsDb(out, 12000) - rmsDb(pause, 12000), 1.0)
        assertTrue(d.minGate < 0.5)
    }

    @Test
    fun mic_voice_filter_cuts_rumble() {
        val d = MicDyn(true, false, 0, false)
        val rumble = tone(8000, 60.0, 16000, 0.3)
        val out = filtered(rumble) { d.run(it) }
        assertTrue(rmsDb(out, 8000) < rmsDb(rumble, 8000) - 15)
    }

    @Test
    fun mic_with_everything_off_is_unchanged() {
        val d = MicDyn(false, false, 0, false)
        val x = tone(8000, 800.0, 4000, 0.3)
        val out = filtered(x) { d.run(it) }
        for (i in x.indices) assertEquals(x[i], out[i], 1e-12)
    }

    @Test
    fun frame_stats_match_the_page_numbers() {
        val fs = FrameStats()
        val frame = ShortArray(160) { (16384 * sin(2 * PI * 1000.0 * it / 8000)).toInt().toShort() }
        val a = fs.of(frame)
        assertEquals(-9.03, a[0], 0.1)
        assertEquals(-6.02, a[1], 0.1)
        assertEquals(0.7071, a[2], 0.1)
        assertEquals(0.0, a[3], 0.1)
        val silent = fs.of(ShortArray(160))
        assertEquals(-120.0, silent[0], 0.0)
        assertEquals(1.0, silent[2], 0.0)
    }

    @Test
    fun hum_meter_sees_a_ctcss_tone_and_ignores_speech_band() {
        val h = Hum()
        h.push(ShortArray(512) { (6000 * sin(2 * PI * 100.0 * it / 8000)).toInt().toShort() })
        assertTrue(h.db() > 10)
        val v = Hum()
        v.push(ShortArray(512) { (6000 * sin(2 * PI * 1000.0 * it / 8000)).toInt().toShort() })
        assertTrue(v.db() < -30)
        assertTrue(Hum().db().isNaN())
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
