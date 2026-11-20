package io.github.tamiltimon.arckadd;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** The Send and Receive tabs. */
final class ShareScreens {
    private ShareScreens() {
    }

    static final int[] MINUTES = {1, 2, 5, 10};

    static Spinner minutes(Context c, SharedPreferences prefs, String key) {
        Spinner s = new Spinner(c);
        String[] labels = new String[MINUTES.length];
        int sel = MINUTES.length - 1, saved = prefs.getInt(key, 10);
        for (int i = 0; i < MINUTES.length; i++) {
            labels[i] = MINUTES[i] + " min";
            if (MINUTES[i] == saved) sel = i;
        }
        ArrayAdapter<String> ad = new ArrayAdapter<>(c, android.R.layout.simple_spinner_item, labels);
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        s.setAdapter(ad);
        s.setSelection(sel);
        return s;
    }

    static int chosen(Spinner s) {
        return MINUTES[Math.max(0, s.getSelectedItemPosition())];
    }

    static String mmss(int secs) {
        return (secs / 60) + ":" + String.format(Locale.US, "%02d", secs % 60);
    }

    static ScrollView page(Context c, LinearLayout box) {
        ScrollView sv = new ScrollView(c);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 12);
        box.setPadding(p, p, p, p);
        sv.addView(box);
        return sv;
    }

    // ================================================================= Send
    static final class Send implements MainActivity.Screen {
        private final MainActivity a;
        private final ScrollView root;
        private final LinearLayout filesCard, peersBox;
        private final ProgressBar progress;
        private final TextView progressText, linkState, url;
        private final Switch linkSwitch;
        private final Spinner linkMinutes;
        private final ImageView qr;
        private final TextView copy;
        private final EditText ipBox;
        private final TextView ipStatus, ipAdd;
        private final LinearLayout savedBox;
        private boolean sending, syncing;

        Send(MainActivity a) {
            this.a = a;
            LinearLayout box = new LinearLayout(a);
            root = page(a, box);
            filesCard = Ui.card(a);
            box.addView(filesCard);

            LinearLayout devices = Ui.card(a);
            devices.addView(Ui.text(a, "Send to nearby Arckad-D", 17, Ui.TEXT, true));
            TextView hint = Ui.text(a, "Phones and computers running Arckad-D on this Wi-Fi with Receive turned on appear here.", 13, Ui.DIM, false);
            hint.setPadding(0, Ui.dp(a, 4), 0, Ui.dp(a, 8));
            devices.addView(hint);
            peersBox = new LinearLayout(a);
            peersBox.setOrientation(LinearLayout.VERTICAL);
            devices.addView(peersBox);
            progress = new ProgressBar(a, null, android.R.attr.progressBarStyleHorizontal);
            progress.setMax(1000);
            progress.setVisibility(View.GONE);
            devices.addView(progress, Ui.matchWrap(a, 8));
            progressText = Ui.text(a, "", 13, Ui.DIM, false);
            devices.addView(progressText);

            TextView vlan = Ui.text(a, "On another network or VLAN? Add its IP address (Receive must be on there).", 13, Ui.DIM, false);
            vlan.setPadding(0, Ui.dp(a, 14), 0, Ui.dp(a, 4));
            devices.addView(vlan);
            ipBox = new EditText(a);
            ipBox.setSingleLine(true);
            ipBox.setHint("IP address, e.g. 10.20.5.14");
            ipBox.setTextColor(Ui.TEXT);
            ipBox.setHintTextColor(Ui.DIM);
            ipBox.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
            ipAdd = Ui.button(a, "Add", true, v -> addIp());
            LinearLayout ipRow = new LinearLayout(a);
            ipRow.setGravity(Gravity.CENTER_VERTICAL);
            ipRow.addView(ipBox, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            ipRow.addView(ipAdd);
            devices.addView(ipRow);
            ipStatus = Ui.text(a, "", 13, Ui.DIM, false);
            devices.addView(ipStatus);
            savedBox = new LinearLayout(a);
            savedBox.setOrientation(LinearLayout.VERTICAL);
            devices.addView(savedBox);
            box.addView(devices, Ui.matchWrap(a, 12));
            loadSaved();

            LinearLayout link = Ui.card(a);
            link.addView(Ui.text(a, "Share as a link", 17, Ui.TEXT, true));
            TextView lh = Ui.text(a, "For phones or computers without Arckad-D: they open the link or scan the code in any browser.", 13, Ui.DIM, false);
            lh.setPadding(0, Ui.dp(a, 4), 0, Ui.dp(a, 8));
            link.addView(lh);
            linkState = Ui.text(a, "Off", 14, Ui.DIM, false);
            linkMinutes = minutes(a, Ui.prefs(a), "link_min");
            linkSwitch = new Switch(a);
            LinearLayout r = new LinearLayout(a);
            r.setGravity(Gravity.CENTER_VERTICAL);
            r.addView(linkState, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            r.addView(linkMinutes);
            r.addView(linkSwitch);
            link.addView(r);
            linkSwitch.setOnCheckedChangeListener((b, on) -> {
                if (!syncing) toggleLink(on);
            });
            qr = new ImageView(a);
            qr.setVisibility(View.GONE);
            link.addView(qr, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(a, 240)));
            url = Ui.text(a, "", 14, Ui.TEXT, true);
            url.setTextIsSelectable(true);
            url.setGravity(Gravity.CENTER);
            link.addView(url, Ui.matchWrap(a, 6));
            copy = Ui.button(a, "Copy link", false, v -> {
                ClipboardManager cm = (ClipboardManager) a.getSystemService(Context.CLIPBOARD_SERVICE);
                cm.setPrimaryClip(ClipData.newPlainText("link", MainActivity.link.url()));
                Ui.toast(a, "Link copied");
            });
            copy.setVisibility(View.GONE);
            link.addView(copy, Ui.matchWrap(a, 8));
            box.addView(link, Ui.matchWrap(a, 12));
        }

        private void loadSaved() {
            String saved = Ui.prefs(a).getString("manual_ips", "");
            MainActivity.nearby.manual.clear();
            for (String h : saved.split(",")) if (!h.trim().isEmpty()) MainActivity.nearby.manual.add(h.trim());
            refreshSaved();
        }

        private void saveIps() {
            synchronized (MainActivity.nearby.manual) {
                Ui.prefs(a).edit().putString("manual_ips", android.text.TextUtils.join(",", MainActivity.nearby.manual)).apply();
            }
            refreshSaved();
        }

        private void refreshSaved() {
            savedBox.removeAllViews();
            List<String> hosts;
            synchronized (MainActivity.nearby.manual) {
                hosts = new ArrayList<>(MainActivity.nearby.manual);
            }
            for (final String h : hosts) {
                LinearLayout r = new LinearLayout(a);
                r.setGravity(Gravity.CENTER_VERTICAL);
                r.addView(Ui.text(a, "Saved: " + h, 14, Ui.TEXT, false), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
                r.addView(Ui.icon(a, "✕", "Forget " + h, v -> {
                    MainActivity.nearby.manual.remove(h);
                    saveIps();
                }));
                savedBox.addView(r);
            }
        }

        private void addIp() {
            final String host = ipBox.getText().toString().trim();
            if (host.isEmpty() || host.contains(" ")) return;
            ipAdd.setEnabled(false);
            ipStatus.setText("Checking " + host + "…");
            new Thread(() -> {
                Object res = MainActivity.nearby.helloAt(host, 2500);
                a.runOnUiThread(() -> {
                    ipAdd.setEnabled(true);
                    if (res instanceof Net.Peer) {
                        Net.Peer p = (Net.Peer) res;
                        if (!MainActivity.nearby.manual.contains(host)) MainActivity.nearby.manual.add(host);
                        saveIps();
                        ipBox.setText("");
                        ipStatus.setText("✓ Found " + p.name + " (" + p.os + ") at " + host + ". Saved: it appears above whenever its Receive is on.");
                        refreshPeers();
                    } else {
                        ipStatus.setText("✗ No Arckad-D answered at " + host + " (" + res + "). On that device, open Arckad-D and turn "
                                + "Receive on. The firewall must allow TCP ports 47821–47823 between the networks (a working ping isn't enough).");
                    }
                });
            }).start();
        }

        @Override
        public View view() {
            return root;
        }

        @Override
        public void onShow() {
            refreshFiles();
            refreshPeers();
            try {
                MainActivity.nearby.startScan();
            } catch (Exception e) {
                progressText.setText("Can't look for nearby devices: " + e.getMessage());
            }
            tick();
        }

        @Override
        public void onHide() {
            MainActivity.nearby.stopScan();
        }

        @Override
        public void topBar(LinearLayout bar) {
            bar.addView(a.title("Send"), MainActivity.grow());
        }

        @Override
        public boolean back() {
            return false;
        }

        void refreshFiles() {
            filesCard.removeAllViews();
            filesCard.addView(Ui.text(a, "Files to send", 17, Ui.TEXT, true));
            List<File> items = MainActivity.link.items;
            if (items.isEmpty()) {
                TextView t = Ui.text(a, "Nothing chosen yet. In Files, long-press to select, then tap 📡 at the top.", 13, Ui.DIM, false);
                t.setPadding(0, Ui.dp(a, 6), 0, Ui.dp(a, 8));
                filesCard.addView(t);
            }
            synchronized (items) {
                for (int i = 0; i < Math.min(6, items.size()); i++) {
                    File f = items.get(i);
                    TextView t = Ui.text(a, "• " + f.getName() + "   " + (f.isDirectory() ? "folder" : Fs.size(f.length())), 14, Ui.TEXT, false);
                    t.setPadding(0, Ui.dp(a, 3), 0, Ui.dp(a, 3));
                    filesCard.addView(t);
                }
                if (items.size() > 6) filesCard.addView(Ui.text(a, "…and " + (items.size() - 6) + " more", 13, Ui.DIM, false));
            }
            TextView choose = Ui.button(a, "Choose files", items.isEmpty(), v -> {
                a.showTab("files");
                Ui.toast(a, "Long-press files to select them, then tap 📡");
            });
            if (items.isEmpty()) filesCard.addView(choose, Ui.matchWrap(a, 6));
            else filesCard.addView(Ui.row(a, choose, Ui.button(a, "Clear", false, v -> {
                MainActivity.link.items.clear();
                refreshFiles();
            })), Ui.matchWrap(a, 8));
        }

        void refreshPeers() {
            peersBox.removeAllViews();
            List<Net.Peer> peers = MainActivity.nearby.peers();
            if (peers.isEmpty()) {
                LinearLayout l = new LinearLayout(a);
                l.setGravity(Gravity.CENTER_VERTICAL);
                ProgressBar spin = new ProgressBar(a);
                l.addView(spin, new LinearLayout.LayoutParams(Ui.dp(a, 22), Ui.dp(a, 22)));
                TextView t = Ui.text(a, "  Looking for nearby devices…", 14, Ui.DIM, false);
                l.addView(t);
                peersBox.addView(l);
            }
            for (final Net.Peer p : peers) {
                LinearLayout row = new LinearLayout(a);
                row.setGravity(Gravity.CENTER_VERTICAL);
                row.setPadding(0, Ui.dp(a, 6), 0, Ui.dp(a, 6));
                String icon = "Android".equals(p.os) ? "📱" : "Windows".equals(p.os) ? "🖥" : "💻";
                row.addView(Ui.text(a, icon, 26, Ui.TEXT, false));
                LinearLayout texts = new LinearLayout(a);
                texts.setOrientation(LinearLayout.VERTICAL);
                texts.setPadding(Ui.dp(a, 12), 0, Ui.dp(a, 8), 0);
                texts.addView(Ui.text(a, p.name, 15, Ui.TEXT, true));
                texts.addView(Ui.text(a, p.os + " · " + p.ip + (p.manual ? " · by IP" : ""), 12, Ui.DIM, false));
                row.addView(texts, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
                TextView b = Ui.button(a, "Send", true, v -> send(p));
                b.setEnabled(!sending);
                b.setAlpha(sending ? 0.4f : 1f);
                row.addView(b);
                peersBox.addView(row);
            }
        }

        private void send(final Net.Peer p) {
            final List<File> items = new ArrayList<>(MainActivity.link.items);
            if (items.isEmpty()) {
                Ui.toast(a, "Choose some files first");
                return;
            }
            sending = true;
            refreshPeers();
            progress.setVisibility(View.VISIBLE);
            progress.setProgress(0);
            progressText.setText("Offering " + items.size() + (items.size() == 1 ? " item" : " items") + " to " + p.name + "…");
            new Thread(() -> {
                String err = MainActivity.nearby.sendFiles(p, items, (sent, total, what) -> a.runOnUiThread(() -> {
                    progress.setProgress(total > 0 ? (int) (sent * 1000 / total) : 1000);
                    progressText.setText(what + "  " + Fs.size(sent) + " / " + Fs.size(total));
                }));
                a.runOnUiThread(() -> {
                    sending = false;
                    refreshPeers();
                    if (err != null) progressText.setText(err);
                    else {
                        progress.setProgress(1000);
                        progressText.setText("Sent to " + p.name + " ✓");
                        Ui.toast(a, "Sent to " + p.name);
                    }
                });
            }).start();
        }

        private void toggleLink(boolean on) {
            Net.Link link = MainActivity.link;
            if (on && !link.active()) {
                if (link.items.isEmpty()) {
                    Ui.toast(a, "Choose some files first");
                    setSwitch(false);
                    return;
                }
                try {
                    Ui.prefs(a).edit().putInt("link_min", chosen(linkMinutes)).apply();
                    link.start(chosen(linkMinutes));
                } catch (Exception e) {
                    Ui.toast(a, "Couldn't start sharing: " + e.getMessage());
                    setSwitch(false);
                    return;
                }
                String u = link.url();
                url.setText(u);
                boolean[][] m = Qr.encode(u);
                if (m != null) {
                    qr.setImageBitmap(qrBitmap(m));
                    qr.setVisibility(View.VISIBLE);
                }
                copy.setVisibility(View.VISIBLE);
            } else if (!on) {
                link.stop();
                qr.setVisibility(View.GONE);
                copy.setVisibility(View.GONE);
                url.setText("");
            }
            tick();
        }

        private void setSwitch(boolean on) {
            syncing = true;
            linkSwitch.setChecked(on);
            syncing = false;
        }

        static Bitmap qrBitmap(boolean[][] m) {
            int n = m.length, s = 10, q = 3;
            Bitmap b = Bitmap.createBitmap((n + 2 * q) * s, (n + 2 * q) * s, Bitmap.Config.RGB_565);
            b.eraseColor(Color.WHITE);
            for (int y = 0; y < n; y++)
                for (int x = 0; x < n; x++)
                    if (m[y][x])
                        for (int dy = 0; dy < s; dy++)
                            for (int dx = 0; dx < s; dx++) b.setPixel((x + q) * s + dx, (y + q) * s + dy, Color.BLACK);
            return b;
        }

        void tick() {
            Net.Link link = MainActivity.link;
            if (link.active()) {
                linkState.setText("On · " + mmss(link.remaining()) + " left");
                linkState.setTextColor(Ui.ACCENT);
            } else {
                if (linkSwitch.isChecked()) {
                    link.stop();
                    setSwitch(false);
                    qr.setVisibility(View.GONE);
                    copy.setVisibility(View.GONE);
                    url.setText("");
                }
                linkState.setText("Off");
                linkState.setTextColor(Ui.DIM);
            }
        }
    }

    // ================================================================= Receive
    static final class Receive implements MainActivity.Screen {
        private final MainActivity a;
        private final ScrollView root;
        private final Switch toggle;
        private final Spinner mins;
        private final TextView state, log;
        private boolean syncing;
        private final StringBuilder lines = new StringBuilder();

        Receive(MainActivity a) {
            this.a = a;
            LinearLayout box = new LinearLayout(a);
            root = page(a, box);
            LinearLayout card = Ui.card(a);
            TextView big = Ui.text(a, "📥", 44, Ui.TEXT, false);
            big.setGravity(Gravity.CENTER);
            card.addView(big);
            TextView t = Ui.text(a, "Receive files", 18, Ui.TEXT, true);
            t.setGravity(Gravity.CENTER);
            card.addView(t);
            TextView d = Ui.text(a, "Turn this on, then send from Arckad-D on a computer or another phone. "
                    + "You'll be asked before anything is saved.", 13, Ui.DIM, false);
            d.setGravity(Gravity.CENTER);
            d.setPadding(0, Ui.dp(a, 4), 0, Ui.dp(a, 12));
            card.addView(d);
            LinearLayout r = new LinearLayout(a);
            r.setGravity(Gravity.CENTER_VERTICAL);
            r.addView(Ui.text(a, "Let nearby devices find me", 15, Ui.TEXT, true), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            mins = minutes(a, Ui.prefs(a), "recv_min");
            r.addView(mins);
            toggle = new Switch(a);
            r.addView(toggle);
            card.addView(r);
            toggle.setOnCheckedChangeListener((b, on) -> {
                if (!syncing) setReceiving(on);
            });
            state = Ui.text(a, "", 14, Ui.DIM, false);
            state.setPadding(0, Ui.dp(a, 8), 0, 0);
            card.addView(state);
            box.addView(card);

            LinearLayout card2 = Ui.card(a);
            card2.addView(Ui.text(a, "This phone's name", 15, Ui.TEXT, true));
            final EditText name = new EditText(a);
            name.setSingleLine(true);
            name.setText(MainActivity.nearby.name);
            name.setTextColor(Ui.TEXT);
            name.addTextChangedListener(new TextWatcher() {
                @Override
                public void beforeTextChanged(CharSequence s, int st, int c, int af) {
                }

                @Override
                public void onTextChanged(CharSequence s, int st, int b, int c) {
                }

                @Override
                public void afterTextChanged(Editable s) {
                    String v = s.toString().trim();
                    if (!v.isEmpty()) {
                        MainActivity.nearby.name = v;
                        MainActivity.link.deviceName = v;
                        Ui.prefs(a).edit().putString("device_name", v).apply();
                    }
                }
            });
            card2.addView(name);
            card2.addView(Ui.button(a, "Open received files", false, v -> {
                a.showTab("files");
                a.files.open(Fs.received(), true);
            }), Ui.matchWrap(a, 6));
            box.addView(card2, Ui.matchWrap(a, 12));

            LinearLayout card3 = Ui.card(a);
            card3.addView(Ui.text(a, "Activity", 15, Ui.TEXT, true));
            log = Ui.text(a, "", 13, Ui.DIM, false);
            log.setPadding(0, Ui.dp(a, 6), 0, 0);
            card3.addView(log);
            box.addView(card3, Ui.matchWrap(a, 12));
        }

        @Override
        public View view() {
            return root;
        }

        @Override
        public void onShow() {
            tick();
        }

        @Override
        public void onHide() {
        }

        @Override
        public void topBar(LinearLayout bar) {
            bar.addView(a.title("Receive"), MainActivity.grow());
        }

        @Override
        public boolean back() {
            return false;
        }

        private void setReceiving(boolean on) {
            Net.Nearby nb = MainActivity.nearby;
            if (on && !nb.visible()) {
                try {
                    Ui.prefs(a).edit().putInt("recv_min", chosen(mins)).apply();
                    nb.setVisible(chosen(mins));
                    line("Visible as “" + nb.name + "”");
                } catch (Exception e) {
                    Ui.toast(a, "Couldn't turn on receiving: " + e.getMessage());
                    set(false);
                }
            } else if (!on) {
                nb.hide(false);
                line("Receiving turned off");
            }
            tick();
        }

        private void set(boolean on) {
            syncing = true;
            toggle.setChecked(on);
            syncing = false;
        }

        void line(String s) {
            String t = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date());
            lines.insert(0, t + "  " + s + "\n");
            if (lines.length() > 3000) lines.setLength(3000);
            log.setText(lines.toString().trim());
        }

        void progress(Net.Incoming in) {
            state.setText("Receiving from " + in.from + ": " + in.doneFiles + " / " + in.rel.size() + " files ("
                    + Fs.size(in.received) + ")");
        }

        void tick() {
            Net.Nearby nb = MainActivity.nearby;
            if (nb.visible()) {
                if (!nb.busyReceiving()) {
                    state.setText("On · visible as “" + nb.name + "” for " + mmss(nb.remaining())
                            + "\nFiles go to " + Fs.shortPath(Fs.received()));
                }
                state.setTextColor(Ui.ACCENT);
                if (!toggle.isChecked()) set(true);
            } else {
                state.setText("Off · other devices can't see this phone");
                state.setTextColor(Ui.DIM);
                if (toggle.isChecked()) set(false);
            }
        }
    }
}
