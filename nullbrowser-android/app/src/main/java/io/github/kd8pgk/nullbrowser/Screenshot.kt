package io.github.kd8pgk.nullbrowser

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.pdf.PdfDocument
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.print.PageRange
import android.print.PrintAttributes
import android.print.PrintDocumentAdapter
import android.print.PrintDocumentInfo
import android.view.PixelCopy
import android.webkit.WebView
import java.io.File
import java.io.FileOutputStream

object Screenshot {
    private val main = Handler(Looper.getMainLooper())

    fun page(web: WebView, dest: File, done: (Boolean) -> Unit) {
        val attrs = PrintAttributes.Builder()
            .setMediaSize(PrintAttributes.MediaSize.ISO_A4)
            .setResolution(PrintAttributes.Resolution("nb", "nb", 300, 300))
            .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
            .setColorMode(PrintAttributes.COLOR_MODE_COLOR)
            .build()
        val adapter = web.createPrintDocumentAdapter("Null Browser page")
        val cancel = CancellationSignal()
        adapter.onLayout(null, attrs, cancel, object : PrintDocumentAdapter.LayoutResultCallback() {
            override fun onLayoutFinished(info: PrintDocumentInfo, changed: Boolean) {
                val pfd = try {
                    ParcelFileDescriptor.open(dest, ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_WRITE_ONLY or ParcelFileDescriptor.MODE_TRUNCATE)
                } catch (e: Exception) {
                    finish(done, false)
                    return
                }
                adapter.onWrite(arrayOf(PageRange.ALL_PAGES), pfd, cancel, object : PrintDocumentAdapter.WriteResultCallback() {
                    override fun onWriteFinished(pages: Array<PageRange>) {
                        closeQuietly(pfd)
                        finish(done, true)
                    }

                    override fun onWriteFailed(error: CharSequence?) {
                        closeQuietly(pfd)
                        finish(done, false)
                    }
                })
            }

            override fun onLayoutFailed(error: CharSequence?) {
                finish(done, false)
            }
        }, null)
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

    private fun closeQuietly(pfd: ParcelFileDescriptor) {
        try {
            pfd.close()
        } catch (_: Exception) {
        }
    }
}
