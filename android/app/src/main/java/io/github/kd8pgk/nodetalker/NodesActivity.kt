package io.github.kd8pgk.nodetalker

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import java.util.UUID

class NodesActivity : Activity() {
    private lateinit var list: ListView
    private lateinit var empty: TextView
    private var nodes: List<Node> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_nodes)
        fitInsets(findViewById(R.id.root))
        list = findViewById(R.id.list)
        empty = findViewById(R.id.empty)
        list.adapter = adapter
        list.setOnItemClickListener { _, _, pos, _ -> open(nodes[pos]) }
        list.setOnItemLongClickListener { _, _, pos, _ -> manage(nodes[pos]); true }
        findViewById<Button>(R.id.add).setOnClickListener { edit(null) }
        val keep = findViewById<CheckBox>(R.id.keep_on)
        keep.isChecked = NodeStore.keepScreenOn(this)
        keep.setOnCheckedChangeListener { _, on -> NodeStore.setKeepScreenOn(this, on) }
        findViewById<TextView>(R.id.version).text = getString(R.string.app_version, BuildConfig.VERSION_NAME)
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        nodes = NodeStore.all(this)
        adapter.notifyDataSetChanged()
        list.visibility = if (nodes.isEmpty()) View.GONE else View.VISIBLE
        empty.visibility = if (nodes.isEmpty()) View.VISIBLE else View.GONE
    }

    private val adapter = object : BaseAdapter() {
        override fun getCount() = nodes.size
        override fun getItem(position: Int) = nodes[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val v = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.row_node, parent, false)
            val n = nodes[position]
            v.findViewById<TextView>(R.id.name).text = n.title
            v.findViewById<TextView>(R.id.url).text = n.origin
            return v
        }
    }

    private fun open(n: Node) {
        startActivity(Intent(this, TalkerActivity::class.java).putExtra(TalkerActivity.EXTRA_NODE, n.id))
    }

    private fun manage(n: Node) {
        val items = mutableListOf(getString(R.string.edit), getString(R.string.delete))
        if (n.pin.isNotEmpty()) items.add(getString(R.string.forget_cert))
        AlertDialog.Builder(this)
            .setTitle(n.title)
            .setItems(items.toTypedArray()) { _, which ->
                when (which) {
                    0 -> edit(n)
                    1 -> AlertDialog.Builder(this)
                        .setMessage(getString(R.string.delete_confirm, n.title))
                        .setPositiveButton(R.string.delete) { _, _ -> NodeStore.delete(this, n.id); refresh() }
                        .setNegativeButton(R.string.cancel, null)
                        .show()
                    2 -> {
                        NodeStore.put(this, n.copy(pin = ""))
                        Toast.makeText(this, R.string.cert_forgotten, Toast.LENGTH_LONG).show()
                        refresh()
                    }
                }
            }
            .show()
    }

    private fun edit(n: Node?) {
        val v = LayoutInflater.from(this).inflate(R.layout.dialog_node, null)
        val name = v.findViewById<EditText>(R.id.name)
        val address = v.findViewById<EditText>(R.id.address)
        val port = v.findViewById<EditText>(R.id.port)
        val https = v.findViewById<CheckBox>(R.id.https)
        name.setText(n?.name.orEmpty())
        address.setText(n?.host.orEmpty())
        port.setText(String.format(java.util.Locale.ROOT, "%d", n?.port ?: Node.DEFAULT_PORT))
        https.isChecked = n?.https ?: false
        val dlg = AlertDialog.Builder(this)
            .setTitle(if (n == null) R.string.edit_title_add else R.string.edit_title_edit)
            .setView(v)
            .setPositiveButton(R.string.save, null)
            .setNegativeButton(R.string.cancel, null)
            .create()
        dlg.setOnShowListener {
            dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val (host, p, h) = Node.parseAddress(address.text.toString())
                if (!Node.validHost(host)) {
                    address.error = getString(R.string.bad_address)
                    return@setOnClickListener
                }
                val portNum = p ?: port.text.toString().trim().toIntOrNull()
                if (portNum == null || portNum !in 1..65535) {
                    port.error = getString(R.string.bad_port)
                    return@setOnClickListener
                }
                val useHttps = h ?: https.isChecked
                val same = n != null && n.host.equals(host, true) && n.port == portNum && n.https == useHttps
                NodeStore.put(
                    this,
                    Node(n?.id ?: UUID.randomUUID().toString(), name.text.toString().trim(), host, portNum, useHttps,
                        if (same) n!!.pin else ""),
                )
                dlg.dismiss()
                refresh()
            }
        }
        dlg.show()
    }

    companion object {
        fun fitInsets(root: View) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.VANILLA_ICE_CREAM) return
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                val ime = insets.getInsets(WindowInsets.Type.ime())
                view.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
                WindowInsets.CONSUMED
            }
        }
    }
}
