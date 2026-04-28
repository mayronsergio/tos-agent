package com.codesupportagent.worker;

import java.util.ArrayList;
import java.util.List;

final class SymbolJson {
    String filePath;
    String fileName;
    String symbolType;
    String name;
    String artifactId;
    String version;
    String sourceType;
    String language = "java";
    String packageName;
    String className;
    String enumName;
    String interfaceName;
    String superclass;
    String genericSuperclass;
    List<String> genericArguments = new ArrayList<>();
    List<String> interfaces = new ArrayList<>();
    List<String> annotations = new ArrayList<>();
    List<String> methods = new ArrayList<>();
    List<String> constructors = new ArrayList<>();
    List<String> imports = new ArrayList<>();
    List<String> fields = new ArrayList<>();
    List<String> constants = new ArrayList<>();
    List<String> overriddenMethods = new ArrayList<>();
    String fieldType;
    List<String> fieldAnnotations = new ArrayList<>();
    String methodName;
    String entityName;
    String layer;
    String tableName;
    String signature;
    int lineStart = 1;
    int lineEnd = 1;
    String snippet = "";
    List<String> tags = new ArrayList<>();

    static SymbolJson base(Context context, String filePath, String fileName, String symbolType, String name) {
        SymbolJson symbol = new SymbolJson();
        symbol.filePath = filePath;
        symbol.fileName = fileName;
        symbol.symbolType = symbolType;
        symbol.name = name;
        symbol.artifactId = context.artifactId().isBlank() ? null : context.artifactId();
        symbol.version = context.version().isBlank() ? null : context.version();
        symbol.sourceType = context.sourceType();
        return symbol;
    }
}
