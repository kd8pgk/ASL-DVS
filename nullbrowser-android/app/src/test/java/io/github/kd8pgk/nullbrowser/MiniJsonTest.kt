package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MiniJsonTest {
    @Test
    fun readsObjectsArraysStringsAndNumbers() {
        val v = MiniJson.map(MiniJson.parse("""{"a":[1,2.5,"x\nA\"",true,null],"b":{"c":-3}}"""))!!
        val a = MiniJson.list(v["a"])!!
        assertEquals(1.0, a[0])
        assertEquals(2.5, a[1])
        assertEquals("x\nA\"", a[2])
        assertEquals(true, a[3])
        assertNull(a[4])
        assertEquals(-3.0, MiniJson.map(v["b"])!!["c"])
    }

    @Test
    fun refusesBrokenOrHugeInput() {
        assertNull(MiniJson.parse(null))
        assertNull(MiniJson.parse(""))
        assertNull(MiniJson.parse("{"))
        assertNull(MiniJson.parse("[1,]"))
        assertNull(MiniJson.parse("{\"a\":1} x"))
        assertNull(MiniJson.parse("[".repeat(100)))
        assertNull(MiniJson.parse("x".repeat(3_000_000)))
    }

    @Test
    fun unwrapsAStringResult() {
        assertEquals("[1]", MiniJson.unwrapString("\"[1]\""))
        assertNull(MiniJson.unwrapString("null"))
        assertNull(MiniJson.unwrapString("[1]"))
    }

    @Test
    fun textAndNumberHelpers() {
        assertEquals("12", MiniJson.text(12.0, 10))
        assertEquals("abc", MiniJson.text("abcdef", 3))
        assertEquals("", MiniJson.text(listOf(1), 3))
        assertEquals(4.0, MiniJson.number("4"), 0.0)
        assertEquals(0.0, MiniJson.number("x"), 0.0)
    }
}
