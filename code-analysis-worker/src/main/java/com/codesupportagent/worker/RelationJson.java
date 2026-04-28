package com.codesupportagent.worker;

final class RelationJson {
    String type;
    String source;
    String target;
    String filePath;
    String methodName;
    String reason;

    RelationJson(String type, String source, String target, String filePath, String methodName, String reason) {
        this.type = type;
        this.source = source;
        this.target = target;
        this.filePath = filePath;
        this.methodName = methodName;
        this.reason = reason;
    }
}
