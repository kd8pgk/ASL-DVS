package io.github.kd8pgk.nodetalker

import android.content.Context
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class SpectrumView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val d = resources.displayMetrics.density
    private val bins = ByteArray(Spectrum.BINS)
    private var spectrum: Spectrum? = null
    private val fill = Paint()
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Typeface.MONOSPACE }
    private val clip = Path()
    private val box = RectF()
    private val border = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = d
        color = context.getColor(R.color.line)
    }
    private val dash = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = d
        color = Color.argb(115, 244, 192, 78)
        pathEffect = DashPathEffect(floatArrayOf(3 * d, 3 * d), 0f)
    }

    private var meterShader: Shader? = null

    var running = false
    var gapDigit = ""

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        meterShader = LinearGradient(
            0f, 0f, 0f, h.toFloat(),
            intArrayOf(Color.parseColor("#ff5c5c"), context.getColor(R.color.amber), context.getColor(R.color.accent), Color.parseColor("#123460")),
            floatArrayOf(0f, 0.1f, 0.5f, 1f), Shader.TileMode.CLAMP,
        )
    }

    fun bind(s: Spectrum) {
        spectrum = s
    }

    fun tick(nowMs: Long) {
        spectrum?.update(nowMs, bins)
        invalidate()
    }

    override fun onDraw(c: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        box.set(0f, 0f, w, h)
        clip.reset()
        clip.addRoundRect(box, 8 * d, 8 * d, Path.Direction.CW)
        c.save()
        c.clipPath(clip)
        fill.shader = null
        fill.color = context.getColor(R.color.spec_bg)
        c.drawRect(box, fill)
        val s = spectrum
        if (running && s != null) drawLive(c, s, w, h)
        drawOverlays(c, w, h)
        c.restore()
        box.inset(d / 2, d / 2)
        c.drawRoundRect(box, 8 * d, 8 * d, border)
    }

    private fun drawLive(c: Canvas, s: Spectrum, w: Float, h: Float) {
        val bx = 40 * d
        val bw = w - bx - 52 * d
        val yDb = { db: Double -> (h - (db - Spectrum.DB_LO) / (Spectrum.DB_HI - Spectrum.DB_LO) * h).toFloat() }
        text.textSize = 9 * d
        text.textAlign = Paint.Align.RIGHT
        for (db in -100..-40 step 10) {
            fill.color = context.getColor(R.color.line)
            val y = yDb(db.toDouble()).roundToInt().toFloat()
            c.drawRect(bx, y, bx + bw, y + max(1f, d), fill)
            text.color = context.getColor(R.color.muted)
            c.drawText(db.toString(), bx - 4 * d, y - (text.ascent() + text.descent()) / 2, text)
        }
        c.drawText("dB", bx - 4 * d, 2 * d - text.ascent(), text)
        val step = max(2f, floor(bw / 96f))
        var x = bx
        while (x < bx + bw) {
            val i = min(Spectrum.BINS - 1, floor((x - bx) / bw * Spectrum.BINS).toInt())
            val v = bins[i].toInt() and 0xFF
            fill.color = Spectrum.PALETTE[v]
            c.drawRect(x, h - v / 255f * h, x + step - 1, h, fill)
            x += step
        }
        val mx = w - 52 * d + 10 * d
        val mw = 16 * d
        val yF = { db: Double -> ((0 - db) / 60 * h).toFloat() }
        fill.color = context.getColor(R.color.spec_bg)
        c.drawRect(mx, 0f, mx + mw, h, fill)
        fill.shader = meterShader
        c.drawRect(mx, yF(s.level), mx + mw, h, fill)
        fill.shader = null
        fill.color = context.getColor(R.color.amber)
        val hy = yF(s.hold).roundToInt().toFloat()
        c.drawRect(mx - 3 * d, hy, mx + mw + 3 * d, hy + max(2f, 2 * d), fill)
        fill.color = context.getColor(R.color.red_line)
        val cy = max(0f, yF(-0.5).roundToInt() - d)
        c.drawRect(mx - 4 * d, cy, mx + mw + 4 * d, cy + 2 * d, fill)
        text.textAlign = Paint.Align.LEFT
        text.color = context.getColor(R.color.muted)
        for (db in intArrayOf(0, -6, -12, -18, -24, -36, -48, -60)) {
            val y = max(6 * d, min(h - 6 * d, yF(db.toDouble())))
            c.drawText(db.toString(), mx + mw + 4 * d, y - text.ascent(), text)
        }
    }

    private fun drawOverlays(c: Canvas, w: Float, h: Float) {
        fill.shader = null
        fill.color = Color.argb(26, 244, 192, 78)
        c.drawRect(0f, 0f, w * 0.075f, h, fill)
        c.drawLine(w * 0.075f - d / 2, 0f, w * 0.075f - d / 2, h, dash)
        text.textSize = 10 * d
        text.textAlign = Paint.Align.CENTER
        text.color = context.getColor(R.color.muted)
        for ((label, at) in listOf("300" to 0.075f, "1k" to 0.25f, "2k" to 0.5f, "3k" to 0.75f)) {
            c.drawText(label, w * at, h - 2 * d - text.descent(), text)
        }
        if (gapDigit.isNotEmpty()) {
            text.typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
            text.textSize = max(14f * d, min(h * 0.5f * 0.8f, w * 0.25f / 0.6f * 0.8f))
            text.color = Color.argb(64, 255, 255, 255)
            val cx = w * 0.875f
            val cy = h * 0.25f
            c.drawText(gapDigit, cx, cy - (text.ascent() + text.descent()) / 2, text)
            text.typeface = Typeface.MONOSPACE
        }
    }
}

class MeterView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val d = resources.displayMetrics.density
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()
    private val clip = Path()
    private val matrix = Matrix()
    private val normal = LinearGradient(
        0f, 0f, 1f, 0f,
        intArrayOf(context.getColor(R.color.accent), context.getColor(R.color.accent), Color.parseColor("#e3a008"), Color.parseColor("#f2545b")),
        floatArrayOf(0f, 0.7f, 0.9f, 1f), Shader.TileMode.CLAMP,
    )
    private val sending = LinearGradient(
        0f, 0f, 1f, 0f,
        intArrayOf(Color.parseColor("#f2545b"), Color.parseColor("#f2545b"), Color.parseColor("#ffb3b6")),
        floatArrayOf(0f, 0.85f, 1f), Shader.TileMode.CLAMP,
    )

    var percent = 0.0
        set(v) {
            field = v.coerceIn(0.0, 100.0)
            invalidate()
        }

    var transmitting = false
        set(v) {
            field = v
            invalidate()
        }

    override fun onDraw(c: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        rect.set(0f, 0f, w, h)
        clip.reset()
        clip.addRoundRect(rect, 6 * d, 6 * d, Path.Direction.CW)
        c.save()
        c.clipPath(clip)
        paint.shader = null
        paint.color = context.getColor(R.color.meter_bg)
        c.drawRect(rect, paint)
        val fw = (w * percent / 100).toFloat()
        if (fw > 0) {
            val shader = if (transmitting) sending else normal
            matrix.setScale(fw, 1f)
            shader.setLocalMatrix(matrix)
            paint.shader = shader
            c.drawRect(0f, 0f, fw, h, paint)
        }
        c.restore()
    }
}

class DotView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private val d = resources.displayMetrics.density
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG).apply { maskFilter = BlurMaskFilter(4 * d, BlurMaskFilter.Blur.NORMAL) }

    var level = ListenStatus.DOT_OFF
        set(v) {
            if (field == v) return
            field = v
            invalidate()
        }

    init {
        setLayerType(LAYER_TYPE_SOFTWARE, null)
    }

    override fun onDraw(c: Canvas) {
        val color = when (level) {
            ListenStatus.DOT_ON -> context.getColor(R.color.accent)
            ListenStatus.DOT_RX -> context.getColor(R.color.amber)
            ListenStatus.DOT_TX, ListenStatus.DOT_ERR -> context.getColor(R.color.red_line)
            ListenStatus.DOT_WARN -> Color.parseColor("#e3a008")
            else -> context.getColor(R.color.dot_off)
        }
        val cx = width / 2f
        val cy = height / 2f
        if (level == ListenStatus.DOT_ON || level == ListenStatus.DOT_RX || level == ListenStatus.DOT_TX) {
            glow.color = color
            c.drawCircle(cx, cy, 5.5f * d, glow)
        }
        paint.color = color
        c.drawCircle(cx, cy, 5.5f * d, paint)
    }
}
