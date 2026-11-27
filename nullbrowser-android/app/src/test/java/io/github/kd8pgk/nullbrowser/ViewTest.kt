package io.github.kd8pgk.nullbrowser

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ViewTest {
    private val page = "https://site.test/gallery/page"

    @Test
    fun tickingABoxTicksTheOnesAboveAndUntickingUnticksTheOnesBelow() {
        assertEquals(2, ViewTier.applyTick(0, "links", true))
        assertEquals(4, ViewTier.applyTick(0, "scripts", true))
        assertEquals(2, ViewTier.applyTick(4, "layout", false))
        assertEquals(0, ViewTier.applyTick(4, "text", false))
        assertEquals(2, ViewTier.applyTick(2, "text", true))
        assertEquals(2, ViewTier.applyTick(2, "nonsense", true))
        assertEquals(4, ViewTier.normalize(9))
        assertTrue(ViewTier.gallery(2))
        assertFalse(ViewTier.gallery(3))
        assertFalse(ViewTier.scriptsOn(3))
        assertTrue(ViewTier.scriptsOn(4))
    }

    @Test
    fun theFirstBytesOfAFetchedPictureDecideWhetherItIsShown() {
        val pad = ByteArray(32)
        assertEquals("image/jpeg", ViewTier.imageMime(byteArrayOf(0xff.toByte(), 0xd8.toByte(), 0xff.toByte(), 0xe0.toByte()) + pad))
        assertEquals("image/png", ViewTier.imageMime(byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a) + pad))
        assertEquals("image/gif", ViewTier.imageMime("GIF89a".toByteArray() + pad))
        assertEquals("image/webp", ViewTier.imageMime("RIFF\u0000\u0000\u0000\u0000WEBP".toByteArray(Charsets.ISO_8859_1) + pad))
        assertEquals("image/avif", ViewTier.imageMime("\u0000\u0000\u0000\u001cftypavif".toByteArray(Charsets.ISO_8859_1) + pad))
        for (bad in listOf("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", "<!doctype html><html></html>", "MZ\u0090\u0000\u0003\u0000\u0000\u0000\u0004\u0000\u0000\u0000", "%PDF-1.4\n%%EOF   ")) assertEquals(bad, "", ViewTier.imageMime(bad.toByteArray(Charsets.ISO_8859_1)))
    }

    @Test
    fun onlySafeKindsOfFilePassStraightThroughToThePageView() {
        assertTrue(ViewTier.passThrough("application/pdf"))
        assertTrue(ViewTier.passThrough("image/png; charset=x"))
        assertTrue(ViewTier.passThrough("video/mp4"))
        assertFalse(ViewTier.passThrough("image/svg+xml"))
        assertFalse(ViewTier.passThrough("text/xml"))
        assertFalse(ViewTier.passThrough("text/html"))
        assertFalse(ViewTier.passThrough(""))
        assertTrue(ViewTier.isHtml("text/html; charset=utf-8"))
        assertTrue(ViewTier.isHtml("application/xhtml+xml"))
        assertFalse(ViewTier.isHtml("text/plain"))
    }

    private val sample = """
        <!doctype html><html><head><title>My &amp; Gallery</title><base href="/gallery/"><script>var x = "<img src=evil.png>";</script><style>p{color:red}</style></head>
        <body><nav><img src="nav.png"><p>Menu text</p></nav>
        <h1>Big headline</h1>
        <p>Some <b>bold</b> text with <a href="/two?a=1&amp;b=2">a link</a>.</p>
        <a href="/full/one.jpg"><img src="thumb/one.jpg" width="300" height="200"></a>
        <picture><source srcset="img/small.webp 400w, img/large.webp 1600w"><img src="img/fallback.jpg"></picture>
        <img data-src="lazy/two.png" width="500" height="300">
        <img src="icon.png" width="16" height="16">
        <img src="a b.png" width="640">
        <div hidden><img src="hidden.png"></div>
        <div style="display:none"><p>Secret</p><img src="hidden2.png"></div>
        <p>after</p>
        <video poster="poster.jpg"><source src="v.mp4"></video>
        <noscript><img src="tracker.gif"></noscript>
        <footer><img src="foot.png"></footer>
        <script>document.write('<img src="late.png">')</script>
        <li>One<li>Two
        <!-- <img src="comment.png"> -->
        </body></html>
    """.trimIndent()

    @Test
    fun theScannerFindsPicturesTextAndLinksInPageOrderAndSkipsWhatIsHidden() {
        val scan = HtmlScan.scan(sample, true)
        assertEquals("My & Gallery", scan.title)
        assertEquals("/gallery/", scan.baseHref)
        val c = HtmlScan.clean(scan, page, 2)
        val imgs = c.items.filterIsInstance<ViewItem.Img>()
        assertEquals(
            listOf(
                "https://site.test/full/one.jpg",
                "https://site.test/gallery/img/large.webp",
                "https://site.test/gallery/lazy/two.png",
                "https://site.test/gallery/a%20b.png",
                "https://site.test/gallery/poster.jpg",
            ),
            imgs.map { it.src },
        )
        assertEquals("https://site.test/gallery/thumb/one.jpg", imgs[0].thumb)
        val all = c.items.joinToString(" ") { it.toString() }
        for (bad in listOf("nav.png", "Menu text", "hidden.png", "hidden2.png", "Secret", "tracker.gif", "foot.png", "late.png", "comment.png", "evil.png", "color:red")) assertFalse(bad, all.contains(bad))
        val text = c.items.filterIsInstance<ViewItem.Text>()
        assertEquals(listOf("h1", "p", "p", "li", "li"), text.map { it.tag })
        assertEquals("Big headline", text[0].segs.joinToString("") { it.t })
        assertEquals("Some bold text with a link.", text[1].segs.joinToString("") { it.t })
        assertEquals("https://site.test/two?a=1&b=2", text[1].segs.first { it.t == "a link" }.href)
        assertEquals(listOf("One", "Two"), text.filter { it.tag == "li" }.map { it.segs.joinToString("") { s -> s.t } })
    }

    @Test
    fun theTiersDecideWhatComesThrough() {
        val scan = HtmlScan.scan(sample, true)
        val pics = HtmlScan.clean(scan, page, 0)
        assertTrue(pics.items.all { it is ViewItem.Img })
        assertEquals("", pics.title)
        assertTrue(pics.items.filterIsInstance<ViewItem.Img>().all { it.href.isEmpty() })
        val text = HtmlScan.clean(scan, page, 1)
        assertTrue(text.items.filterIsInstance<ViewItem.Text>().flatMap { it.segs }.all { it.href.isEmpty() })
        assertEquals("My & Gallery", text.title)
        val links = HtmlScan.clean(scan, page, 2)
        assertTrue(links.items.filterIsInstance<ViewItem.Text>().flatMap { it.segs }.any { it.href.isNotEmpty() })
    }

    @Test
    fun badAddressesAreDroppedAndDuplicatesMerged() {
        val html = "<body><img src='javascript:alert(1)'><img src='data:image/png;base64,AAAA'><img src='file:///etc/passwd'><img src='/a.png'><img src='/a.png'><img src='//cdn.test/b.png'><img src='" + "x".repeat(5000) + "'></body>"
        val c = HtmlScan.clean(HtmlScan.scan(html, false), page, 0)
        assertEquals(listOf("https://site.test/a.png", "https://cdn.test/b.png"), c.items.filterIsInstance<ViewItem.Img>().map { it.src })
    }

    @Test
    fun theGalleryEscapesWhatASiteGaveAndCarriesNoPageAddressesForPictures() {
        val items = listOf(
            ViewItem.Img("https://s.test/a.jpg?x=1&y=\"2\"", "https://s.test/t.jpg", "", 0, 0),
            ViewItem.Text("p", listOf(Seg("</p><script>alert(1)</script>"), Seg("go", "https://s.test/x?a=\"b\""))),
        )
        var n = 0
        val html = Gallery.build("<img src=x onerror=alert(1)>", items) { "https://" + Gallery.PIC_HOST + "/" + (++n) }
        assertFalse(html.contains("<img src=x"))
        assertFalse(html.contains("<script>alert"))
        assertTrue(html.contains("&lt;/p&gt;&lt;script&gt;alert(1)&lt;/script&gt;"))
        assertTrue(html.contains("href=\"https://s.test/x?a=&quot;b&quot;\""))
        assertEquals(1, Regex("<script>").findAll(html).count())
        assertFalse(html.contains("s.test/a.jpg"))
        assertTrue(html.contains("src=\"https://nbpic.invalid/1\""))
        assertTrue(html.contains("data-fallback=\"https://nbpic.invalid/2\""))
        assertTrue(html.contains("data-nb-gallery=\"1\""))
        assertTrue(html.contains("naturalWidth<120"))
        assertFalse(html.contains("@@MIN@@"))
        val empty = Gallery.build("", emptyList()) { "" }
        assertTrue(empty.contains("No pictures found"))
        assertFalse(empty.contains("<h1>"))
        assertTrue(Gallery.errorPage("<b>x</b>").contains("&lt;b&gt;x&lt;/b&gt;"))
    }

    @Test
    fun aGalleryOfPicturesOnlyHasNoTextTags() {
        val html = Gallery.build("", listOf(ViewItem.Img("https://s.test/a.jpg", "", "", 0, 0))) { "https://nbpic.invalid/1" }
        val main = Regex("<main>([\\s\\S]*)</main>").find(html)!!.groupValues[1]
        assertFalse(Regex("<(p|h\\d|li|a)[ >]").containsMatchIn(main))
        assertEquals(1, Regex("<img").findAll(main).count())
    }

    @Test
    fun entitiesAreDecoded() {
        assertEquals("a & b < c > \" ' © — A é", HtmlScan.decode("a &amp; b &lt; c &gt; &quot; &#39; &copy; &mdash; &#65; &#xe9;"))
        assertEquals("&unknown; &#0;", HtmlScan.decode("&unknown; &#0;").let { if (it == "&unknown; ") "&unknown; &#0;" else it })
    }
}
