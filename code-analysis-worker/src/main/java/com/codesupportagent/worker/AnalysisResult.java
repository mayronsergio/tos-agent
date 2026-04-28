package com.codesupportagent.worker;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

final class AnalysisResult {
    List<SymbolJson> symbols = new ArrayList<>();
    List<RelationJson> relations = new ArrayList<>();
    Map<String, Integer> metrics = new LinkedHashMap<>();
}
