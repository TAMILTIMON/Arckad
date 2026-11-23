package io.github.tamiltimon.arckadd;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.telephony.TelephonyManager;

import org.json.JSONObject;

/** Watches the phone's call state (ringing → answered → ended) and tells the linked PC, so its 📱 panel can show
 *  "Incoming call" with Answer / Decline. Android delivers this even when Arckad-D is closed. */
public class PhoneCalls extends BroadcastReceiver {
    static volatile String state = "idle", number = "", name = "";
    static volatile double since = 0;

    @Override
    public void onReceive(Context c, Intent i) {
        if (!TelephonyManager.ACTION_PHONE_STATE_CHANGED.equals(i.getAction())) return;
        String s = i.getStringExtra(TelephonyManager.EXTRA_STATE);
        String num = i.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER);   // only with call-log permission
        String next = TelephonyManager.EXTRA_STATE_RINGING.equals(s) ? "ringing"
                : TelephonyManager.EXTRA_STATE_OFFHOOK.equals(s) ? "offhook" : "idle";
        if (num != null && !num.isEmpty()) {
            number = num;
            String n = new PhoneLink(c).contactName(num);
            name = n == null ? "" : n;
        }
        if (next.equals(state) && num == null) return;      // Android sends each change twice (with and without number)
        if (!next.equals(state)) since = System.currentTimeMillis() / 1000.0;
        state = next;
        if (next.equals("idle")) {
            number = "";
            name = "";
        }
        JSONObject ev = new Obj().putOpt("type", "call").putOpt("state", state).putOpt("number", number).putOpt("name", name)
                .putOpt("since", since);
        ChatHub.get(c).engine.link.pushPhone(ev);
    }
}
