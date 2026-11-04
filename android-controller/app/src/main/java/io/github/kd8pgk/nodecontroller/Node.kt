package io.github.kd8pgk.nodecontroller

import android.content.Context
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.util.UUID

data class Node(val id: String, val name: String, val address: NodeAddress) {
    val title: String
        get() = name.ifBlank { address.host }

    fun toJson(): JSONObject = JSONObject()
        .put("id", id).put("name", name).put("host", address.host)
        .put("port", address.port).put("https", address.https)

    companion object {
        fun fromJson(o: JSONObject): Node? {
            val host = o.optString("host")
            val port = o.optInt("port", -1)
            if (!NodeAddress.validHost(host) || port !in 1..65535) return null
            val id = o.optString("id").ifEmpty { UUID.randomUUID().toString() }
            return Node(id, o.optString("name"), NodeAddress(host, port, o.optBoolean("https")))
        }
    }
}

object NodeStore {
    private const val PREFS = "nodecontroller"
    private const val KEY_NODES = "nodes"

    private fun prefs(c: Context) = c.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun all(c: Context): List<Node> {
        val arr = try {
            JSONArray(prefs(c).getString(KEY_NODES, "[]"))
        } catch (e: JSONException) {
            JSONArray()
        }
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it)?.let(Node::fromJson) }
    }

    private fun write(c: Context, nodes: List<Node>) {
        val arr = JSONArray()
        nodes.forEach { arr.put(it.toJson()) }
        prefs(c).edit().putString(KEY_NODES, arr.toString()).apply()
    }

    fun get(c: Context, id: String?) = all(c).firstOrNull { it.id == id }

    fun put(c: Context, node: Node) {
        val list = all(c).toMutableList()
        val i = list.indexOfFirst { it.id == node.id }
        if (i >= 0) list[i] = node else list.add(node)
        write(c, list)
    }

    fun delete(c: Context, id: String) = write(c, all(c).filter { it.id != id })
}
