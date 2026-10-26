package io.github.kd8pgk.nodetalker

import org.json.JSONException
import org.json.JSONObject
import org.json.JSONTokener

data class PageSettings(
    val ptt: PttSettings = PttSettings(),
    val micGainDb: Double = 0.0,
    val spectrum: Boolean = true,
    val auto: Boolean = true,
    val textPx: Double = DEFAULT_TEXT,
    val pttHeightDp: Double = DEFAULT_HEIGHT,
) {
    companion object {
        const val DEFAULT_TEXT = 15.0
        const val DEFAULT_HEIGHT = 64.0

        const val READ_JS = "(function(){try{var s=null;try{s=JSON.parse(localStorage.getItem('nlListenSize')||'null')}catch(e){}" +
            "return JSON.stringify({ptt:ptt,play:play,mic:Number(mic&&mic.gain)||0,size:s})}catch(e){return null}})()"

        fun parse(raw: String?): PageSettings {
            if (raw.isNullOrEmpty() || raw == "null") return PageSettings()
            return try {
                val text = JSONTokener(raw).nextValue() as? String ?: return PageSettings()
                val o = JSONObject(text)
                val p = o.optJSONObject("ptt")
                val mode = p?.optString("mode") ?: "hold"
                val guard = p?.optInt("guard", 60) ?: 60
                val play = o.optJSONObject("play")
                val size = o.optJSONObject("size")
                PageSettings(
                    ptt = PttSettings(
                        if (mode == "tap") "tap" else "hold",
                        if (guard in PttSettings.GUARDS) guard else 60,
                        p?.optBoolean("gap", true) ?: true,
                    ),
                    micGainDb = o.optDouble("mic", 0.0),
                    spectrum = play?.optBoolean("spec", true) ?: true,
                    auto = play?.optBoolean("auto", true) ?: true,
                    textPx = size?.optDouble("font", DEFAULT_TEXT)?.takeIf { it in 10.0..20.0 } ?: DEFAULT_TEXT,
                    pttHeightDp = size?.optDouble("h", DEFAULT_HEIGHT)?.takeIf { it in 48.0..96.0 } ?: DEFAULT_HEIGHT,
                )
            } catch (e: JSONException) {
                PageSettings()
            }
        }
    }
}
