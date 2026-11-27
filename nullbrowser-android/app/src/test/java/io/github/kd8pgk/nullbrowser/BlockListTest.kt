package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BlockListTest {
    @Test
    fun hostNamesAreCleanedFromListSyntax() {
        assertEquals("ads.example.com", BlockRules.cleanHost("||Ads.Example.com^\$third-party"))
        assertEquals("tracker.net", BlockRules.cleanHost("*.tracker.net"))
        assertEquals("", BlockRules.cleanHost("https://x.example.com/path"))
        assertEquals("x.example.com", BlockRules.cleanHost("x.example.com/path"))
        assertEquals("", BlockRules.cleanHost("localhost"))
        assertEquals("", BlockRules.cleanHost("com"))
        assertEquals("", BlockRules.cleanHost("bad host.com"))
        assertEquals("10.0.0.5", BlockRules.cleanHost("10.0.0.5"))
        assertEquals("", BlockRules.cleanHost("999.1.1.1"))
    }

    @Test
    fun aListedHostBlocksItselfAndSubdomainsButNotParentsOrLookalikes() {
        val l = BlockList()
        l.addHost("ads.example.com")
        assertEquals("ads.example.com", l.hostBlocked("ads.example.com"))
        assertEquals("ads.example.com", l.hostBlocked("x.y.ads.example.com"))
        assertEquals("", l.hostBlocked("example.com"))
        assertEquals("", l.hostBlocked("www.example.com"))
        assertEquals("", l.hostBlocked("badads.example.com"))
        assertEquals("", l.hostBlocked("ads.example.com.evil.test"))
        assertTrue(l.removeHost("ads.example.com"))
        assertEquals("", l.hostBlocked("ads.example.com"))
    }

    @Test
    fun selectorsThatCouldBreakOutOrHideThePageAreRefused() {
        for (ok in listOf("#promo", "div.popup", "div.a.b", "body > div:nth-of-type(2)", "div[role=\"dialog\"]", "iframe[src*=\"ads\"]")) assertEquals(ok, BlockRules.validSelector(ok))
        for (bad in listOf("", "body", "html", "*", ":root", "a{color:red}", "a;b", "@import url(x)", "div\\41", "a,b", "div[x=\"1", "div)", "div <script>", "div /* x */", "x".repeat(600), "div:has(url(x))")) assertEquals(bad, "", BlockRules.validSelector(bad))
    }

    @Test
    fun elementRulesMakeOneBlockOfCssPerHost() {
        val l = BlockList()
        assertTrue(l.addElement("site.test", "#promo").added)
        assertFalse(l.addElement("site.test", "#promo").added)
        assertTrue(l.addElement("site.test", "div.popup").added)
        assertTrue(l.addElement("other.test", ".x").added)
        assertFalse(l.addElement("site.test", "a{x:y}").ok)
        val css = l.cssFor("www.site.test")
        assertEquals("#promo{display:none!important}\ndiv.popup{display:none!important}", css)
        assertEquals("", l.cssFor("example.org"))
        assertTrue(l.removeElement("site.test", "#promo"))
        assertEquals("div.popup{display:none!important}", l.cssFor("www.site.test"))
    }

    @Test
    fun anImportedListTakesHostsHostsFileLinesAndElementRules() {
        val l = BlockList()
        val r = l.importText(listOf("! comment", "# another", "[Adblock Plus 2.0]", "", "0.0.0.0 evil.test", "127.0.0.1 localhost", "||ads.test^\$third-party", "plain.test", "site.test##.overlay", "##.generic", "@@||ok.test^", "/ads/*.js", "a b c").joinToString("\n"))
        assertEquals(3, r.hosts)
        assertEquals(1, r.elements)
        assertTrue(r.skipped >= 4)
        assertEquals("evil.test", l.hostBlocked("evil.test"))
        assertEquals("", l.hostBlocked("ok.test"))
        assertEquals(".overlay{display:none!important}", l.cssFor("site.test"))
    }

    @Test
    fun theListStopsGrowingAtTheLimit() {
        val l = BlockList()
        val text = (0 until BlockRules.MAX_RULES + 50).joinToString("\n") { "h$it.example.com" }
        val r = l.importText(text)
        assertEquals(BlockRules.MAX_RULES, r.hosts)
        assertTrue(r.full)
        assertFalse(l.addHost("one-more.example.com").ok)
    }

    @Test
    fun sitesFollowTheSameRulesAsTheDesktopBuild() {
        assertEquals("example.com", Sites.siteOfHost("cdn.example.com"))
        assertEquals("example.co.uk", Sites.siteOfHost("a.b.example.co.uk"))
        assertEquals("127.0.0.1", Sites.siteOfHost("127.0.0.1"))
        assertEquals("cdn.test", Sites.hostOfUrl("https://user@cdn.test:8443/x?y#z"))
        assertEquals("::1", Sites.hostOfUrl("http://[::1]:80/"))
    }
}
