package io.github.kd8pgk.nullbrowser

object LessInfo {
    private val PLATFORM = Regex("^Mozilla/5\\.0 \\(([^)]*)\\)")
    private val CHROME = Regex("\\bChrome/(\\d+)[0-9.]*")
    private val ANDROID = Regex("^Android [0-9.]+$")

    fun userAgent(default: String): String {
        val platform = PLATFORM.find(default)?.groupValues?.get(1) ?: return default
        val major = CHROME.find(default)?.groupValues?.get(1) ?: return default
        val parts = platform.split(';').map { it.trim() }
        val kept = parts.filter { it == "Linux" || ANDROID.matches(it) || it == "wv" }
        if (kept.none { ANDROID.matches(it) }) return default
        val mobile = if (default.contains(" Mobile ")) " Mobile" else ""
        val webview = if (default.contains("Version/4.0")) " Version/4.0" else ""
        return "Mozilla/5.0 (${kept.joinToString("; ")}) AppleWebKit/537.36 (KHTML, like Gecko)$webview Chrome/$major.0.0.0$mobile Safari/537.36"
    }

    const val JS = """(function(){try{var d=function(p,n){try{if(p&&Object.prototype.hasOwnProperty.call(p,n))delete p[n]}catch(e){}};d(Navigator.prototype,'connection');d(Navigator.prototype,'deviceMemory');d(Navigator.prototype,'hardwareConcurrency');d(Navigator.prototype,'getBattery');if(typeof NavigatorUAData==='function'){var low=NavigatorUAData.prototype.toJSON;try{Object.defineProperty(NavigatorUAData.prototype,'getHighEntropyValues',{value:function getHighEntropyValues(){var b=typeof low==='function'?low.call(this):{};return Promise.resolve({brands:b.brands,mobile:b.mobile,platform:b.platform})},writable:false,configurable:false})}catch(e){}}}catch(e){}})();"""
}
