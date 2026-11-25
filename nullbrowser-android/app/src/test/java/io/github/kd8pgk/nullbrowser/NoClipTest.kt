package io.github.kd8pgk.nullbrowser

import android.view.KeyEvent
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NoClipTest {
    @Test
    fun clipboardKeysAreCaught() {
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_V, ctrl = true, shift = false))
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_C, ctrl = true, shift = false))
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_X, ctrl = true, shift = true))
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_INSERT, ctrl = true, shift = false))
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_INSERT, ctrl = false, shift = true))
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_FORWARD_DEL, ctrl = false, shift = true))
        assertTrue(NoClip.isClipKey(KeyEvent.KEYCODE_PASTE, ctrl = false, shift = false))
    }

    @Test
    fun typingIsNotCaught() {
        assertFalse(NoClip.isClipKey(KeyEvent.KEYCODE_V, ctrl = false, shift = false))
        assertFalse(NoClip.isClipKey(KeyEvent.KEYCODE_V, ctrl = false, shift = true))
        assertFalse(NoClip.isClipKey(KeyEvent.KEYCODE_FORWARD_DEL, ctrl = false, shift = false))
        assertFalse(NoClip.isClipKey(KeyEvent.KEYCODE_A, ctrl = true, shift = false))
    }

    @Test
    fun pageScriptBlocksEveryClipboardRoute() {
        for (word in listOf("execCommand", "queryCommandSupported", "writeText", "readText", "'copy'", "'cut'", "'paste'")) assertTrue(word, NoClip.JS.contains(word))
    }
}
