package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LessInfoTest {
    @Test
    fun modelAndBuildAreDroppedAndVersionShortened() {
        val ua = "Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UQ1A.240205.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36"
        assertEquals("Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36", LessInfo.userAgent(ua))
    }

    @Test
    fun tabletWithoutMobileStaysTablet() {
        val ua = "Mozilla/5.0 (Linux; Android 13; SM-X200 Build/TP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/119.0.6045.163 Safari/537.36"
        assertEquals("Mozilla/5.0 (Linux; Android 13; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/119.0.0.0 Safari/537.36", LessInfo.userAgent(ua))
    }

    @Test
    fun unknownShapeIsLeftAlone() {
        assertEquals("something else", LessInfo.userAgent("something else"))
    }

    @Test
    fun pageScriptRemovesTheReadouts() {
        for (w in listOf("'connection'", "'deviceMemory'", "'hardwareConcurrency'", "'getBattery'", "getHighEntropyValues")) assertTrue(w, LessInfo.JS.contains(w))
    }
}
