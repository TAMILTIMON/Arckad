package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.util.Base64;
import android.view.GestureDetector;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** 🖥 The PC on the phone: its whole screen, full screen, controlled by touch — or 🎛 the phone as a remote for
 *  slides, music and volume. Over the encrypted link to the linked PC, same Wi-Fi only; the PC asks first. */
public class PcActivity extends Activity {
    static void open(Context c, String mode) {
        c.startActivity(new Intent(c, PcActivity.class).putExtra("mode", mode));
    }

    private ChatLink link;
    private String inst;
    private volatile boolean running = true;
    private final List<JSONObject> queue = new ArrayList<>();
    private ScreenView view;
    private TextView status;
    private LinearLayout bar;
    private EditText keys;
    private boolean remote;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        remote = "remote".equals(getIntent().getStringExtra("mode"));
        link = ChatHub.get(this).engine.link;
        inst = ToPc.pc(link);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        setContentView(root);
        status = new TextView(this);
        status.setTextColor(Color.WHITE);
        status.setTextSize(16);
        status.setGravity(Gravity.CENTER);
        status.setPadding(40, 40, 40, 40);
        if (inst == null) {
            status.setText("Your PC needs to be on, running Arckad-D, on the same Wi-Fi, and linked to this phone.");
            root.addView(status);
            return;
        }
        if (remote) {
            buildRemote(root);
        } else {
            immersive();
            view = new ScreenView(this);
            root.addView(view);
            buildBar(root);
            keys = hiddenKeyboard();
            root.addView(keys, new FrameLayout.LayoutParams(1, 1));
            status.setText("Connecting to your PC…");
            root.addView(status, new FrameLayout.LayoutParams(-1, -1));
            new Thread(this::screenLoop).start();
            new Thread(this::sendLoop).start();
        }
    }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    @Override
    public void onWindowFocusChanged(boolean f) {
        super.onWindowFocusChanged(f);
        if (f && !remote) immersive();
    }

    private void say(String s) {
        runOnUiThread(() -> {
            status.setText(s);
            status.setVisibility(s == null ? View.GONE : View.VISIBLE);
        });
    }

    /** Asks the PC (it shows “Allow?” the first time), then keeps fetching the screen. */
    private void screenLoop() {
        try {
            while (running) {
                JSONObject r = link.call(inst, "/t/pc/start", new Obj().putOpt("screen", true), 30_000);
                if (r.optBoolean("ok")) break;
                say(r.optString("reason", "The PC said no"));
                if (!r.optBoolean("asking")) return;
                Thread.sleep(1500);
            }
            say(null);
            int maxw = Math.max(getResources().getDisplayMetrics().widthPixels, getResources().getDisplayMetrics().heightPixels);
            while (running) {
                long t0 = System.currentTimeMillis();
                JSONObject r = link.call(inst, "/t/pc/frame", new Obj().putOpt("maxw", maxw), 15_000);
                if (!r.optBoolean("ok")) {
                    say(r.optString("reason", "Disconnected"));
                    return;
                }
                byte[] jpg = Base64.decode(r.optString("jpg"), Base64.DEFAULT);
                Bitmap bm = BitmapFactory.decodeByteArray(jpg, 0, jpg.length);
                if (bm != null) view.setFrame(bm);
                long left = 70 - (System.currentTimeMillis() - t0);
                if (left > 0) Thread.sleep(left);
            }
        } catch (Exception ex) {
            if (running) say("Lost the connection to the PC: " + ex.getMessage());
        }
    }

    private void send(JSONObject e) {
        synchronized (queue) {
            if ("move".equals(e.optString("t")) && !queue.isEmpty()
                    && "move".equals(queue.get(queue.size() - 1).optString("t")))
                queue.set(queue.size() - 1, e);                 // only the latest position matters
            else queue.add(e);
            queue.notifyAll();
        }
    }

    private void sendLoop() {
        while (running) {
            JSONArray batch = new JSONArray();
            synchronized (queue) {
                while (queue.isEmpty() && running) {
                    try {
                        queue.wait(500);
                    } catch (InterruptedException ignored) {
                    }
                }
                for (JSONObject e : queue) batch.put(e);
                queue.clear();
            }
            if (batch.length() == 0) continue;
            try {
                link.call(inst, "/t/pc/input", new Obj().putOpt("events", batch), 8000);
            } catch (Exception ignored) {
            }
        }
    }

    private static JSONObject ev(String t, float[] xy) {
        Obj o = new Obj();
        o.putOpt("t", t);
        if (xy != null) {
            o.putOpt("x", xy[0]);
            o.putOpt("y", xy[1]);
        }
        return o;
    }

    private void key(String name, String... mods) {
        Obj o = new Obj();
        o.putOpt("t", "key").putOpt("k", name);
        if (mods.length > 0) o.putOpt("mods", new JSONArray(java.util.Arrays.asList(mods)));
        send(o);
    }

    // ---------- the toolbar (hides itself; touch the top edge to bring it back)
    private void buildBar(FrameLayout root) {
        HorizontalScrollView hs = new HorizontalScrollView(this);
        bar = new LinearLayout(this);
        bar.setBackgroundColor(0xcc202024);
        bar.setPadding(8, 8, 8, 8);
        hs.addView(bar);
        Object[][] btns = {{"⌨", (Runnable) this::showKeyboard}, {"Esc", (Runnable) () -> key("Escape")},
                {"Tab", (Runnable) () -> key("Tab")}, {"⊞", (Runnable) () -> key("Super_L")},
                {"Copy", (Runnable) () -> key("c", "Control_L")}, {"Paste", (Runnable) () -> key("v", "Control_L")},
                {"↶ Undo", (Runnable) () -> key("z", "Control_L")}, {"Alt+Tab", (Runnable) () -> key("Tab", "Alt_L")},
                {"🔍 1:1", (Runnable) () -> view.resetZoom()}, {"🎛 Remote", (Runnable) () -> open(this, "remote")},
                {"✕", (Runnable) this::finish}};
        for (Object[] bt : btns) {
            Button b = new Button(this);
            b.setText((String) bt[0]);
            b.setAllCaps(false);
            final Runnable r = (Runnable) bt[1];
            b.setOnClickListener(v -> {
                r.run();
                hideBarSoon();
            });
            bar.addView(b);
        }
        root.addView(hs, new FrameLayout.LayoutParams(-1, -2, Gravity.TOP));
        hideBarSoon();
    }

    private final Runnable hideBar = () -> {
        if (bar != null) ((View) bar.getParent()).setVisibility(View.GONE);
    };

    private void hideBarSoon() {
        if (bar == null) return;
        ((View) bar.getParent()).setVisibility(View.VISIBLE);
        bar.removeCallbacks(hideBar);
        bar.postDelayed(hideBar, 4000);
    }

    // ---------- typing: a hidden text box keeps a small cushion so Backspace always reaches us
    private static final String CUSHION = "      ";

    private EditText hiddenKeyboard() {
        EditText e = new EditText(this);
        e.setAlpha(0f);
        e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        e.setImeOptions(EditorInfo.IME_FLAG_NO_EXTRACT_UI | EditorInfo.IME_ACTION_NONE);
        e.setText(CUSHION);
        e.setSelection(CUSHION.length());
        e.addTextChangedListener(new TextWatcher() {
            boolean busy;

            public void beforeTextChanged(CharSequence s, int a, int b, int c) {
            }

            public void onTextChanged(CharSequence s, int a, int b, int c) {
            }

            public void afterTextChanged(Editable s) {
                if (busy) return;
                String t = s.toString();
                if (t.length() < CUSHION.length()) {
                    for (int i = 0; i < CUSHION.length() - t.length(); i++) key("BackSpace");
                } else if (t.length() > CUSHION.length()) {
                    send(new Obj().putOpt("t", "text").putOpt("s", t.substring(CUSHION.length())));
                }
                busy = true;
                s.replace(0, s.length(), CUSHION);
                busy = false;
                e.setSelection(CUSHION.length());
            }
        });
        e.setOnEditorActionListener((v, id, k) -> {
            key("Return");
            return true;
        });
        e.setOnKeyListener((v, code, k) -> {
            if (k.getAction() != KeyEvent.ACTION_DOWN) return false;
            if (code == KeyEvent.KEYCODE_ENTER) {
                key("Return");
                return true;
            }
            if (code == KeyEvent.KEYCODE_DEL) {
                key("BackSpace");
                return true;
            }
            return false;
        });
        return e;
    }

    private void showKeyboard() {
        keys.requestFocus();
        ((InputMethodManager) getSystemService(INPUT_METHOD_SERVICE)).showSoftInput(keys, InputMethodManager.SHOW_FORCED);
    }

    // ---------- 🎛 the remote
    private void buildRemote(FrameLayout root) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(24, 48, 24, 24);
        TextView t = new TextView(this);
        t.setText("🎛 Remote for your PC\nThe phone's volume buttons also go to the next / previous slide.");
        t.setTextColor(Color.WHITE);
        t.setTextSize(16);
        col.addView(t);
        String[][] groups = {
                {"Slides", "◀ Previous|prev", "Next ▶|next", "▶ Start show|start", "■ End show|end", "⬛ Black screen|black", "⛶ Full screen|fullscreen"},
                {"Music", "⏮|track_prev", "⏯ Play / pause|play", "⏭|track_next"},
                {"Volume", "🔉 −|vol_down", "🔇 Mute|mute", "🔊 +|vol_up"}};
        for (String[] g : groups) {
            TextView h = new TextView(this);
            h.setText(g[0]);
            h.setTextColor(0xffff9b45);
            h.setTextSize(15);
            h.setPadding(0, 30, 0, 8);
            col.addView(h);
            GridLayout grid = new GridLayout(this);
            grid.setColumnCount(g[0].equals("Slides") ? 2 : 3);
            for (int i = 1; i < g.length; i++) {
                String[] p = g[i].split("\\|");
                Button b = new Button(this);
                b.setText(p[0]);
                b.setAllCaps(false);
                b.setTextSize(p[1].equals("next") || p[1].equals("prev") ? 22 : 16);
                GridLayout.LayoutParams lp = new GridLayout.LayoutParams(GridLayout.spec(GridLayout.UNDEFINED, 1f),
                        GridLayout.spec(GridLayout.UNDEFINED, 1f));
                lp.width = 0;
                lp.height = p[1].equals("next") || p[1].equals("prev") ? 260 : 150;
                b.setOnClickListener(v -> press(p[1]));
                grid.addView(b, lp);
            }
            col.addView(grid);
        }
        col.addView(status);
        status.setText("");
        root.addView(col);
    }

    private void press(String action) {
        new Thread(() -> {
            try {
                JSONObject r = link.call(inst, "/t/pc/remote", new Obj().putOpt("action", action), 30_000);
                say(r.optBoolean("ok") ? "" : r.optString("reason", "The PC didn't answer"));
            } catch (Exception ex) {
                say("Lost the connection to the PC");
            }
        }).start();
    }

    @Override
    public boolean onKeyDown(int code, KeyEvent e) {
        if (remote && code == KeyEvent.KEYCODE_VOLUME_UP) {
            press("next");
            return true;
        }
        if (remote && code == KeyEvent.KEYCODE_VOLUME_DOWN) {
            press("prev");
            return true;
        }
        return super.onKeyDown(code, e);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        running = false;
        synchronized (queue) {
            queue.notifyAll();
        }
        if (inst != null && !remote) new Thread(() -> {
            try {
                link.call(inst, "/t/pc/stop", new JSONObject(), 5000);
            } catch (Exception ignored) {
            }
        }).start();
    }

    // ---------- the screen, with touch: tap = click · double tap = double click · long press = right click ·
    //            drag = drag · two fingers = scroll (or move around when zoomed) · pinch = zoom
    class ScreenView extends View {
        private Bitmap frame;
        private final Matrix m = new Matrix(), inv = new Matrix();
        private float zoom = 1f, panX, panY;
        private final Paint paint = new Paint(Paint.FILTER_BITMAP_FLAG);
        private final GestureDetector taps;
        private final ScaleGestureDetector pinch;
        private boolean dragging, twoFinger;
        private float lastY2, lastX2, scrollAcc;

        ScreenView(Context c) {
            super(c);
            taps = new GestureDetector(c, new GestureDetector.SimpleOnGestureListener() {
                @Override
                public boolean onSingleTapConfirmed(MotionEvent e) {
                    send(ev("click", pc(e.getX(), e.getY())));
                    if (e.getY() < 60) hideBarSoon();
                    return true;
                }

                @Override
                public boolean onDoubleTap(MotionEvent e) {
                    send(ev("dclick", pc(e.getX(), e.getY())));
                    return true;
                }

                @Override
                public void onLongPress(MotionEvent e) {
                    if (!dragging && !twoFinger) send(ev("rclick", pc(e.getX(), e.getY())));
                }
            });
            pinch = new ScaleGestureDetector(c, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
                @Override
                public boolean onScale(ScaleGestureDetector d) {
                    float nz = Math.max(1f, Math.min(5f, zoom * d.getScaleFactor()));
                    float k = nz / zoom;
                    panX = d.getFocusX() - (d.getFocusX() - panX) * k;
                    panY = d.getFocusY() - (d.getFocusY() - panY) * k;
                    zoom = nz;
                    invalidate();
                    return true;
                }
            });
        }

        void setFrame(Bitmap b) {
            post(() -> {
                Bitmap old = frame;
                frame = b;
                invalidate();
                if (old != null && old != b) old.recycle();
            });
        }

        void resetZoom() {
            zoom = 1f;
            panX = panY = 0;
            invalidate();
        }

        private void layoutMatrix() {
            if (frame == null) return;
            float k = Math.min(getWidth() / (float) frame.getWidth(), getHeight() / (float) frame.getHeight());
            m.reset();
            m.postScale(k, k);
            m.postTranslate((getWidth() - frame.getWidth() * k) / 2, (getHeight() - frame.getHeight() * k) / 2);
            m.postScale(zoom, zoom);
            m.postTranslate(panX, panY);
            m.invert(inv);
        }

        /** A touch point → where it is on the PC's screen (0…1). */
        float[] pc(float x, float y) {
            if (frame == null) return new float[]{0.5f, 0.5f};
            layoutMatrix();
            float[] p = {x, y};
            inv.mapPoints(p);
            return new float[]{Math.max(0, Math.min(1, p[0] / frame.getWidth())), Math.max(0, Math.min(1, p[1] / frame.getHeight()))};
        }

        @Override
        protected void onDraw(Canvas c) {
            if (frame == null) return;
            layoutMatrix();
            c.drawBitmap(frame, m, paint);
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            pinch.onTouchEvent(e);
            int n = e.getPointerCount();
            switch (e.getActionMasked()) {
                case MotionEvent.ACTION_POINTER_DOWN:
                    twoFinger = true;
                    if (dragging) {
                        send(ev("up", pc(e.getX(0), e.getY(0))));
                        dragging = false;
                    }
                    lastX2 = (e.getX(0) + e.getX(1)) / 2;
                    lastY2 = (e.getY(0) + e.getY(1)) / 2;
                    return true;
                case MotionEvent.ACTION_MOVE:
                    if (twoFinger && n >= 2) {
                        float cx = (e.getX(0) + e.getX(1)) / 2, cy = (e.getY(0) + e.getY(1)) / 2;
                        if (zoom > 1.05f) {                       // zoomed in: move around
                            panX += cx - lastX2;
                            panY += cy - lastY2;
                            invalidate();
                        } else if (!pinch.isInProgress()) {       // otherwise: scroll the PC
                            scrollAcc += lastY2 - cy;
                            int steps = (int) (scrollAcc / 60);
                            if (steps != 0) {
                                scrollAcc -= steps * 60;
                                send(new Obj().putOpt("t", "scroll").putOpt("dy", steps));
                            }
                        }
                        lastX2 = cx;
                        lastY2 = cy;
                        return true;
                    }
                    break;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    if (dragging) send(ev("up", pc(e.getX(), e.getY())));
                    dragging = false;
                    twoFinger = false;
                    break;
                default:
                    break;
            }
            if (!twoFinger) {
                if (e.getActionMasked() == MotionEvent.ACTION_MOVE && e.getHistorySize() > 0) {
                    float dx = e.getX() - e.getHistoricalX(0), dy = e.getY() - e.getHistoricalY(0);
                    if (!dragging && e.getEventTime() - e.getDownTime() > 120 && Math.hypot(dx, dy) > 1) {
                        dragging = true;                            // one finger moving: a drag on the PC
                        send(ev("down", pc(e.getX() - dx, e.getY() - dy)));
                    }
                    if (dragging) send(ev("move", pc(e.getX(), e.getY())));
                }
                if (!dragging) taps.onTouchEvent(e);
            }
            return true;
        }
    }
}
