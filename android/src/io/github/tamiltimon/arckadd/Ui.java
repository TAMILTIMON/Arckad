package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.content.res.TypedArray;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.content.res.ColorStateList;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/** Colours, sizes and small widget helpers shared by every screen. */
final class Ui {
    static boolean dark;
    static int BG, BAR, CARD, TEXT, DIM, ACCENT, LINE, SEL, ON_ACCENT = Color.WHITE;

    private Ui() {
    }

    static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("arckad", Context.MODE_PRIVATE);
    }

    /** theme: "system" | "light" | "dark" */
    static void apply(Activity a) {
        String mode = prefs(a).getString("theme", "system");
        boolean sys = (a.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        dark = mode.equals("dark") || (mode.equals("system") && sys);
        if (dark) {
            BG = 0xFF111214; BAR = 0xFF1A1B1F; CARD = 0xFF222328; TEXT = 0xFFF1F1F4; DIM = 0xFFA2A3AB;
            ACCENT = 0xFF8E8CFF; LINE = 0xFF33343A; SEL = 0x338E8CFF;
        } else {
            BG = 0xFFF6F5F4; BAR = 0xFFFFFFFF; CARD = 0xFFFFFFFF; TEXT = 0xFF1C1C1F; DIM = 0xFF6B6B72;
            ACCENT = 0xFF5B5BD6; LINE = 0xFFE3E2E0; SEL = 0x225B5BD6;
        }
        a.setTheme(dark ? android.R.style.Theme_DeviceDefault_NoActionBar
                : android.R.style.Theme_DeviceDefault_Light_NoActionBar);
        Window w = a.getWindow();
        w.setStatusBarColor(BAR);
        w.setNavigationBarColor(BAR);
        w.setWindowAnimations(0);
        if (android.os.Build.VERSION.SDK_INT >= 23) {
            View d = w.getDecorView();
            int f = d.getSystemUiVisibility();
            f = dark ? (f & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR) : (f | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
            if (android.os.Build.VERSION.SDK_INT >= 26) {
                f = dark ? (f & ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR) : (f | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
            }
            d.setSystemUiVisibility(f);
        }
    }

    static int dialogTheme() {
        return dark ? android.R.style.Theme_DeviceDefault_Dialog_Alert
                : android.R.style.Theme_DeviceDefault_Light_Dialog_Alert;
    }

    static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    static TextView text(Context c, String s, float sp, int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT_BOLD);
        return t;
    }

    static GradientDrawable round(int color, float radiusPx) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(radiusPx);
        return g;
    }

    static Drawable pressable(Context c, int color, float radiusDp) {
        GradientDrawable shape = round(color, dp(c, radiusDp));
        GradientDrawable mask = round(Color.WHITE, dp(c, radiusDp));
        return new RippleDrawable(ColorStateList.valueOf(dark ? 0x33FFFFFF : 0x22000000), shape, mask);
    }

    static Drawable ripple(Context c) {
        TypedArray a = c.obtainStyledAttributes(new int[]{android.R.attr.selectableItemBackground});
        Drawable d = a.getDrawable(0);
        a.recycle();
        return d;
    }

    static Drawable rippleRound(Context c) {
        TypedArray a = c.obtainStyledAttributes(new int[]{android.R.attr.selectableItemBackgroundBorderless});
        Drawable d = a.getDrawable(0);
        a.recycle();
        return d;
    }

    /** A rounded button: primary = filled accent colour. */
    static TextView button(Context c, String label, boolean primary, View.OnClickListener l) {
        TextView b = text(c, label, 15, primary ? ON_ACCENT : TEXT, primary);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(c, 16), 0, dp(c, 16), 0);
        b.setMinHeight(dp(c, 46));
        b.setBackground(pressable(c, primary ? ACCENT : LINE, 12));
        b.setOnClickListener(l);
        return b;
    }

    /** Top-bar icon button (an emoji or symbol). */
    static TextView icon(Context c, String glyph, String description, View.OnClickListener l) {
        TextView t = text(c, glyph, 20, TEXT, false);
        t.setGravity(Gravity.CENTER);
        t.setContentDescription(description);
        t.setBackground(rippleRound(c));
        t.setOnClickListener(l);
        t.setLayoutParams(new LinearLayout.LayoutParams(dp(c, 46), dp(c, 46)));
        return t;
    }

    static LinearLayout card(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        int p = dp(c, 16);
        l.setPadding(p, p, p, p);
        l.setBackground(round(CARD, dp(c, 16)));
        return l;
    }

    static LinearLayout.LayoutParams matchWrap(Context c, int topMarginDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(c, topMarginDp);
        return lp;
    }

    static LinearLayout row(Context c, View... views) {
        LinearLayout r = new LinearLayout(c);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER_VERTICAL);
        for (int i = 0; i < views.length; i++) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
            if (i > 0) lp.leftMargin = dp(c, 8);
            r.addView(views[i], lp);
        }
        return r;
    }

    static void toast(Context c, String s) {
        Toast.makeText(c, s, Toast.LENGTH_SHORT).show();
    }

    static AlertDialog.Builder dialog(Context c) {
        return new AlertDialog.Builder(c, dialogTheme());
    }

    interface TextResult {
        void onText(String s);
    }

    static void askText(Context c, String title, String initial, String ok, TextResult r) {
        final EditText e = new EditText(c);
        e.setText(initial);
        e.setSingleLine(true);
        e.setInputType(InputType.TYPE_CLASS_TEXT);
        int dot = initial.lastIndexOf('.');
        e.setSelection(0, dot > 0 ? dot : initial.length());
        FrameLayout f = new FrameLayout(c);
        int p = dp(c, 20);
        f.setPadding(p, dp(c, 8), p, 0);
        f.addView(e);
        AlertDialog d = dialog(c).setTitle(title).setView(f)
                .setPositiveButton(ok, (di, w) -> r.onText(e.getText().toString().trim()))
                .setNegativeButton("Cancel", null).create();
        d.getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);
        d.show();
    }

    static void confirm(Context c, String title, String message, String ok, Runnable onOk) {
        dialog(c).setTitle(title).setMessage(message)
                .setPositiveButton(ok, (di, w) -> onOk.run())
                .setNegativeButton("Cancel", null).show();
    }

    static void info(Context c, String title, String message) {
        dialog(c).setTitle(title).setMessage(message).setPositiveButton("OK", null).show();
    }
}
