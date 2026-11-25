package io.github.kd8pgk.nullbrowser

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import java.io.File

fun downloadsDir(cacheDir: File): File {
    val dir = File(cacheDir, "downloads")
    dir.mkdirs()
    return dir
}

class DownloadProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    private fun fileFor(uri: Uri): File {
        val name = uri.lastPathSegment ?: throw SecurityException("no file name")
        val dir = downloadsDir(context!!.cacheDir)
        val file = File(dir, name)
        if (file.canonicalFile.parentFile != dir.canonicalFile) throw SecurityException("bad path")
        return file
    }

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        return ParcelFileDescriptor.open(fileFor(uri), ParcelFileDescriptor.MODE_READ_ONLY)
    }

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val file = fileFor(uri)
        val cursor = MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE))
        cursor.addRow(arrayOf(file.name, file.length()))
        return cursor
    }

    override fun getType(uri: Uri): String? {
        val ext = fileFor(uri).extension.lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext)
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
