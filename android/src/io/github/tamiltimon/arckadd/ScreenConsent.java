package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;

/** A see-through screen that shows Android's own "Start recording or casting?" question, then starts sharing. */
public class ScreenConsent extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        startActivityForResult(mpm.createScreenCaptureIntent(), 7405);
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        if (req == 7405 && result == RESULT_OK && data != null) {
            Intent i = new Intent(this, ScreenShare.class).putExtra("code", result).putExtra("data", data);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i);
            else startService(i);
        } else {
            ScreenShare.sessionKey = null;                 // declined: no session
        }
        finish();
    }
}
