package io.github.kd8pgk.nodetalker

import android.app.Activity
import android.app.AlertDialog
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONObject
import java.io.IOException
import java.net.URLEncoder
import java.util.concurrent.Executors

class ConnectTab(private val act: Activity, private val root: View, private val host: Host) : StatusFeed.Listener {
    interface Host {
        val node: Node
        val feed: StatusFeed
        fun readPage(js: String, done: (String?) -> Unit)
        fun pickTab(name: String)
        fun flashListen(color: Int, text: String)
        fun listenFlashIs(text: String): Boolean
        fun stopPageTests()
        fun openLink(uri: Uri)
    }

    private class Last(val b: TuneBody, val snap: ConnectModel.Remembered, var seen: Boolean)

    private class NetAsk(val url: String, val body: TuneBody?, val favIndex: Int, val label: String, val onTune: Boolean)

    private class Size(val h: Int = 40, val font: Int = 14)

    private var favIndexSet = 0
    private var pickValues: List<String> = emptyList()
    private var favsLoaded = false
    private var netAskBody: JSONObject? = null
    private val ui = Handler(Looper.getMainLooper())
    private val io = Executors.newCachedThreadPool { r -> Thread(r, "nt-connect").also { it.isDaemon = true } }
    private val model = ConnectModel()
    private var shown = false
    private var authed = false
    private var primed = false
    private var tuneDone = false
    private var favSel: Int? = null
    private var last: Last? = null
    private var netAsk: NetAsk? = null
    private var connBusy = false
    private var daPoll = false
    private var daMine = false
    private var daList = "md380-emu, Analog_Bridge, MMDVM_Bridge, USRP2M17 and Asterisk"
    private var size = Size()
    private var seq = 0
    private var suppress = false
    private val timers = HashMap<TextView, Runnable>()
    private var findTimer: Runnable? = null
    private var connMsgTimer: Runnable? = null

    private val favEmpty = root.findViewById<TextView>(R.id.c_empty)
    private val favBox = root.findViewById<View>(R.id.c_pick)
    private val fav = root.findViewById<Spinner>(R.id.c_fav)
    private val cMode = root.findViewById<TextView>(R.id.c_mode)
    private val cNum = root.findViewById<TextView>(R.id.c_num)
    private val cLabel = root.findViewById<TextView>(R.id.c_label)
    private val cGo = root.findViewById<Button>(R.id.c_connect)
    private val cMsg = root.findViewById<TextView>(R.id.c_msg)
    private val cAsk = root.findViewById<View>(R.id.c_net)
    private val tList = root.findViewById<TextView>(R.id.t_list)
    private val tMsg = root.findViewById<TextView>(R.id.t_msg)
    private val tAsk = root.findViewById<View>(R.id.t_ask)
    private val tNow = root.findViewById<TextView>(R.id.t_now)
    private val daBtn = root.findViewById<Button>(R.id.da_btn)
    private val daMsg = root.findViewById<TextView>(R.id.da_msg)

    private val gap = dp(1)
    private val grid = GridLayout(act).apply { columnCount = 3 }
    private val tMode = Spinner(act, Spinner.MODE_DIALOG)
    private val tNet = Spinner(act, Spinner.MODE_DIALOG)
    private val tMod = Spinner(act, Spinner.MODE_DIALOG)
    private val tFind = EditText(act)
    private val tPick = Spinner(act, Spinner.MODE_DIALOG)
    private val tLh = Button(act)
    private val tSave = Button(act)
    private val tGo = Button(act)

    init {
        root.findViewById<LinearLayout>(R.id.t_rows).addView(grid, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        cell(tMode, 1)
        cell(tNet, 1)
        cell(tMod, 1)
        cell(tFind, 2)
        cell(tPick, 2)
        cell(tLh, 1)
        cell(tSave, 1)
        cell(tGo, 3)
        for (s in listOf(tMode, tNet, tMod, tPick)) s.background = act.getDrawable(R.drawable.bg_spinner)
        tFind.background = act.getDrawable(R.drawable.bg_field)
        tFind.setTextColor(act.getColor(R.color.text))
        tFind.setHintTextColor(act.getColor(R.color.muted))
        tFind.setPadding(dp(10), 0, dp(10), 0)
        tFind.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        tFind.imeOptions = EditorInfo.IME_ACTION_GO
        tFind.setSingleLine()
        tLh.text = act.getString(R.string.tune_lh)
        tSave.text = act.getString(R.string.tune_save)
        for (b in listOf(tLh, tSave, tGo)) {
            b.isAllCaps = false
            b.setPadding(dp(4), 0, dp(4), 0)
        }
        tGo.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 15f)
        tGo.minimumHeight = dp(44)
        tGo.typeface = android.graphics.Typeface.DEFAULT_BOLD
        tLh.minimumHeight = dp(40)
        tLh.minHeight = dp(40)
        tSave.setBackgroundResource(R.drawable.btn_plain)
        tLh.setBackgroundResource(R.drawable.btn_plain)
        tSave.setTextColor(act.getColor(R.color.text))
        tLh.setTextColor(act.getColor(R.color.text))
        cGo.minimumHeight = dp(40)

        fav.adapter = adapter(emptyList(), 14f)
        fav.onItemSelectedListener = pickListener { pos ->
            if (pos != favIndexSet) {
                favIndexSet = pos
                showSelected()
            }
        }
        tMode.adapter = adapter(Tn.MODES.map { Tn.modeName(it) }, size.font.toFloat())
        tMode.onItemSelectedListener = pickListener { pos ->
            val m = Tn.MODES[pos]
            if (m != model.mode) {
                model.mode = m
                onMode(false)
            }
        }
        tNet.onItemSelectedListener = pickListener { pos ->
            val n = model.favNets.getOrNull(pos) ?: ""
            if (n != model.net) {
                model.net = n
                buttons()
                remember()
            }
        }
        tMod.onItemSelectedListener = pickListener { pos ->
            val v = model.modulesFor().getOrNull(pos) ?: return@pickListener
            if (v != model.mod) {
                model.mod = v
                buttons()
                remember()
            }
        }
        tPick.onItemSelectedListener = pickListener { pos ->
            val v = pickValues.getOrNull(pos) ?: return@pickListener
            if (v != model.pick) {
                model.pick = v
                refreshMods()
                buttons()
                remember()
            }
        }
        tFind.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
            override fun afterTextChanged(s: Editable?) {
                if (suppress) return
                model.find = s?.toString().orEmpty()
                buttons()
                findTimer?.let { ui.removeCallbacks(it) }
                val m = model.mode
                val t = Runnable {
                    if (Tn.SEARCH.contains(m)) search(m, null) else renderFill(null)
                    remember()
                }
                findTimer = t
                ui.postDelayed(t, if (Tn.SEARCH.contains(m)) 300L else 150L)
            }
        })
        tFind.setOnEditorActionListener { _, id, ev ->
            if (id == EditorInfo.IME_ACTION_GO || (ev != null && ev.keyCode == KeyEvent.KEYCODE_ENTER && ev.action == KeyEvent.ACTION_DOWN)) {
                tuneConnect()
                true
            } else {
                false
            }
        }
        tGo.setOnClickListener { if (linkedNow()) tuneOff() else tuneConnect() }
        tLh.setOnClickListener {
            val u = model.link()
            if (u.isNotEmpty()) host.openLink(Uri.parse(u))
        }
        tSave.setOnClickListener { tuneSave() }
        cGo.setOnClickListener { favConnect() }
        root.findViewById<View>(R.id.c_net_add).setOnClickListener { netAnswer("add") }
        root.findViewById<View>(R.id.c_net_once).setOnClickListener { netAnswer("once") }
        root.findViewById<View>(R.id.c_net_no).setOnClickListener { netAnswer("") }
        root.findViewById<View>(R.id.t_net_add).setOnClickListener { netAnswer("add") }
        root.findViewById<View>(R.id.t_net_once).setOnClickListener { netAnswer("once") }
        root.findViewById<View>(R.id.t_net_no).setOnClickListener { netAnswer("") }
        daBtn.setBackgroundResource(R.drawable.btn_danger)
        daBtn.setTextColor(act.getColor(R.color.red))
        daBtn.setOnClickListener { disconnectAll() }
        model.mode = "ASL"
        applyVisibility()
        applySize()
        style(cGo, false)
        style(tGo, false)
        fillNets()
        renderFill(null)
    }

    private fun dp(v: Int) = (v * act.resources.displayMetrics.density).toInt()

    private fun cell(v: View, span: Int) {
        val lp = GridLayout.LayoutParams(GridLayout.spec(GridLayout.UNDEFINED), GridLayout.spec(GridLayout.UNDEFINED, span, 1f))
        lp.width = 0
        lp.height = dp(size.h)
        lp.setMargins(gap, gap, gap, gap)
        grid.addView(v, lp)
    }

    private fun adapter(items: List<String>, fontSp: Float): ArrayAdapter<String> =
        object : ArrayAdapter<String>(act, R.layout.item_spinner, items) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View =
                (super.getView(position, convertView, parent) as TextView).also { it.textSize = fontSp }
        }.also { it.setDropDownViewResource(R.layout.item_spinner_drop) }

    private fun pickListener(on: (Int) -> Unit) = object : AdapterView.OnItemSelectedListener {
        override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) = on(position)
        override fun onNothingSelected(parent: AdapterView<*>?) = Unit
    }

    private fun setSpin(s: Spinner, items: List<String>, index: Int) {
        s.adapter = adapter(items, size.font.toFloat())
        s.setSelection(index.coerceIn(0, maxOf(items.size - 1, 0)), false)
    }

    private fun style(b: Button, danger: Boolean) {
        b.setBackgroundResource(if (danger) R.drawable.btn_danger else R.drawable.btn_primary)
        b.setTextColor(act.getColor(if (danger) R.color.red else R.color.accent_ink))
        b.typeface = android.graphics.Typeface.DEFAULT_BOLD
    }

    private fun msg(tv: TextView, kind: Int, text: String) {
        tv.setTextColor(act.getColor(when (kind) {
            1 -> R.color.accent
            2 -> R.color.amber
            3 -> R.color.red
            else -> R.color.text
        }))
        tv.text = text
    }

    private fun result(tv: TextView, d: JSONObject) {
        val ok = d.optBoolean("ok")
        val text = if (ok) d.optString("message").ifEmpty { "Done." } else d.optString("error").ifEmpty { "Failed." }
        msg(tv, if (d.optBoolean("warn")) 2 else if (ok) 1 else 3, text)
        timers.remove(tv)?.let { ui.removeCallbacks(it) }
        val shownText = tv.text.toString()
        val t = Runnable { if (tv.text.toString() == shownText) msg(tv, 0, "") }
        timers[tv] = t
        ui.postDelayed(t, 30000)
    }

    private fun clearMsg(tv: TextView) {
        timers.remove(tv)?.let { ui.removeCallbacks(it) }
        msg(tv, 0, "")
    }

    private fun api() = NodeApi(host.node)

    private fun call(post: Boolean, path: String, body: JSONObject = JSONObject(), done: (JSONObject) -> Unit) {
        io.execute {
            val d = try {
                if (post) api().postLoose(path, body) else api().getLoose(path)
            } catch (e: NodeApi.NotLoggedIn) {
                JSONObject().put("ok", false).put("error", "Log in on the Setup tab first.")
            } catch (e: IOException) {
                JSONObject().put("ok", false).put("error", "Node Talker is not answering.")
            }
            ui.post { done(d) }
        }
    }

    fun show() {
        if (shown) return
        shown = true
        root.visibility = View.VISIBLE
        host.feed.add(this)
        host.readPage(SIZE_JS) { raw ->
            if (!shown) return@readPage
            size = parseSize(raw)
            applySize()
        }
        enter()
    }

    fun hide() {
        if (!shown) return
        shown = false
        root.visibility = View.GONE
        host.feed.remove(this)
    }

    fun reset() {
        hide()
        authed = false
        primed = false
        tuneDone = false
        favSel = null
        last = null
        netAsk = null
        model.lists.clear()
        model.remembered = ConnectModel.Remembered()
        model.favs = emptyList()
        favsLoaded = false
    }

    private fun enter() {
        if (!favsLoaded) loadFavs()
        connectTabEnter()
    }

    private fun connectTabEnter() {
        if (model.favs.isNotEmpty()) {
            val i = if (tuneDone && favSel != null && favSel!! < model.favs.size) favSel!! else 0
            setFavIndex(i)
            showSelected()
        }
        val l = last
        if (l != null && model.linked(l.b)) setSel(l.snap) else setSel(model.defaultSel())
        if (!daPoll) daStatus()
    }

    private fun setFavIndex(i: Int) {
        favIndexSet = i
        fav.setSelection(i, false)
    }

    private fun loadFavs() {
        call(false, "/api/favorites") { d ->
            if (!d.optBoolean("ok")) return@call
            favsLoaded = true
            authed = true
            val f = Favorites.parse(d)
            model.favs = f.favs
            model.favNets = f.nets
            model.favNetLinks = f.netLinks
            val keep = favIndexSet
            fav.adapter = adapter(model.favLabels(), 14f)
            fillNets()
            val i = if (keep < model.favs.size) keep else 0
            setFavIndex(i)
            favEmpty.visibility = if (model.favs.isEmpty()) View.VISIBLE else View.GONE
            favBox.visibility = if (model.favs.isEmpty()) View.GONE else View.VISIBLE
            showSelected()
            if (!primed) setSel(model.defaultSel())
        }
    }

    private fun showSelected() {
        val f = model.favs.getOrNull(favIndexSet)
        cMode.visibility = if (f == null) View.INVISIBLE else View.VISIBLE
        cMode.text = f?.let { Tn.modeName(it.mode) }.orEmpty()
        cNum.text = f?.numText.orEmpty()
        cLabel.text = f?.label.orEmpty()
        connectLabel()
    }

    private fun connectLabel() {
        val on = model.selectedFavLinked(favIndexSet)
        cGo.text = act.getString(if (on) R.string.connect_off else R.string.connect_go)
        style(cGo, on)
    }

    private fun favConnect() {
        val i = favIndexSet
        val f = model.favs.getOrNull(i) ?: return
        val off = model.selectedFavLinked(i)
        netHide()
        if (!off) {
            val tune = f.mode == "M17" || Tn.DVS.contains(f.mode)
            val name = f.label.ifEmpty { "the favorite" }
            connectFlow(
                "/api/connect", JSONObject().put("index", i),
                (if (tune) "Tuning " else "Connecting to ") + name + "...",
                if (tune) "Tuning..." else "Connecting... (checking the link for up to 15 s)",
                true, null, i,
            ) { ok -> if (ok) { tuneDone = true; favSel = i } }
            return
        }
        cGo.isEnabled = false
        msg(cMsg, 0, "Disconnecting...")
        call(true, "/api/disconnect", JSONObject().put("index", i)) { d ->
            cGo.isEnabled = true
            result(cMsg, d)
            host.feed.pokeAfter(1000)
        }
    }

    private fun connectFlow(
        url: String, body: JSONObject, listenText: String, connectText: String, onFav: Boolean,
        tb: TuneBody?, favIndex: Int, done: (Boolean) -> Unit,
    ) {
        val btn = if (onFav) cGo else tGo
        val box = if (onFav) cMsg else tMsg
        val ask = if (onFav) cAsk else tAsk
        btn.isEnabled = false
        connBusy = true
        msg(box, 0, connectText)
        host.pickTab("listen")
        connMsgTimer?.let { ui.removeCallbacks(it) }
        connMsgTimer = null
        host.flashListen(R.color.text, listenText)
        call(true, url, body) { d ->
            btn.isEnabled = true
            connBusy = false
            result(box, d)
            if (d.optBoolean("ok")) {
                val text = d.optString("message").ifEmpty { "Done." }
                host.flashListen(if (d.optBoolean("warn")) R.color.amber else R.color.accent, text)
                val t = Runnable { if (host.listenFlashIs(text)) host.flashListen(R.color.text, "") }
                connMsgTimer = t
                ui.postDelayed(t, 8000)
            } else {
                if (host.listenFlashIs(listenText)) host.flashListen(R.color.text, "")
                host.pickTab("connect")
                if (d.optBoolean("need_net")) {
                    netAsk = NetAsk(url, tb, favIndex, listenText, !onFav)
                    netAskBody = body
                    ask.visibility = View.VISIBLE
                }
            }
            buttons()
            connectLabel()
            host.feed.poke()
            done(d.optBoolean("ok"))
        }
    }

    private fun netHide() {
        cAsk.visibility = View.GONE
        tAsk.visibility = View.GONE
        netAsk = null
        netAskBody = null
    }

    private fun netAnswer(action: String) {
        val a = netAsk
        val body = netAskBody
        netHide()
        if (a == null || body == null) return
        if (action.isEmpty()) {
            clearMsg(if (a.onTune) tMsg else cMsg)
            return
        }
        val text = if (action == "add") "Adding the network to Node Controller and tuning..." else "Tuning..."
        val again = JSONObject(body.toString()).put("net_action", action)
        connectFlow(a.url, again, a.label, text, !a.onTune, a.body, a.favIndex) { ok ->
            if (ok && a.onTune && a.body != null) afterTune(a.body)
            if (ok && !a.onTune) { tuneDone = true; favSel = a.favIndex }
        }
    }

    private fun applyVisibility() {
        val m = model.mode
        tNet.visibility = if (m == "DMR") View.VISIBLE else View.GONE
        tMod.visibility = if (m == "DSTAR" || m == "M17") View.VISIBLE else View.GONE
        tPick.visibility = if (m == "DMR") View.GONE else View.VISIBLE
        tFind.hint = Tn.HINT[m]
    }

    private fun setFind(text: String) {
        suppress = true
        tFind.setText(text)
        tFind.setSelection(text.length)
        suppress = false
        model.find = text
    }

    private fun remember() {
        model.remember()
    }

    private fun fillNets() {
        val keep = model.net.ifEmpty { model.remembered.net }
        val nets = model.favNets
        setSpin(tNet, if (nets.isEmpty()) listOf("No networks") else nets, nets.indexOf(keep))
        model.net = if (keep.isNotEmpty() && nets.contains(keep)) keep else nets.firstOrNull() ?: ""
        val m = model.mode
        if (m == "DMR") {
            renderFill(null)
        } else if (Tn.SEARCH.contains(m)) {
            if (model.lists[m] == null) search(m, null)
        } else {
            loadList(m, null)
        }
    }

    private fun refreshMods() {
        model.applyModules()
        val list = model.modulesFor()
        setSpin(tMod, list.map { if (it == "@ALL") "All" else it }, list.indexOf(model.mod))
    }

    private fun onMode(first: Boolean) {
        val m = model.mode
        netHide()
        clearMsg(tMsg)
        applyVisibility()
        if (!first) setFind("")
        refreshMods()
        renderFill(if (first) model.remembered.pick else "")
        if (Tn.SEARCH.contains(m)) {
            if (authed) search(m, if (first) model.remembered.pick else null)
        } else if (m != "DMR" && authed) {
            loadList(m, if (first) model.remembered.pick else null)
        }
        if (!first) remember()
    }

    private fun setSel(s: ConnectModel.Remembered) {
        primed = true
        model.remembered = ConnectModel.Remembered(s.mode, s.net, s.mod, s.find, s.pick)
        model.mode = s.mode
        setFind(s.find)
        val mi = Tn.MODES.indexOf(s.mode)
        suppress = true
        tMode.setSelection(maxOf(mi, 0), false)
        suppress = false
        onMode(true)
        if (s.net.isNotEmpty() && model.favNets.contains(s.net)) {
            model.net = s.net
            tNet.setSelection(model.favNets.indexOf(s.net), false)
        }
        if (s.mod.isNotEmpty() && model.modulesFor().contains(s.mod)) {
            model.mod = s.mod
            tMod.setSelection(model.modulesFor().indexOf(s.mod), false)
        }
        buttons()
    }

    private fun renderFill(want: String?) {
        val m = model.mode
        val v = model.fill(want)
        if (m == "DMR") {
            tList.text = v.hint
            buttons()
            return
        }
        pickValues = v.options.map { it.value }
        setSpin(tPick, v.options.map { it.text }, pickValues.indexOf(v.selected))
        tPick.isEnabled = v.enabled
        tList.text = v.hint
        if (m == "M17") refreshMods()
        buttons()
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private fun loadList(m: String, want: String?) {
        val c = model.lists[m]
        val now = System.currentTimeMillis()
        if (c != null && (c.loading || now - c.at < 300000)) return
        model.lists[m] = TuneList(rows = c?.rows.orEmpty(), found = c?.found ?: false, files = c?.files.orEmpty(), loading = true, at = now)
        if (c == null) renderFill(want)
        call(false, "/api/tune-list?mode=" + enc(m)) { d ->
            model.lists[m] = if (d.optBoolean("ok")) TuneList.fromList(d, System.currentTimeMillis())
            else TuneList(rows = c?.rows.orEmpty(), found = c?.found ?: false, files = c?.files.orEmpty(), err = d.optString("error").ifEmpty { "Could not load the list." }, at = 0)
            if (model.mode == m) renderFill(want)
        }
    }

    private fun search(m: String, want: String?) {
        val q = tFind.text.toString().trim()
        val mine = ++seq
        if (q.length < 2) {
            model.lists[m] = TuneList.shortQuery()
            renderFill(want)
            return
        }
        call(false, "/api/tune-search?mode=" + enc(m) + "&q=" + enc(q)) { d ->
            if (mine != seq || model.mode != m) return@call
            model.lists[m] = TuneList.fromSearch(d)
            renderFill(want)
        }
    }

    private fun linkedNow() = model.linked(model.body())

    private fun buttons() {
        val b = model.buttons()
        tGo.text = act.getString(if (b.goDanger) R.string.connect_off else R.string.connect_go)
        style(tGo, b.goDanger)
        tGo.isEnabled = !connBusy && (b.goDanger || model.body() != null)
        tSave.isEnabled = b.saveEnabled
        tLh.alpha = if (b.lhOn) 1f else 0.45f
        tLh.isEnabled = b.lhOn
    }

    private fun tuneConnect() {
        val b = model.body() ?: return
        if (connBusy) return
        netHide()
        remember()
        val link = Tn.SEARCH.contains(b.mode)
        connectFlow(
            "/api/tune", b.toJson(), (if (link) "Connecting to " else "Tuning ") + b.name + "...",
            if (link) "Connecting... (checking the link for up to 15 s)" else "Tuning...", false, b, -1,
        ) { ok -> if (ok) afterTune(b) }
    }

    private fun afterTune(b: TuneBody) {
        last = Last(b, ConnectModel.Remembered(model.mode, model.net, model.mod, model.find, model.pick), false)
        tuneDone = true
        val f = model.findFavFor(b)
        if (f != null) favSel = model.favs.indexOf(f)
    }

    private fun tuneSave() {
        val b = model.body() ?: return
        tSave.isEnabled = false
        call(true, "/api/tune/save", b.toJson()) { d ->
            result(tMsg, d)
            buttons()
            loadFavs()
        }
    }

    private fun tuneOff() {
        last = null
        msg(tMsg, 0, "Disconnecting...")
        val b = if (Tn.SEARCH.contains(model.mode)) model.body() else null
        if (Tn.SEARCH.contains(model.mode) && b == null) {
            msg(tMsg, 2, "Pick or type the node to disconnect.")
            return
        }
        call(true, "/api/tune/disconnect", b?.toJson() ?: JSONObject()) { d ->
            result(tMsg, d)
            buttons()
            host.feed.pokeAfter(1000)
        }
    }

    private fun disconnectAll() {
        AlertDialog.Builder(act)
            .setMessage(
                "Disconnect All?\n\nStops any transmission or test, drops every link and restarts " +
                    daList.ifEmpty { "the node services" } + ". The node is off the air until they are back up, up to a minute or two.",
            )
            .setPositiveButton(R.string.ok) { _, _ -> startDisconnectAll() }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun startDisconnectAll() {
        host.stopPageTests()
        daBtn.isEnabled = false
        call(true, "/api/disconnect-all") { d ->
            if (!d.optBoolean("ok")) {
                daBtn.isEnabled = true
                msg(daMsg, 3, d.optString("error").ifEmpty { "Could not start Disconnect All." })
                return@call
            }
            daMine = true
            last = null
            msg(daMsg, 2, d.optString("message").ifEmpty { "Disconnect All started." })
            daStatus()
        }
    }

    private fun daStatus() {
        daPoll = true
        call(false, "/api/disconnect-all/status") { d ->
            daPoll = false
            daShow(d)
            if (d.optBoolean("ok") && d.optBoolean("running")) {
                if (shown) {
                    daPoll = true
                    ui.postDelayed({ daPoll = false; if (shown) daStatus() }, 1000)
                }
                return@call
            }
            if (d.optBoolean("ok") && daMine && d.optBoolean("finished")) {
                last = null
                buttons()
                host.feed.poke()
            }
        }
    }

    private fun daShow(d: JSONObject) {
        if (!d.optBoolean("ok")) return
        d.optJSONArray("installed")?.let { a ->
            daList = (0 until a.length()).joinToString(", ") { a.optString(it) }
        }
        daBtn.isEnabled = !d.optBoolean("running")
        val steps = d.optJSONArray("steps")
        val n = steps?.length() ?: 0
        if (d.optBoolean("running")) {
            var i = -1
            for (k in 0 until n) if (steps!!.getJSONObject(k).optString("state") == "running") { i = k; break }
            msg(daMsg, 2, if (i >= 0) steps!!.getJSONObject(i).optString("name") + "... (" + (i + 1) + " of " + n + ")" else "Working...")
        } else if (daMine && d.optString("message").isNotEmpty()) {
            val bad = ArrayList<String>()
            for (k in 0 until n) {
                val s = steps!!.getJSONObject(k)
                val st = s.optString("state")
                if (st == "failed" || st == "warn") bad.add(s.optString("name") + ": " + s.optString("note"))
            }
            msg(
                daMsg, if (d.optString("level") == "err") 3 else if (bad.isNotEmpty()) 2 else 1,
                d.optString("message") + (if (bad.isNotEmpty()) " " + bad.joinToString("; ") + "." else ""),
            )
        }
    }

    override fun onStatus(s: NodeStatus) {
        authed = true
        model.linkedTargets = ConnectModel.linkedTargetsOf(s.links, s.m17, s.tuned)
        model.tunedNow = s.tunedNow
        model.defaultMode = s.defaultMode
        connectLabel()
        tNow.text = if (s.tunedNow.isNotEmpty()) "Tuned: " + s.tunedNow else ""
        val l = last
        if (l != null) {
            if (model.linked(l.b)) l.seen = true else if (l.seen) last = null
        }
        if (!primed) setSel(model.defaultSel())
        buttons()
    }

    override fun onLost() = Unit

    private fun applySize() {
        for (v in listOf(tMode, tNet, tMod, tFind, tPick, tSave)) {
            v.layoutParams = (v.layoutParams as GridLayout.LayoutParams).also { it.height = dp(size.h) }
        }
        tFind.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, size.font.toFloat())
        tSave.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, size.font.toFloat())
        tLh.setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f)
        grid.requestLayout()
        for (s in listOf(tMode, tNet, tMod, tPick)) {
            val a = s.adapter as? ArrayAdapter<*> ?: continue
            s.adapter = adapter((0 until a.count).map { a.getItem(it).toString() }, size.font.toFloat())
        }
        setSpin(tMode, Tn.MODES.map { Tn.modeName(it) }, Tn.MODES.indexOf(model.mode))
        fillNetsSpin()
        refreshModsSpin()
        renderFill(null)
    }

    private fun fillNetsSpin() {
        val nets = model.favNets
        setSpin(tNet, if (nets.isEmpty()) listOf("No networks") else nets, nets.indexOf(model.net))
    }

    private fun refreshModsSpin() {
        val list = model.modulesFor()
        setSpin(tMod, list.map { if (it == "@ALL") "All" else it }, list.indexOf(model.mod))
    }

    companion object {
        const val SIZE_JS = "(function(){try{var s=localStorage.getItem('nlTuneSize');return s?s:null}catch(e){return null}})()"

        private fun parseSize(raw: String?): Size {
            if (raw.isNullOrEmpty() || raw == "null") return Size()
            return try {
                val text = org.json.JSONTokener(raw).nextValue() as? String ?: return Size()
                val o = JSONObject(text)
                val h = o.optInt("h", 40).takeIf { it in 28..72 } ?: 40
                val f = o.optInt("font", 14).takeIf { it in 10..22 } ?: 14
                Size(h, f)
            } catch (e: org.json.JSONException) {
                Size()
            }
        }
    }
}
