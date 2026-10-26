package io.github.kd8pgk.nodetalker

import android.content.res.ColorStateList
import android.graphics.Typeface
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView

class TabBar(private val bar: View, private val pick: (String) -> Unit) {
    private val tabs = mapOf(
        "connect" to bar.findViewById<ViewGroup>(R.id.tab_connect),
        "listen" to bar.findViewById<ViewGroup>(R.id.tab_listen),
        "setup" to bar.findViewById<ViewGroup>(R.id.tab_setup),
    )

    init {
        tabs.forEach { (name, cell) -> cell.setOnClickListener { pick(name) } }
        select("")
    }

    fun select(name: String) {
        bar.visibility = if (name in tabs) View.VISIBLE else View.GONE
        tabs.forEach { (n, cell) -> paint(cell, n == name) }
    }

    private fun paint(cell: ViewGroup, on: Boolean) {
        val color = bar.context.getColor(if (on) R.color.accent else R.color.muted)
        (cell.getChildAt(0) as ImageView).imageTintList = ColorStateList.valueOf(color)
        (cell.getChildAt(1) as TextView).apply {
            setTextColor(color)
            typeface = if (on) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        }
        cell.isSelected = on
    }

    companion object {
        val NAMES = setOf("connect", "listen", "setup")

        fun clickJs(name: String): String =
            "(function(){var b=document.getElementById('nav-" + name + "');if(b)b.click()})()"

        const val HIDE_PAGE_NAV_JS = "(function(){var n=document.getElementById('nav');if(!n||window.__ntBar)return;" +
            "window.__ntBar=1;var s=document.createElement('style');s.textContent='#nav{display:none!important}';" +
            "document.head.appendChild(s);var last=null;function cur(){if(n.classList.contains('hidden'))return '';" +
            "var b=n.querySelector('[aria-current]');return b?b.id.replace('nav-',''):''}" +
            "function tell(){var c=cur();if(c!==last){last=c;NodeTalkerApp.tabChanged(c)}}" +
            "new MutationObserver(tell).observe(n,{attributes:true,subtree:true,attributeFilter:['aria-current','class']});tell()})()"
    }
}
