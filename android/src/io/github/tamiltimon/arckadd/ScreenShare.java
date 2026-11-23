package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.util.DisplayMetrics;
import android.view.WindowManager;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;

/** Shows the phone's screen to the linked PC (view only). Android asks you to allow it every time; frames are
 *  compressed only while the PC is watching, each one encrypted with that session's own key. Stops when you tap
 *  "Stop sharing", when the PC stops, or 30 seconds after the PC stops watching. */
public class ScreenShare extends Service {
    static final String STOP = "io.github.tamiltimon.arckadd.SCREEN_STOP";
    static volatile boolean active;
    static volatile byte[] frame;                 // the newest JPEG
    static volatile long frameNo, lastRequest;
    static volatile byte[] sessionKey;            // fresh for every session
    static volatile String viewer = "your PC";
    static volatile int width, height;

    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader reader;
    private HandlerThread thread;
    private Handler handler;
    private long lastShot;

    /** The PC asked to see the screen: approve on the phone (directly if Arckad-D is open, else via a notification). */
    static void askToShare(Context c, String pcName) {
        viewer = pcName == null || pcName.isEmpty() ? "your PC" : pcName;
        Intent i = new Intent(c, ScreenConsent.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        ChatHub hub = ChatHub.get(c);
        if (hub.onScreen()) {
            try {
                c.startActivity(i);
                return;
            } catch (Exception ignored) {
            }
        }
        PendingIntent pi = PendingIntent.getActivity(c, 5, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        hub.notifyIntent(7404, "🖥 " + viewer + " wants to see your screen", "Tap to allow (view only)", pi);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) {
            stopSharing();
            return START_NOT_STICKY;
        }
        PendingIntent stop = PendingIntent.getService(this, 6, new Intent(this, ScreenShare.class).setAction(STOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, ChatHub.CH_MSG) : new Notification.Builder(this);
        b.setSmallIcon(ChatHub.get(this).statusIcon()).setContentTitle("🖥 Your screen is shown on " + viewer)
                .setContentText("View only · encrypted · local network").setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Stop sharing", stop).build());
        try {
            if (Build.VERSION.SDK_INT >= 29) startForeground(4, b.build(), 32 /* FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION */);
            else startForeground(4, b.build());
        } catch (Exception e) {
            stopSelf();
            return START_NOT_STICKY;
        }
        int code = intent == null ? 0 : intent.getIntExtra("code", 0);
        Intent data = intent == null ? null : intent.getParcelableExtra("data");
        if (code != Activity.RESULT_OK || data == null) {
            stopSharing();
            return START_NOT_STICKY;
        }
        MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        projection = mpm.getMediaProjection(code, data);
        if (projection == null) {
            stopSharing();
            return START_NOT_STICKY;
        }
        thread = new HandlerThread("arckad-screen");
        thread.start();
        handler = new Handler(thread.getLooper());
        projection.registerCallback(new MediaProjection.Callback() {
            @Override
            public void onStop() {
                stopSharing();
            }
        }, handler);
        DisplayMetrics dm = new DisplayMetrics();
        ((WindowManager) getSystemService(Context.WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(dm);
        float scale = Math.min(1f, 1280f / Math.max(dm.widthPixels, dm.heightPixels));
        width = Math.max(2, Math.round(dm.widthPixels * scale) / 2 * 2);
        height = Math.max(2, Math.round(dm.heightPixels * scale) / 2 * 2);
        reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(this::onImage, handler);
        display = projection.createVirtualDisplay("arckad-screen", width, height, dm.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, handler);
        active = true;
        lastRequest = System.currentTimeMillis();
        handler.postDelayed(watchdog, 5000);
        return START_NOT_STICKY;
    }

    private final Runnable watchdog = new Runnable() {
        @Override
        public void run() {
            if (!active) return;
            if (System.currentTimeMillis() - lastRequest > 30_000) stopSharing();    // the PC stopped watching
            else handler.postDelayed(this, 5000);
        }
    };

    private void onImage(ImageReader r) {
        Image img = null;
        try {
            img = r.acquireLatestImage();
            if (img == null) return;
            long now = System.currentTimeMillis();
            if (now - lastRequest > 2000 || now - lastShot < 80) return;   // nobody watching / max ~12 frames a second
            lastShot = now;
            Image.Plane p = img.getPlanes()[0];
            ByteBuffer buf = p.getBuffer();
            int pixel = p.getPixelStride(), row = p.getRowStride();
            Bitmap full = Bitmap.createBitmap(row / pixel, height, Bitmap.Config.ARGB_8888);
            full.copyPixelsFromBuffer(buf);
            Bitmap bmp = full.getWidth() == width ? full : Bitmap.createBitmap(full, 0, 0, width, height);
            ByteArrayOutputStream out = new ByteArrayOutputStream(120_000);
            bmp.compress(Bitmap.CompressFormat.JPEG, 60, out);
            frame = out.toByteArray();
            frameNo++;
        } catch (Exception ignored) {
        } finally {
            if (img != null) img.close();
        }
    }

    private void stopSharing() {
        active = false;
        frame = null;
        sessionKey = null;                                 // the session key is thrown away
        try {
            if (display != null) display.release();
            if (reader != null) reader.close();
            if (projection != null) projection.stop();
        } catch (Exception ignored) {
        }
        display = null;
        reader = null;
        projection = null;
        if (thread != null) thread.quitSafely();
        stopForeground(true);
        stopSelf();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
