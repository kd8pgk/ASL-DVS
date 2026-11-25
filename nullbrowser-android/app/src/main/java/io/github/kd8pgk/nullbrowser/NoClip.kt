package io.github.kd8pgk.nullbrowser

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.util.AttributeSet
import android.view.ActionMode
import android.view.DragEvent
import android.view.KeyEvent
import android.view.Menu
import android.view.MenuItem
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.view.inputmethod.InputConnectionWrapper
import android.webkit.WebView
import android.widget.EditText

object NoClip {
    val MENU_IDS = setOf(
        android.R.id.cut,
        android.R.id.copy,
        android.R.id.paste,
        android.R.id.pasteAsPlainText,
        android.R.id.shareText,
    )

    val JS = """(function(){try{var lock=function(o,n,v){try{Object.defineProperty(o,n,{value:v,writable:false,configurable:false})}catch(e){}};var re=/^(copy|cut|paste)${'$'}/i;var ex=Document.prototype.execCommand;lock(Document.prototype,'execCommand',function execCommand(c){if(re.test(String(c)))return false;return ex.apply(this,arguments)});var q=Document.prototype.queryCommandSupported;lock(Document.prototype,'queryCommandSupported',function queryCommandSupported(c){if(re.test(String(c)))return false;return q.apply(this,arguments)});if(typeof Clipboard==='function'){['read','readText','write','writeText'].forEach(function(m){lock(Clipboard.prototype,m,function(){return Promise.reject(new DOMException('The clipboard is off in Null Browser.','NotAllowedError'))})})}['copy','cut','paste'].forEach(function(t){window.addEventListener(t,function(e){e.preventDefault();e.stopImmediatePropagation()},true)})}catch(e){}})();"""

    fun isClipKey(code: Int, ctrl: Boolean, shift: Boolean): Boolean {
        if (code == KeyEvent.KEYCODE_COPY || code == KeyEvent.KEYCODE_CUT || code == KeyEvent.KEYCODE_PASTE) return true
        if (ctrl && (code == KeyEvent.KEYCODE_C || code == KeyEvent.KEYCODE_X || code == KeyEvent.KEYCODE_V || code == KeyEvent.KEYCODE_INSERT)) return true
        return shift && (code == KeyEvent.KEYCODE_INSERT || code == KeyEvent.KEYCODE_FORWARD_DEL)
    }

    fun isClipKey(event: KeyEvent): Boolean = isClipKey(event.keyCode, event.isCtrlPressed || event.isMetaPressed, event.isShiftPressed)

    fun clear(clipboard: ClipboardManager) {
        if (Build.VERSION.SDK_INT >= 28) clipboard.clearPrimaryClip() else clipboard.setPrimaryClip(ClipData.newPlainText("", ""))
    }
}

object NoMenu : ActionMode.Callback {
    override fun onCreateActionMode(mode: ActionMode, menu: Menu): Boolean = false
    override fun onPrepareActionMode(mode: ActionMode, menu: Menu): Boolean = false
    override fun onActionItemClicked(mode: ActionMode, item: MenuItem): Boolean = false
    override fun onDestroyActionMode(mode: ActionMode) {}
}

class NoClipConnection(target: InputConnection) : InputConnectionWrapper(target, false) {
    override fun performContextMenuAction(id: Int): Boolean = if (id in NoClip.MENU_IDS) true else super.performContextMenuAction(id)
    override fun commitContent(inputContentInfo: android.view.inputmethod.InputContentInfo, flags: Int, opts: android.os.Bundle?): Boolean = false
}

class NoClipEditText(context: Context, attrs: AttributeSet?) : EditText(context, attrs) {
    init {
        isLongClickable = false
        customSelectionActionModeCallback = NoMenu
        customInsertionActionModeCallback = NoMenu
    }

    override fun onTextContextMenuItem(id: Int): Boolean = if (id in NoClip.MENU_IDS) true else super.onTextContextMenuItem(id)

    override fun dispatchKeyEvent(event: KeyEvent): Boolean = if (NoClip.isClipKey(event)) true else super.dispatchKeyEvent(event)

    override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection? = super.onCreateInputConnection(outAttrs)?.let { NoClipConnection(it) }

    override fun onDragEvent(event: DragEvent): Boolean = false
}

class NoClipWebView(context: Context, attrs: AttributeSet?) : WebView(context, attrs) {
    override fun startActionMode(callback: ActionMode.Callback?): ActionMode? = null

    override fun startActionMode(callback: ActionMode.Callback?, type: Int): ActionMode? = null

    override fun dispatchKeyEvent(event: KeyEvent): Boolean = if (NoClip.isClipKey(event)) true else super.dispatchKeyEvent(event)

    override fun onCreateInputConnection(outAttrs: EditorInfo): InputConnection? = super.onCreateInputConnection(outAttrs)?.let { NoClipConnection(it) }

    override fun onDragEvent(event: DragEvent): Boolean = false
}
