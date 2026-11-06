package io.github.kd8pgk.nodetalker

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.app.usage.UsageStatsManager
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.PowerManager
import android.webkit.CookieManager
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

object ListenLog {
    private const val PREFS = "nodetalker_listenlog"
    private const val KEY_EVENTS = "events"
    private const val KEY_ON = "on"
    private const val KEY_ON_AT = "on_at"
    private const val MAX = 200
    private const val BATCH = 20
    private val busy = AtomicBoolean(false)
    private val lock = Any()

    @Volatile var started = 0

    private fun prefs(c: Context) = c.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun src(s: String?) = if (s == "user") "user" else "system"

    fun why(s: String?, fallback: String) = (s ?: "").filter { it.isLetterOrDigit() || it == '_' }.take(40).ifEmpty { fallback }

    fun add(c: Context, action: String, src: String, why: String, extra: String? = null) {
        val detail = JSONObject()
        try {
            if (!extra.isNullOrEmpty()) {
                val e = JSONObject(extra)
                for (k in e.keys()) detail.put(k, e.get(k))
            }
        } catch (e: JSONException) {
            detail.put("err", "bad detail")
        }
        if (src == "system") phone(c, detail)
        val ev = JSONObject().put("action", action).put("src", src).put("why", why)
            .put("t", System.currentTimeMillis()).put("detail", detail)
        synchronized(lock) {
            val p = prefs(c)
            val arr = try {
                JSONArray(p.getString(KEY_EVENTS, "[]"))
            } catch (e: JSONException) {
                JSONArray()
            }
            val out = JSONArray()
            val from = maxOf(0, arr.length() - (MAX - 1))
            for (i in from until arr.length()) out.put(arr.get(i))
            out.put(ev)
            val ed = p.edit().putString(KEY_EVENTS, out.toString())
            if (action == "connect") ed.putBoolean(KEY_ON, true).putLong(KEY_ON_AT, System.currentTimeMillis())
            else if (action == "disconnect") ed.putBoolean(KEY_ON, false)
            ed.apply()
        }
        flush(c)
    }

    fun talk(c: Context, action: String, reason: String, detail: String) = add(c, action, "system", why(reason, "other"), detail)

    private fun phone(c: Context, d: JSONObject) {
        try {
            val pm = c.getSystemService(Context.POWER_SERVICE) as PowerManager
            d.put("screen", if (pm.isInteractive) 1 else 0)
            d.put("doze", if (pm.isDeviceIdleMode) 1 else 0)
            d.put("psave", if (pm.isPowerSaveMode) 1 else 0)
            d.put("ign", if (pm.isIgnoringBatteryOptimizations(c.packageName)) 1 else 0)
            d.put("fg", if (started > 0) 1 else 0)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val um = c.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
                d.put("bucket", um.appStandbyBucket)
            }
            val cm = c.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val caps = cm.getNetworkCapabilities(cm.activeNetwork)
            d.put(
                "net",
                when {
                    caps == null -> "none"
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cell"
                    else -> "other"
                }
            )
        } catch (e: RuntimeException) {
            d.put("err", "state unreadable")
        }
    }

    fun checkLastExit(c: Context) {
        val p = prefs(c)
        if (!p.getBoolean(KEY_ON, false)) return
        val d = JSONObject()
        var exit = "gone"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                val am = c.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
                val info = am.getHistoricalProcessExitReasons(c.packageName, 0, 1).firstOrNull()
                if (info != null && info.timestamp >= p.getLong(KEY_ON_AT, 0L)) {
                    exit = exitName(info.reason)
                    d.put("imp", info.importance)
                }
            } catch (e: RuntimeException) {
                exit = "unreadable"
            }
        }
        d.put("exit", exit)
        add(c, "disconnect", "system", "process_killed", d.toString())
    }

    private fun exitName(r: Int): String = when (r) {
        ApplicationExitInfo.REASON_EXIT_SELF -> "self"
        ApplicationExitInfo.REASON_SIGNALED -> "signaled"
        ApplicationExitInfo.REASON_LOW_MEMORY -> "low_memory"
        ApplicationExitInfo.REASON_CRASH -> "crash"
        ApplicationExitInfo.REASON_CRASH_NATIVE -> "crash_native"
        ApplicationExitInfo.REASON_ANR -> "anr"
        ApplicationExitInfo.REASON_INITIALIZATION_FAILURE -> "init_failure"
        ApplicationExitInfo.REASON_PERMISSION_CHANGE -> "permission_change"
        ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE -> "excessive_resource_usage"
        ApplicationExitInfo.REASON_USER_REQUESTED -> "user_requested"
        ApplicationExitInfo.REASON_USER_STOPPED -> "user_stopped"
        ApplicationExitInfo.REASON_DEPENDENCY_DIED -> "dependency_died"
        ApplicationExitInfo.REASON_OTHER -> "other"
        else -> "code_$r"
    }

    fun flush(c: Context) {
        if (!busy.compareAndSet(false, true)) return
        val app = c.applicationContext
        Thread({
            try {
                send(app)
            } finally {
                busy.set(false)
            }
        }, "nt-listenlog").apply { isDaemon = true }.start()
    }

    private fun send(c: Context) {
        val node = NodeStore.get(c, NodeStore.lastNode(c)) ?: return
        while (true) {
            val batch = JSONArray()
            synchronized(lock) {
                val arr = try {
                    JSONArray(prefs(c).getString(KEY_EVENTS, "[]"))
                } catch (e: JSONException) {
                    JSONArray()
                }
                for (i in 0 until minOf(arr.length(), BATCH)) batch.put(arr.get(i))
            }
            if (batch.length() == 0) return
            val cookie = try {
                CookieManager.getInstance().getCookie(node.origin)
            } catch (e: RuntimeException) {
                null
            }
            val code = post(node, cookie, JSONObject().put("client", "android").put("events", batch).toString())
            if (code != 200 && code != 404) return
            drop(c, batch.length())
        }
    }

    private fun post(node: Node, cookie: String?, json: String): Int {
        val conn = NodeHttp.open(node, "/api/listen/event", cookie)
        return try {
            val body = json.toByteArray(Charsets.UTF_8)
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("X-Requested-With", "XMLHttpRequest")
            conn.setFixedLengthStreamingMode(body.size)
            conn.outputStream.use { it.write(body) }
            conn.responseCode
        } catch (e: IOException) {
            -1
        } finally {
            conn.disconnect()
        }
    }

    private fun drop(c: Context, n: Int) {
        synchronized(lock) {
            val p = prefs(c)
            val arr = try {
                JSONArray(p.getString(KEY_EVENTS, "[]"))
            } catch (e: JSONException) {
                JSONArray()
            }
            val out = JSONArray()
            for (i in n until arr.length()) out.put(arr.get(i))
            p.edit().putString(KEY_EVENTS, out.toString()).apply()
        }
    }
}
