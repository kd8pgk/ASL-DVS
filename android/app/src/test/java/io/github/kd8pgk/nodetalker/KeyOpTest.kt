package io.github.kd8pgk.nodetalker

import org.junit.Assert.assertEquals
import org.junit.Test

class KeyOpTest {
    @Test
    fun noChoiceSendsThePlainKey() {
        assertEquals("{\"op\":\"key\"}", Talk.keyOp(null))
    }

    @Test
    fun theQuickKeyGuardChoiceIsSent() {
        assertEquals("{\"op\":\"key\",\"qk\":true}", Talk.keyOp(true))
        assertEquals("{\"op\":\"key\",\"qk\":false}", Talk.keyOp(false))
    }
}
