package io.github.tamiltimon.arckadd;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;

/** Lets other apps read a file we hand them ("Open with", "Share"), using content:// links. */
public class Provider extends ContentProvider {
    static final String AUTHORITY = "io.github.tamiltimon.arckadd.files";

    static Uri uriFor(File f) {
        return new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath("f")
                .appendPath(f.getAbsolutePath()).build();
    }

    private static File fileOf(Uri uri) throws FileNotFoundException {
        if (uri.getPathSegments().size() < 2) throw new FileNotFoundException(String.valueOf(uri));
        File f = new File(uri.getPathSegments().get(1));
        if (!f.isFile()) throw new FileNotFoundException(f.getPath());
        return f;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sort) {
        File f;
        try {
            f = fileOf(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        String[] cols = projection != null ? projection : new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor c = new MatrixCursor(cols, 1);
        Object[] row = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) row[i] = f.getName();
            else if (OpenableColumns.SIZE.equals(cols[i])) row[i] = f.length();
        }
        c.addRow(row);
        return c;
    }

    @Override
    public String getType(Uri uri) {
        try {
            return Fs.mime(fileOf(uri).getName());
        } catch (FileNotFoundException e) {
            return null;
        }
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (mode != null && mode.contains("w")) {                   // 📷 only the camera, only into our scan folder
            if (uri.getPathSegments().size() < 2) throw new FileNotFoundException(String.valueOf(uri));
            File f = new File(uri.getPathSegments().get(1));
            File scan = new File(getContext().getCacheDir(), "scan");
            try {
                if (!f.getCanonicalPath().startsWith(scan.getCanonicalPath() + File.separator))
                    throw new FileNotFoundException("not writable");
            } catch (java.io.IOException e) {
                throw new FileNotFoundException("not writable");
            }
            return ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_WRITE_ONLY | ParcelFileDescriptor.MODE_CREATE
                    | ParcelFileDescriptor.MODE_TRUNCATE);
        }
        return ParcelFileDescriptor.open(fileOf(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        return null;
    }

    @Override
    public int delete(Uri uri, String s, String[] a) {
        return 0;
    }

    @Override
    public int update(Uri uri, ContentValues v, String s, String[] a) {
        return 0;
    }
}
