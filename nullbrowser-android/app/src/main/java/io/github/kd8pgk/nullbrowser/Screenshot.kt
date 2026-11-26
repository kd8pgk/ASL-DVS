package io.github.kd8pgk.nullbrowser

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.pdf.PdfDocument
import android.os.Handler
import android.os.Looper
import android.view.PixelCopy
import android.view.ViewGroup
import android.webkit.WebView
import java.io.File
import java.io.FileOutputStream
import kotlin.math.roundToInt

object Screenshot {
    private val main = Handler(Looper.getMainLooper())
    private const val MAX_PAGE_PX = 14000
    private const val LAYOUT_WAIT_MS = 400L

    fun page(web: WebView, dest: File, done: (Boolean) -> Unit) {
        val width = web.width
        if (width <= 0) {
            finish(done, false)
            return
        }
        val saved = web.layoutParams
        val screenHeight = web.height
        val wanted = (web.contentHeight * web.scale).roundToInt().coerceIn(screenHeight, MAX_PAGE_PX)
        web.layoutParams = ViewGroup.LayoutParams(width, wanted)
        web.requestLayout()
        main.postDelayed({
            val ok = try {
                val doc = PdfDocument()
                try {
                    val page = doc.startPage(PdfDocument.PageInfo.Builder(width, wanted, 1).create())
                    web.draw(page.canvas)
                    doc.finishPage(page)
                    FileOutputStream(dest).use { doc.writeTo(it) }
                    true
                } finally {
                    doc.close()
                }
            } catch (e: Exception) {
                false
            }
            web.layoutParams = saved
            web.requestLayout()
            finish(done, ok)
        }, LAYOUT_WAIT_MS)
    }

    fun window(activity: Activity, dest: File, done: (Boolean) -> Unit) {
        val view = activity.window.decorView
        val w = view.width
        val h = view.height
        if (w <= 0 || h <= 0) {
            finish(done, false)
            return
        }
        val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        PixelCopy.request(activity.window, bitmap, { result ->
            val ok = result == PixelCopy.SUCCESS && bitmapPdf(bitmap, dest)
            bitmap.recycle()
            finish(done, ok)
        }, main)
    }

    private fun bitmapPdf(bitmap: Bitmap, dest: File): Boolean {
        val doc = PdfDocument()
        return try {
            val info = PdfDocument.PageInfo.Builder(bitmap.width, bitmap.height, 1).create()
            val page = doc.startPage(info)
            page.canvas.drawBitmap(bitmap, 0f, 0f, null)
            doc.finishPage(page)
            FileOutputStream(dest).use { doc.writeTo(it) }
            true
        } catch (e: Exception) {
            false
        } finally {
            doc.close()
        }
    }

    private fun finish(done: (Boolean) -> Unit, ok: Boolean) {
        main.post { done(ok) }
    }
}
