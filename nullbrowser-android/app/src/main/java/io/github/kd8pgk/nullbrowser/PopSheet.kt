package io.github.kd8pgk.nullbrowser

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.Typeface
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class PopSheet(private val activity: Activity, private val guard: PopGuard, private val importList: () -> Unit) {
    private val dialog = Dialog(activity, R.style.Theme_NullBrowser)
    private val foundBox = LinearLayout(activity)
    private val logBox = LinearLayout(activity)
    private val listBox = LinearLayout(activity)
    private val noteView = TextView(activity)
    private val countsView = TextView(activity)
    private val pickButton = Button(activity)

    private fun dp(n: Int): Int = (n * activity.resources.displayMetrics.density).toInt()

    private fun color(id: Int): Int = activity.resources.getColor(id, activity.theme)

    private fun text(value: String, size: Float, colorId: Int, bold: Boolean = false): TextView {
        val t = TextView(activity)
        t.text = value
        t.textSize = size
        t.setTextColor(color(colorId))
        if (bold) t.setTypeface(t.typeface, Typeface.BOLD)
        return t
    }

    private fun button(label: String, onClick: () -> Unit): Button {
        val b = Button(activity, null, android.R.attr.buttonStyleSmall)
        b.text = label
        b.isAllCaps = false
        b.minWidth = 0
        b.setOnClickListener { onClick() }
        return b
    }

    private fun section(title: String): LinearLayout {
        val box = LinearLayout(activity)
        box.orientation = LinearLayout.VERTICAL
        val t = text(title, 15f, R.color.amber, true)
        t.setPadding(0, dp(14), 0, dp(6))
        box.addView(t)
        return box
    }

    private fun row(title: String, sub: String, buttons: List<Pair<String, () -> Unit>>): View {
        val card = LinearLayout(activity)
        card.orientation = LinearLayout.VERTICAL
        card.setBackgroundColor(color(R.color.card))
        card.setPadding(dp(10), dp(8), dp(10), dp(8))
        val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        lp.bottomMargin = dp(6)
        card.layoutParams = lp
        card.addView(text(title, 14f, R.color.text))
        if (sub.isNotEmpty()) card.addView(text(sub, 12f, R.color.muted))
        if (buttons.isNotEmpty()) {
            val scroll = HorizontalScrollView(activity)
            val line = LinearLayout(activity)
            line.orientation = LinearLayout.HORIZONTAL
            for ((label, fn) in buttons) line.addView(button(label, fn))
            scroll.addView(line)
            card.addView(scroll)
        }
        return card
    }

    private fun empty(message: String): View = text(message, 13f, R.color.muted).also { it.setPadding(0, 0, 0, dp(6)) }

    init {
        val root = LinearLayout(activity)
        root.orientation = LinearLayout.VERTICAL
        root.setBackgroundColor(color(R.color.bg))

        val head = LinearLayout(activity)
        head.orientation = LinearLayout.HORIZONTAL
        head.gravity = Gravity.CENTER_VERTICAL
        head.setBackgroundColor(color(R.color.bar))
        head.setPadding(dp(12), dp(8), dp(8), dp(8))
        val title = text("Pop-ups", 18f, R.color.amber, true)
        head.addView(title, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        head.addView(button("Close") { dialog.dismiss() })
        root.addView(head)

        val scroll = ScrollView(activity)
        val content = LinearLayout(activity)
        content.orientation = LinearLayout.VERTICAL
        content.setPadding(dp(12), dp(8), dp(12), dp(24))

        val actions = HorizontalScrollView(activity)
        val actionLine = LinearLayout(activity)
        actionLine.orientation = LinearLayout.HORIZONTAL
        actionLine.addView(button("Find on this page") { guard.find() })
        pickButton.text = "Pick"
        pickButton.isAllCaps = false
        pickButton.minWidth = 0
        pickButton.setOnClickListener {
            if (guard.state().picking) {
                guard.pick()
            } else {
                guard.pick()
                dialog.dismiss()
            }
        }
        actionLine.addView(pickButton)
        actionLine.addView(button("Import list…") { importList() })
        actions.addView(actionLine)
        content.addView(actions)

        noteView.textSize = 13f
        noteView.setTextColor(color(R.color.muted))
        noteView.setPadding(0, dp(8), 0, 0)
        content.addView(noteView)

        foundBox.orientation = LinearLayout.VERTICAL
        logBox.orientation = LinearLayout.VERTICAL
        listBox.orientation = LinearLayout.VERTICAL

        val s1 = section("On this page")
        s1.addView(foundBox)
        content.addView(s1)

        val s2 = section("Tried this run")
        s2.addView(logBox)
        s2.addView(button("Clear the log") { guard.clearLog() })
        content.addView(s2)

        val s3 = section("Block list")
        countsView.textSize = 13f
        countsView.setTextColor(color(R.color.muted))
        countsView.setPadding(0, 0, 0, dp(6))
        s3.addView(countsView)
        s3.addView(listBox)
        content.addView(s3)

        scroll.addView(content)
        root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        dialog.setContentView(root)
        dialog.window?.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(Color.BLACK))
    }

    fun show() {
        render()
        dialog.show()
    }

    fun isShowing(): Boolean = dialog.isShowing

    fun refresh() {
        if (dialog.isShowing) render()
    }

    fun dismiss() {
        if (dialog.isShowing) dialog.dismiss()
    }

    private fun render() {
        val st = guard.state()
        pickButton.text = if (st.picking) "Stop picking" else "Pick"
        noteView.text = st.note
        noteView.visibility = if (st.note.isEmpty()) View.GONE else View.VISIBLE

        foundBox.removeAllViews()
        val kinds = mapOf("frame" to "Ad frame", "overlay" to "Overlay", "cover" to "Covers the page", "picked" to "Picked")
        for (f in st.found) {
            val hosts = (listOf(if (f.thirdParty) f.frameHost else "") + f.hosts).filter { it.isNotEmpty() }.distinct().take(3)
            val buttons = ArrayList<Pair<String, () -> Unit>>()
            if (f.selector.isNotEmpty()) {
                buttons.add("Show" to { guard.show(f.id) })
                buttons.add("Hide" to { guard.hide(f.id) })
            }
            for (h in hosts) buttons.add("Block $h" to { guard.blockFound(f.id, h) })
            foundBox.addView(row("${kinds[f.kind] ?: "Item"}: ${f.tag} ${f.w}×${f.h} · ${f.frameHost}", listOf(f.text, f.selector).filter { it.isNotEmpty() }.joinToString("  ·  "), buttons))
        }
        if (st.found.isEmpty()) foundBox.addView(empty("Nothing listed. Use Find on this page, or Pick."))

        logBox.removeAllViews()
        val words = mapOf("window" to "pop-up window", "jump" to "jump to another site")
        for (e in st.log) {
            val buttons = ArrayList<Pair<String, () -> Unit>>()
            if (e.action != "blocked" && e.host.isNotEmpty()) buttons.add("Block ${e.host}" to { guard.blockLogged(e.id) })
            val target = if (e.host.isEmpty()) "an unknown address" else e.host
            logBox.addView(row("${e.action}: ${words[e.kind] ?: e.kind} to $target${if (e.n > 1) " ×${e.n}" else ""}", "from ${e.from}", buttons))
        }
        if (st.log.isEmpty()) logBox.addView(empty("Nothing has tried to open a window or jump away yet."))

        val snap = st.snapshot
        countsView.text = "${snap.hostCount} blocked host${if (snap.hostCount == 1) "" else "s"}, ${snap.elementCount} hidden element rule${if (snap.elementCount == 1) "" else "s"}. Kept only until Null Browser closes."
        listBox.removeAllViews()
        for (h in snap.hosts) {
            val n = st.hits[h]
            listBox.addView(row(h + if (n != null) "  ·  blocked $n request${if (n == 1) "" else "s"}" else "", "", listOf("Remove" to { guard.removeHost(h) })))
        }
        for ((h, s) in snap.elements) listBox.addView(row(h, "hide $s", listOf("Remove" to { guard.removeElement(h, s) })))
    }
}
