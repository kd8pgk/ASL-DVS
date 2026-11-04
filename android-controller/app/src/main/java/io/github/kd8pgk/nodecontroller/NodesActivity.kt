package io.github.kd8pgk.nodecontroller

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.widget.ArrayAdapter
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
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
        list = findViewById(R.id.node_list)
        empty = findViewById(R.id.empty_text)
        findViewById<View>(R.id.add_node).setOnClickListener { editNode(null) }
        list.setOnItemClickListener { _, _, pos, _ -> open(nodes[pos]) }
        list.setOnItemLongClickListener { _, _, pos, _ -> manage(nodes[pos]); true }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        nodes = NodeStore.all(this)
        list.adapter = object : ArrayAdapter<Node>(this, android.R.layout.simple_list_item_2, android.R.id.text1, nodes) {
            override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
                val v = super.getView(position, convertView, parent)
                v.findViewById<TextView>(android.R.id.text2).text = getItem(position)?.address?.origin.orEmpty()
                return v
            }
        }
        empty.visibility = if (nodes.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun open(node: Node) {
        startActivity(Intent(this, DashboardActivity::class.java).putExtra(DashboardActivity.EXTRA_NODE, node.id))
    }

    private fun manage(node: Node) {
        AlertDialog.Builder(this)
            .setTitle(node.title)
            .setItems(arrayOf(getString(R.string.edit), getString(R.string.delete))) { _, which ->
                if (which == 0) editNode(node) else confirmDelete(node)
            }
            .show()
    }

    private fun confirmDelete(node: Node) {
        AlertDialog.Builder(this)
            .setMessage(getString(R.string.delete_confirm, node.title))
            .setPositiveButton(R.string.delete) { _, _ ->
                NodeStore.delete(this, node.id)
                refresh()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun editNode(existing: Node?) {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, 0)
        }
        val nameBox = EditText(this).apply {
            hint = getString(R.string.name_hint)
            setText(existing?.name.orEmpty())
            inputType = InputType.TYPE_CLASS_TEXT
        }
        val addressBox = EditText(this).apply {
            hint = getString(R.string.address_hint)
            setText(existing?.address?.origin.orEmpty())
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        box.addView(nameBox)
        box.addView(addressBox)
        val dialog = AlertDialog.Builder(this)
            .setTitle(if (existing == null) R.string.add_node else R.string.edit_node)
            .setView(box)
            .setPositiveButton(R.string.save, null)
            .setNegativeButton(R.string.cancel, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val address = NodeAddress.parse(addressBox.text.toString())
                if (address == null) {
                    Toast.makeText(this, R.string.bad_address, Toast.LENGTH_LONG).show()
                    return@setOnClickListener
                }
                NodeStore.put(this, Node(existing?.id ?: UUID.randomUUID().toString(), nameBox.text.toString().trim(), address))
                dialog.dismiss()
                refresh()
            }
        }
        dialog.show()
    }
}
