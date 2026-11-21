package io.github.tamiltimon.arckadd;

import org.json.JSONException;
import org.json.JSONObject;

/** A JSON object whose putOpt() never throws (Android's org.json declares a checked exception). */
final class Obj extends JSONObject {
    Obj() {
        super();
    }

    static Obj of(String json) {
        try {
            Obj o = new Obj();
            JSONObject src = new JSONObject(json);
            for (java.util.Iterator<String> it = src.keys(); it.hasNext(); ) {
                String k = it.next();
                o.putOpt(k, src.opt(k));
            }
            return o;
        } catch (JSONException e) {
            return new Obj();
        }
    }

    @Override
    public Obj putOpt(String name, Object value) {
        try {
            super.putOpt(name, value);
        } catch (JSONException ignored) {
        }
        return this;
    }

    /** putOpt on any JSONObject without the checked exception. */
    static JSONObject put(JSONObject o, String name, Object value) {
        try {
            o.putOpt(name, value);
        } catch (JSONException ignored) {
        }
        return o;
    }
}
