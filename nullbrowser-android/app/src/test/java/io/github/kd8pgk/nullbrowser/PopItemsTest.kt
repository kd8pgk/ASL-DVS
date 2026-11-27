package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PopItemsTest {
    @Test
    fun whatAPageReportsIsCleanedBeforeItIsShownOrUsed() {
        val json = """[{"kind":"weird","tag":"DIV\n","text":"Win\u0000 a prize\n now","selector":"a{x:y}","frameHost":"Ads.Example.com","hosts":["evil.test","not a host","evil.test","x.test"],"w":1e9,"h":-4,"z":1e12}]"""
        var n = 0
        val items = PopItems.parseFound(json, "page.test") { ++n }
        assertEquals(1, items.size)
        val it = items[0]
        assertEquals("overlay", it.kind)
        assertFalse(it.tag.contains('\n'))
        assertTrue(it.text.length <= 80)
        assertFalse(it.text.contains('\u0000'))
        assertEquals("", it.selector)
        assertEquals("ads.example.com", it.frameHost)
        assertTrue(it.thirdParty)
        assertEquals(listOf("evil.test", "x.test"), it.hosts)
        assertEquals(99999, it.w)
        assertEquals(0, it.h)
    }

    @Test
    fun brokenInputGivesNothing() {
        assertTrue(PopItems.parseFound(null, "a.test") { 1 }.isEmpty())
        assertTrue(PopItems.parseFound("{}", "a.test") { 1 }.isEmpty())
        assertTrue(PopItems.parseFound("[1,\"x\",null]", "a.test") { 1 }.isEmpty())
    }

    @Test
    fun aPickedItemComesBackAsAStringOfJson() {
        val inner = """{"kind":"picked","tag":"div","text":"Ad","selector":"#box","frameHost":"a.test","hosts":[],"w":240,"h":120}"""
        val wrapped = "\"" + inner.replace("\"", "\\\"") + "\""
        val it = PopItems.parsePicked(wrapped, "a.test", 7)!!
        assertEquals(7, it.id)
        assertEquals("picked", it.kind)
        assertEquals("#box", it.selector)
        assertFalse(it.thirdParty)
        assertNull(PopItems.parsePicked("\"null\"", "a.test", 1))
        assertNull(PopItems.parsePicked("null", "a.test", 1))
    }

    @Test
    fun scriptsAreQuotedSoAPageStringCannotBreakOut() {
        val q = PopScripts.quote("a\"b\\c\n</script> ")
        assertEquals("\"a\\\"b\\\\c\\n\\u003c/script>\\u2028\"", q)
        assertTrue(PopScripts.tokenOk("0123456789abcdef"))
        assertFalse(PopScripts.tokenOk("x'); alert(1);//"))
        assertTrue(PopScripts.pickJs("0123456789abcdef").contains("__nbp'+\"0123456789abcdef\""))
        assertTrue(PopScripts.applyJs("a{b:c}").contains("\"a{b:c}\""))
        assertTrue(PopScripts.FIND_JS.startsWith("(function findFn"))
    }
}
