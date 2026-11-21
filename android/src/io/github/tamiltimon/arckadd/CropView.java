package io.github.tamiltimon.arckadd;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

/** Profile photo cropper: drag to move, pinch to zoom, rotate; the circle shows what others will see. */
final class CropView extends View {
    private Bitmap bmp;
    private float scale = 1, minScale = 1, tx, ty, lastX, lastY;
    private final ScaleGestureDetector pinch;
    private final Paint shade = new Paint(Paint.ANTI_ALIAS_FLAG), ring = new Paint(Paint.ANTI_ALIAS_FLAG);

    CropView(Context c, Bitmap b) {
        super(c);
        bmp = b;
        shade.setColor(0x99000000);
        ring.setColor(Color.WHITE);
        ring.setStyle(Paint.Style.STROKE);
        ring.setStrokeWidth(Ui.dp(c, 2));
        pinch = new ScaleGestureDetector(c, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override
            public boolean onScale(ScaleGestureDetector d) {
                float s = Math.max(minScale, Math.min(minScale * 6, scale * d.getScaleFactor()));
                float f = s / scale, cx = d.getFocusX(), cy = d.getFocusY();
                tx = cx - (cx - tx) * f;
                ty = cy - (cy - ty) * f;
                scale = s;
                clamp();
                invalidate();
                return true;
            }
        });
    }

    private float side() {
        return Math.min(getWidth(), getHeight()) * 0.86f;
    }

    private RectF frame() {
        float s = side(), l = (getWidth() - s) / 2, t = (getHeight() - s) / 2;
        return new RectF(l, t, l + s, t + s);
    }

    void rotate() {
        Matrix m = new Matrix();
        m.postRotate(90);
        bmp = Bitmap.createBitmap(bmp, 0, 0, bmp.getWidth(), bmp.getHeight(), m, true);
        fit();
        invalidate();
    }

    private void fit() {
        if (getWidth() == 0) return;
        float s = side();
        minScale = scale = s / Math.min(bmp.getWidth(), bmp.getHeight());
        tx = (getWidth() - bmp.getWidth() * scale) / 2;
        ty = (getHeight() - bmp.getHeight() * scale) / 2;
    }

    private void clamp() {                               // keep the circle covered by the photo
        RectF f = frame();
        tx = Math.min(f.left, Math.max(f.right - bmp.getWidth() * scale, tx));
        ty = Math.min(f.top, Math.max(f.bottom - bmp.getHeight() * scale, ty));
    }

    @Override
    protected void onSizeChanged(int w, int h, int ow, int oh) {
        fit();
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        pinch.onTouchEvent(e);
        if (e.getPointerCount() == 1 && !pinch.isInProgress()) {
            if (e.getActionMasked() == MotionEvent.ACTION_DOWN) {
                lastX = e.getX();
                lastY = e.getY();
            } else if (e.getActionMasked() == MotionEvent.ACTION_MOVE) {
                tx += e.getX() - lastX;
                ty += e.getY() - lastY;
                lastX = e.getX();
                lastY = e.getY();
                clamp();
                invalidate();
            }
        } else {
            lastX = e.getX();
            lastY = e.getY();
        }
        return true;
    }

    @Override
    protected void onDraw(Canvas c) {
        c.save();
        c.translate(tx, ty);
        c.scale(scale, scale);
        c.drawBitmap(bmp, 0, 0, null);
        c.restore();
        RectF f = frame();
        Path p = new Path();
        p.addRect(0, 0, getWidth(), getHeight(), Path.Direction.CW);
        p.addCircle(f.centerX(), f.centerY(), f.width() / 2, Path.Direction.CCW);
        c.drawPath(p, shade);
        c.drawCircle(f.centerX(), f.centerY(), f.width() / 2, ring);
    }

    /** The square inside the circle, as a size x size picture. */
    Bitmap result(int size) {
        RectF f = frame();
        int x = Math.max(0, (int) ((f.left - tx) / scale)), y = Math.max(0, (int) ((f.top - ty) / scale));
        int s = Math.max(8, (int) (f.width() / scale));
        s = Math.min(s, Math.min(bmp.getWidth() - x, bmp.getHeight() - y));
        return Bitmap.createScaledBitmap(Bitmap.createBitmap(bmp, x, y, s, s), size, size, true);
    }
}
