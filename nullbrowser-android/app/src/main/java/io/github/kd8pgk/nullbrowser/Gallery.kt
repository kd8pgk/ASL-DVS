package io.github.kd8pgk.nullbrowser

object Gallery {
    const val PIC_HOST = "nbpic.invalid"
    const val CSP = "default-src 'none'; img-src https://nbpic.invalid; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'; connect-src 'none'"

    private const val STYLE = """html{background:#0d0d0d;color:#d8d8d8}body{margin:0;font:16px/1.55 system-ui,sans-serif}main{max-width:960px;margin:0 auto;padding:1rem}main img{display:block;width:100%;height:auto;margin:0 0 1rem;background:#1a1a1a;cursor:zoom-in}main a.pl{display:block}main p,main li,main blockquote,main figcaption,main pre,main h1,main h2,main h3,main h4,main h5,main h6{margin:0 0 1rem;overflow-wrap:anywhere}main h1,main h2,main h3,main h4,main h5,main h6{color:#fff;line-height:1.25}main pre{white-space:pre-wrap}main li{list-style:none}main li:before{content:"\2022  "}main blockquote{border-left:3px solid #444;padding-left:1rem;color:#bbb}a{color:#6cf}.note{color:#777;text-align:center;margin:3rem 0}#lb{position:fixed;inset:0;background:rgba(0,0,0,.94);display:flex;align-items:center;justify-content:center;z-index:9}#lb[hidden]{display:none}#lb img{max-width:100vw;max-height:100vh;object-fit:contain;cursor:zoom-out}#lb a,#lb button{position:fixed;background:#222;color:#fff;border:1px solid #555;border-radius:4px;padding:.4rem .8rem;font:inherit;cursor:pointer;text-decoration:none}#lbx{top:.6rem;right:.6rem}#lbp{left:.6rem;top:50%}#lbn{right:.6rem;top:50%}#lbl{left:.6rem;top:.6rem}#lbl[hidden]{display:none}"""

    private const val SCRIPT = """(function(){var lb=document.getElementById('lb'),big=document.getElementById('lbi'),lk=document.getElementById('lbl'),at=0;function pics(){return Array.prototype.slice.call(document.querySelectorAll('main img'))}function show(i){var p=pics();if(!p.length)return;at=(i+p.length)%p.length;big.src=p[at].getAttribute('src');var h=p[at].getAttribute('data-href');if(h){lk.href=h;lk.hidden=false}else{lk.hidden=true}lb.hidden=false}function hide(){lb.hidden=true;big.removeAttribute('src')}document.addEventListener('load',function(e){var t=e.target;if(t&&t.tagName==='IMG'&&t.closest('main')&&(t.naturalWidth<@@MIN@@||t.naturalHeight<@@MIN@@)){var a=t.parentNode;if(a&&a.tagName==='A'&&a.className==='pl')a.remove();else t.remove()}},true);document.addEventListener('error',function(e){var t=e.target;if(t&&t.tagName==='IMG'&&t.closest('main')){var f=t.getAttribute('data-fallback');if(f&&t.getAttribute('src')!==f){t.setAttribute('src',f)}else{var a=t.parentNode;if(a&&a.tagName==='A'&&a.className==='pl')a.remove();else t.remove()}}},true);document.addEventListener('click',function(e){var t=e.target;if(t&&t.tagName==='IMG'&&t.closest('main')){e.preventDefault();show(pics().indexOf(t));return}if(t&&t.id==='lbi'||t&&t.id==='lbx'||t===lb){hide();return}if(t&&t.id==='lbp'){show(at-1);return}if(t&&t.id==='lbn'){show(at+1)}});document.addEventListener('keydown',function(e){if(lb.hidden)return;if(e.key==='Escape')hide();else if(e.key==='ArrowLeft')show(at-1);else if(e.key==='ArrowRight'||e.key===' ')show(at+1)});})();"""

    private const val LIGHTBOX = """<div id="lb" hidden><img id="lbi" alt=""><button id="lbx" type="button">&#10005;</button><button id="lbp" type="button">&#8249;</button><button id="lbn" type="button">&#8250;</button><a id="lbl" hidden rel="noopener noreferrer">Open link</a></div>"""

    fun esc(value: String): String = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&#39;")

    private fun segs(list: List<Seg>): String = list.joinToString("") {
        if (it.href.isNotEmpty()) "<a href=\"" + esc(it.href) + "\" rel=\"noopener noreferrer\">" + esc(it.t) + "</a>" else esc(it.t)
    }

    fun build(title: String, items: List<ViewItem>, picUrl: (String) -> String): String {
        val parts = ArrayList<String>()
        if (title.isNotEmpty()) parts.add("<h1>" + esc(title) + "</h1>")
        var pics = 0
        for (it in items) {
            when (it) {
                is ViewItem.Img -> {
                    val u = picUrl(it.src)
                    if (u.isEmpty()) continue
                    pics += 1
                    val fb = if (it.thumb.isNotEmpty()) picUrl(it.thumb) else ""
                    parts.add("<img src=\"" + esc(u) + "\" alt=\"\" loading=\"lazy\" decoding=\"async\"" + (if (fb.isNotEmpty()) " data-fallback=\"" + esc(fb) + "\"" else "") + (if (it.href.isNotEmpty()) " data-href=\"" + esc(it.href) + "\"" else "") + ">")
                }
                is ViewItem.Text -> parts.add("<" + it.tag + ">" + segs(it.segs) + "</" + it.tag + ">")
            }
        }
        if (pics == 0) parts.add("<p class=\"note\">No pictures found on this page.</p>")
        val heading = if (title.isNotEmpty()) esc(title.take(200)) else "Pictures"
        return "<!doctype html><html lang=\"en\" data-nb-gallery=\"1\"><head><meta charset=\"utf-8\"><meta name=\"referrer\" content=\"no-referrer\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>" + heading + "</title><style>" + STYLE + "</style></head><body><main>" + parts.joinToString("\n") + "</main>" + LIGHTBOX + "<script>" + SCRIPT.replace("@@MIN@@", ViewTier.MIN_SIDE.toString()) + "</script></body></html>"
    }

    fun errorPage(message: String): String =
        "<!doctype html><html lang=\"en\" data-nb-gallery=\"1\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Pictures</title><style>" + STYLE + "</style></head><body><main><p class=\"note\">" + esc(message) + "</p></main></body></html>"
}
