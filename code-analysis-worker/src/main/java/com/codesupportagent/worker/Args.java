package com.codesupportagent.worker;

import java.util.HashMap;
import java.util.Map;

final class Args {
    private Args() {
    }

    static Map<String, String> parse(String[] args) {
        Map<String, String> values = new HashMap<>();
        for (int index = 0; index < args.length; index++) {
            String item = args[index];
            if (!item.startsWith("--")) {
                continue;
            }
            String key = item.substring(2);
            String value = index + 1 < args.length && !args[index + 1].startsWith("--") ? args[++index] : "true";
            values.put(key, value);
        }
        return values;
    }
}
