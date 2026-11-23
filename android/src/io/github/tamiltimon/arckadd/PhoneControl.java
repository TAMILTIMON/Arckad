package io.github.tamiltimon.arckadd;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Build;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

/** Taps, swipes, keys and typing from the linked PC while you share your screen (stage 4 of Phone link).
 *  Android only starts this after you turn it on yourself: Settings → Accessibility → Arckad-D. */
public class PhoneControl extends AccessibilityService {
    static volatile PhoneControl instance;

    @Override
    protected void onServiceConnected() {
        if (!Ui.prefs(this).getBoolean("phone_control", false) || ChatHub.get(this).safeMode()) {
            disableSelf();                               // only runs while you actually want control from the PC
            return;
        }
        instance = this;
    }

    /** "Allow control from the PC" was switched off: the accessibility service turns itself off too. */
    static void stopIfRunning() {
        PhoneControl pc = instance;
        instance = null;
        if (pc != null) pc.disableSelf();
    }

    @Override
    public boolean onUnbind(android.content.Intent i) {
        instance = null;
        return super.onUnbind(i);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
    }

    @Override
    public void onInterrupt() {
    }

    /** Screen size in real pixels (the PC sends positions as 0..1 of the shared picture). */
    private float[] size() {
        DisplayMetrics dm = new DisplayMetrics();
        ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(dm);
        return new float[]{dm.widthPixels, dm.heightPixels};
    }

    private static float clamp(double v) {
        return (float) Math.max(0, Math.min(0.9999, v));
    }

    boolean gesture(double x1, double y1, double x2, double y2, long ms) {
        float[] s = size();
        Path p = new Path();
        p.moveTo(clamp(x1) * s[0], clamp(y1) * s[1]);
        if (x1 != x2 || y1 != y2) p.lineTo(clamp(x2) * s[0], clamp(y2) * s[1]);
        GestureDescription g = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(p, 0, Math.max(1, Math.min(ms, 5000)))).build();
        return dispatchGesture(g, null, null);
    }

    boolean key(String k) {
        switch (k) {
            case "back":
                return performGlobalAction(GLOBAL_ACTION_BACK);
            case "home":
                return performGlobalAction(GLOBAL_ACTION_HOME);
            case "recents":
                return performGlobalAction(GLOBAL_ACTION_RECENTS);
            case "notifications":
                return performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS);
            case "enter": {
                AccessibilityNodeInfo n = focused();
                if (n != null && Build.VERSION.SDK_INT >= 30)
                    return n.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId());
                return type("\n");
            }
            case "backspace": {
                AccessibilityNodeInfo n = focused();
                if (n == null) return false;
                CharSequence t = n.getText();
                String cur = t == null || n.isShowingHintText() ? "" : t.toString();
                return !cur.isEmpty() && setText(n, cur.substring(0, cur.length() - 1));
            }
            default:
                return false;
        }
    }

    private AccessibilityNodeInfo focused() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        return root == null ? null : root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
    }

    private static boolean setText(AccessibilityNodeInfo n, String text) {
        Bundle b = new Bundle();
        b.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        return n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, b);
    }

    /** Typing from the PC keyboard goes into the selected text field. */
    boolean type(String text) {
        AccessibilityNodeInfo n = focused();
        if (n == null || !n.isEditable()) return false;
        CharSequence t = n.getText();
        String cur = t == null || n.isShowingHintText() ? "" : t.toString();
        return setText(n, cur + text);
    }
}
