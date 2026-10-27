package io.github.kd8pgk.nodetalker

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.InputFilter
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ListView
import android.widget.RadioButton
import android.widget.SeekBar
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
        findViewById<Button>(R.id.callsign).setOnClickListener { callsignSettings() }
        findViewById<Button>(R.id.audio).setOnClickListener { audioSettings() }
        findViewById<Button>(R.id.battery).setOnClickListener { batterySettings() }
        val keep = findViewById<CheckBox>(R.id.keep_on)
        keep.isChecked = NodeStore.keepScreenOn(this)
        keep.setOnCheckedChangeListener { _, on -> NodeStore.setKeepScreenOn(this, on) }
        findViewById<TextView>(R.id.version).text = getString(R.string.app_version, BuildConfig.VERSION_NAME)
        findViewById<TextView>(R.id.license).apply {
            paintFlags = paintFlags or android.graphics.Paint.UNDERLINE_TEXT_FLAG
            setOnClickListener { openLicense() }
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun openLicense() {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(getString(R.string.license_url))))
        } catch (e: android.content.ActivityNotFoundException) {
            Toast.makeText(this, getString(R.string.license_url), Toast.LENGTH_LONG).show()
        }
    }

    private fun batteryFree() = (getSystemService(POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(packageName)

    private fun batterySettings() {
        val tries = listOf(
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, android.net.Uri.parse("package:$packageName")),
        )
        for (i in tries) {
            try {
                startActivity(i)
                return
            } catch (e: android.content.ActivityNotFoundException) {
                continue
            }
        }
    }

    private fun refresh() {
        val free = batteryFree()
        findViewById<TextView>(R.id.battery_text).text = getString(if (free) R.string.battery_ok else R.string.battery_warn)
        findViewById<TextView>(R.id.battery_text).setTextColor(getColor(if (free) R.color.muted else R.color.amber))
        findViewById<Button>(R.id.callsign).text = getString(
            R.string.callsign_button,
            NodeStore.callsign(this).ifEmpty { getString(R.string.callsign_none) },
        )
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

    private fun callsignSettings() {
        val field = EditText(this).apply {
            setText(NodeStore.callsign(this@NodesActivity))
            hint = getString(R.string.callsign_hint)
            filters = arrayOf(
                InputFilter.AllCaps(),
                InputFilter.LengthFilter(16),
                InputFilter { src, start, end, _, _, _ ->
                    if (src.subSequence(start, end).all { it.isLetterOrDigit() || it == '/' || it == '-' }) null else ""
                },
            )
        }
        AlertDialog.Builder(this)
            .setTitle(R.string.callsign_title)
            .setMessage(R.string.callsign_help)
            .setView(field)
            .setPositiveButton(R.string.save) { _, _ ->
                NodeStore.setCallsign(this, field.text.toString().trim())
                refresh()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun audioSettings() {
        val a = NodeStore.audio(this)
        val v = LayoutInflater.from(this).inflate(R.layout.dialog_audio, null)
        val app = v.findViewById<RadioButton>(R.id.mode_app)
        val page = v.findViewById<RadioButton>(R.id.mode_page)
        val buf = v.findViewById<SeekBar>(R.id.buffer)
        val bufText = v.findViewById<TextView>(R.id.buffer_text)
        val speaker = v.findViewById<RadioButton>(R.id.out_speaker)
        val ear = v.findViewById<RadioButton>(R.id.out_earpiece)
        val voice = v.findViewById<CheckBox>(R.id.voice_mic)
        voice.isChecked = a.voiceMic
        app.isChecked = a.app
        page.isChecked = !a.app
        speaker.isChecked = !a.earpiece
        ear.isChecked = a.earpiece
        val step = 50
        buf.max = (AudioSettings.MAX_BUFFER - AudioSettings.MIN_BUFFER) / step
        buf.progress = (a.bufferMs - AudioSettings.MIN_BUFFER) / step
        val ms = { AudioSettings.MIN_BUFFER + buf.progress * step }
        bufText.text = getString(R.string.rx_buffer, ms())
        buf.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar, p: Int, user: Boolean) {
                bufText.text = getString(R.string.rx_buffer, ms())
            }

            override fun onStartTrackingTouch(sb: SeekBar) = Unit
            override fun onStopTrackingTouch(sb: SeekBar) = Unit
        })
        AlertDialog.Builder(this)
            .setTitle(R.string.audio_settings)
            .setView(v)
            .setPositiveButton(R.string.save) { _, _ ->
                val b = AudioSettings(if (app.isChecked) AudioSettings.APP else AudioSettings.PAGE, ms(), ear.isChecked, voice.isChecked)
                NodeStore.setAudio(this, b)
                if (!b.app) Listen.stop(this)
                else Listen.nodeId?.let { id -> NodeStore.get(this, id)?.let { Listen.start(this, it) } }
                Toast.makeText(this, R.string.audio_saved, Toast.LENGTH_LONG).show()
            }
            .setNegativeButton(R.string.cancel, null)
            .show()
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
