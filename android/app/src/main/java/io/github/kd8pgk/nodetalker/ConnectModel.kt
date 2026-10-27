package io.github.kd8pgk.nodetalker

import org.json.JSONArray
import org.json.JSONObject

object Tn {
    val MODES = listOf("ASL", "EchoLink", "DMR", "STFU", "YSF", "P25", "NXDN", "DSTAR", "M17")
    val SEARCH = listOf("ASL", "EchoLink")
    val DVS = listOf("DMR", "STFU", "YSF", "P25", "NXDN", "DSTAR")
    val HINT = mapOf(
        "ASL" to "Node #, call or place", "EchoLink" to "Node # or call", "DMR" to "TG number", "STFU" to "TG, ID or name",
        "YSF" to "Name, # or IP:port", "P25" to "TG # or host", "NXDN" to "TG # or host", "DSTAR" to "REF001 C or callsign",
        "M17" to "M17-USA A",
    )
    val NOUN = mapOf(
        "ASL" to "nodes", "EchoLink" to "stations", "STFU" to "talkgroups", "YSF" to "reflectors", "P25" to "talkgroups",
        "NXDN" to "talkgroups", "DSTAR" to "reflectors", "M17" to "reflectors",
    )
    const val LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    val TYPED = mapOf(
        "ASL" to Regex("^\\d{1,7}$"), "EchoLink" to Regex("^\\d{1,6}$"), "DMR" to Regex("^\\d{1,8}$"),
        "STFU" to Regex("^\\d{1,8}$"), "P25" to Regex("^\\d{1,8}$"), "NXDN" to Regex("^\\d{1,8}$"),
        "YSF" to Regex("^(\\d{1,5}|[A-Za-z0-9.-]+:\\d{1,5})$"),
        "DSTAR" to Regex("^(?:(?:REF|XRF|DCS)\\d{3}|[A-Z0-9]{1,3}\\d[A-Z]{1,4})(?:\\s+[A-Z])?$", RegexOption.IGNORE_CASE),
        "M17" to Regex("^[A-Z0-9]+-[A-Z0-9-]{1,14}(?:\\s+(?:[A-Z]|@ALL))?$", RegexOption.IGNORE_CASE),
    )

    fun modeName(m: String) = if (m == "DSTAR") "D-STAR" else m
}

data class Fav(
    val mode: String,
    val num: String,
    val net: String,
    val module: String?,
    val label: String,
    val target: String,
) {
    val numText: String
        get() = when (mode) {
            "M17" -> num + (if (!module.isNullOrEmpty()) " $module" else "")
            "DMR" -> (if (net.isNotEmpty()) "$net " else "") + num
            "DSTAR" -> num.trim().replace(Regex(" +"), " ")
            else -> num
        }

    val listLabel: String
        get() = label.ifEmpty { Tn.modeName(mode) + " " + numText }

    companion object {
        fun from(o: JSONObject) = Fav(
            o.optString("mode"), o.optString("num"), o.optString("net"),
            if (o.has("module") && !o.isNull("module")) o.optString("module") else null,
            o.optString("label"), o.optString("target"),
        )
    }
}

data class Favorites(val favs: List<Fav>, val nets: List<String>, val netLinks: Map<String, String>, val max: Int) {
    companion object {
        fun parse(d: JSONObject): Favorites {
            val arr = d.optJSONArray("favs") ?: JSONArray()
            val nets = d.optJSONArray("nets") ?: JSONArray()
            val links = d.optJSONObject("net_links") ?: JSONObject()
            return Favorites(
                (0 until arr.length()).mapNotNull { arr.optJSONObject(it)?.let(Fav::from) },
                (0 until nets.length()).map { nets.optString(it) },
                links.keys().asSequence().associateWith { links.optString(it) },
                if (d.has("max")) d.optInt("max", 10) else 10,
            )
        }
    }
}

class TuneList(
    val rows: List<List<String>> = emptyList(),
    val found: Boolean = false,
    val files: List<String> = emptyList(),
    val search: Boolean = false,
    val short: Boolean = false,
    val count: Int = 0,
    val err: String = "",
    val loading: Boolean = false,
    val at: Long = 0,
) {
    val text: List<String> = rows.map { (it[0] + " " + it[1]).lowercase() }

    companion object {
        private fun rowsOf(a: JSONArray?): List<List<String>> {
            if (a == null) return emptyList()
            return (0 until a.length()).mapNotNull { i ->
                val r = a.optJSONArray(i) ?: return@mapNotNull null
                if (r.length() < 2) null else (0 until r.length()).map { r.optString(it) }
            }
        }

        private fun filesOf(a: JSONArray?): List<String> = if (a == null) emptyList() else (0 until a.length()).map { a.optString(it) }

        fun fromList(d: JSONObject, now: Long) = TuneList(
            rows = rowsOf(d.optJSONArray("rows")), found = d.optBoolean("found"), files = filesOf(d.optJSONArray("files")), at = now,
        )

        fun fromSearch(d: JSONObject): TuneList = TuneList(
            rows = rowsOf(d.optJSONArray("rows")), found = d.optBoolean("found"),
            files = if (d.has("file") && !d.isNull("file") && d.optString("file").isNotEmpty()) listOf(d.optString("file")) else emptyList(),
            search = true, count = d.optInt("count"),
            err = if (d.optBoolean("ok")) "" else d.optString("error").ifEmpty { "Search failed." },
        )

        fun failed(error: String) = TuneList(err = error.ifEmpty { "Could not load the list." }, at = 0)

        fun shortQuery() = TuneList(search = true, short = true, found = true)
    }
}

data class PickOption(val value: String, val text: String)

class PickView(val options: List<PickOption>, val selected: String, val enabled: Boolean, val hint: String)

data class TuneBody(val mode: String, val num: String, val net: String?, val module: String?, val label: String?) {
    fun toJson(): JSONObject {
        val o = JSONObject().put("mode", mode)
        if (net != null) o.put("net", net)
        o.put("num", num)
        if (label != null) o.put("label", label)
        if (module != null) o.put("module", module)
        return o
    }

    val name: String
        get() = Tn.modeName(mode) + (if (!net.isNullOrEmpty()) " $net" else "") + " " + (label?.takeIf { it.isNotEmpty() } ?: num) +
            (if (!module.isNullOrEmpty() && !Regex("\\s").containsMatchIn(num)) " $module" else "")
}

class ButtonState(val go: String, val goDanger: Boolean, val goEnabled: Boolean, val saveEnabled: Boolean, val lhOn: Boolean)

class ConnectModel {
    var favs: List<Fav> = emptyList()
    var favNets: List<String> = emptyList()
    var favNetLinks: Map<String, String> = emptyMap()
    var linkedTargets: Set<String> = emptySet()
    var tunedNow = ""
    var defaultMode = ""
    var busy = false

    var mode = "ASL"
    var net = ""
    var mod = ""
    var find = ""
    var pick = ""
    var pickEnabled = true

    val lists = HashMap<String, TuneList>()
    var remembered = Remembered()

    class Remembered(var mode: String = "", var net: String = "", var mod: String = "", var find: String = "", var pick: String = "")

    fun remember() {
        remembered = Remembered(mode, net.ifEmpty { remembered.net }, mod, find, pick)
    }

    fun modulesFor(): List<String> {
        val r = row()
        val letters = if (mode == "M17") "@ALL".let { listOf(it) } + (if (r != null && r.size > 3 && r[3].isNotEmpty()) r[3] else Tn.LETTERS).map { it.toString() }
        else Tn.LETTERS.map { it.toString() }
        return letters
    }

    fun applyModules() {
        val keep = mod.ifEmpty { remembered.mod }
        val list = modulesFor()
        mod = if (list.contains(keep)) keep else (if (mode == "M17") "@ALL" else "C")
    }

    fun row(): List<String>? {
        val s = lists[mode]
        return if (s != null && pick.isNotEmpty()) s.rows.firstOrNull { it[0] == pick } else null
    }

    fun fill(want: String? = null): PickView {
        val m = mode
        val s = lists[m]
        if (m == "DMR") {
            val hint = if (favNets.isNotEmpty()) "Type the talkgroup number." else "Add a DMR network on the Setup tab (Digital card) first."
            return PickView(emptyList(), pick, pickEnabled, hint)
        }
        val keep = want ?: pick.ifEmpty { remembered.pick }
        fun done(opts: List<PickOption>, sel: String, en: Boolean, hint: String): PickView {
            pick = sel
            pickEnabled = en
            return PickView(opts, sel, en, hint)
        }
        if (s != null && s.search && (s.short || !s.found || s.err.isNotEmpty())) {
            val hint = if (s.err.isNotEmpty()) s.err
            else if (s.short) "Type 2 or more characters to search, or a " + (if (m == "ASL") "node" else "station") + " number."
            else "No " + (if (m == "ASL") "AllStar node list (" + (s.files.firstOrNull() ?: "astdb.txt") + ")" else "EchoLink station list (is EchoLink loaded in Asterisk?)") + " was found. You can still type a number."
            return done(listOf(PickOption("", "Type to search...")), "", false, hint)
        }
        if (s == null || s.loading || !s.found) {
            val hint = if (s == null || s.loading) "Loading the " + Tn.modeName(m) + " list..."
            else (s.err.ifEmpty { "No " + Tn.modeName(m) + " list was found on the Pi." }) + " You can still type one."
            return done(listOf(PickOption("", if (s != null && !s.loading) "No list" else "Loading...")), "", false, hint)
        }
        val words = find.lowercase().split(Regex("\\s+")).filter { it.isNotEmpty() }
        val list = if (s.search) s.rows else s.rows.filterIndexed { i, _ -> words.all { w -> s.text[i].contains(w) } }
        val opts = ArrayList<PickOption>()
        opts.add(PickOption("", if (list.isNotEmpty()) "Select... (" + grouped(list.size) + ")" else "No matches"))
        list.forEach { opts.add(PickOption(it[0], it[1])) }
        var sel = ""
        if (keep.isNotEmpty() && list.any { it[0] == keep }) sel = keep
        else if (list.size == 1) sel = list[0][0]
        val n = list.size
        val t = if (s.search) s.count else s.rows.size
        val noun = Tn.NOUN[m] ?: ""
        val nounText = if (t == 1) noun.dropLast(1) else noun
        val files = s.files.joinToString(", ")
        val hint = if (s.search) {
            if (t == 0) "No matches ($files)."
            else if (n < t) "Showing $n of ${grouped(t)} matches ($files). Type more to narrow it down."
            else grouped(t) + " " + (if (t == 1) "match" else "matches") + " ($files)."
        } else {
            (if (n == t) grouped(t) + " " + nounText else "Showing " + grouped(n) + " of " + grouped(t) + " " + nounText) + " ($files)."
        }
        val out = done(opts, sel, list.isNotEmpty(), hint)
        if (m == "M17") applyModules()
        return out
    }

    private fun grouped(n: Int): String = java.text.NumberFormat.getIntegerInstance().format(n.toLong())

    fun typed(): String {
        val t = find.trim()
        return if (Tn.TYPED.getValue(mode).containsMatchIn(t)) t else ""
    }

    fun body(): TuneBody? {
        val m = mode
        val r = row()
        val typed = typed()
        var num: String
        var net: String? = null
        var label: String? = null
        var module: String? = null
        if (m == "DMR") {
            net = this.net
            num = typed
        } else if (r != null) {
            num = r[0]
            if (m in listOf("YSF", "STFU", "ASL", "EchoLink")) label = r[1]
        } else {
            num = typed
        }
        if (m == "DSTAR" || m == "M17") module = mod
        return if (num.isNotEmpty() && (m != "DMR" || !net.isNullOrEmpty())) TuneBody(m, num, net, module, label) else null
    }

    fun findFavFor(tb: TuneBody): Fav? = favs.firstOrNull {
        it.mode == tb.mode && it.num == tb.num && (tb.mode != "DMR" || it.net == (tb.net ?: "")) &&
            ((tb.mode != "M17" && tb.mode != "DSTAR") || it.module == tb.module)
    }

    fun linked(tb: TuneBody?): Boolean {
        if (tb == null) return false
        val fav = findFavFor(tb)
        if (fav != null) return linkedTargets.contains(fav.target)
        return tunedNow.isNotEmpty() && tunedNow.contains(tb.num)
    }

    fun link(): String {
        if (mode == "DMR") return favNetLinks[net] ?: ""
        val r = row()
        return if (r != null && r.size > 2) r[2] else ""
    }

    fun buttons(): ButtonState {
        val b = body()
        val ok = b != null
        val on = linked(b)
        return ButtonState(if (on) "Disconnect" else "Connect", on, !busy && (on || ok), ok, link().isNotEmpty())
    }

    fun defaultSel(): Remembered = Remembered(if (Tn.MODES.contains(defaultMode)) defaultMode else "ASL")

    fun selectedFavLinked(index: Int): Boolean = index in favs.indices && linkedTargets.contains(favs[index].target)

    fun favLabels(): List<String> = favs.map { it.listLabel }

    companion object {
        fun linkedTargetsOf(links: List<String>, m17: String, tuned: String): Set<String> {
            val s = HashSet(links)
            if (m17.isNotEmpty()) s.add(m17)
            if (tuned.isNotEmpty()) s.add(tuned)
            return s
        }
    }
}
