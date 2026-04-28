from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from app.models.schemas import Evidence, SearchMode
from app.services.repository import CodeRepository
from app.services.vector_index import VectorIndex


TECHNICAL_LAYERS = {"service", "dao/repository", "controller/action", "entity"}
TECHNICAL_WORDS = {
    "classe",
    "class",
    "arquivo",
    "file",
    "metodo",
    "method",
    "tabela",
    "table",
    "entidade",
    "entity",
    "enum",
    "interface",
}


class SearchService:
    def __init__(self, repository: CodeRepository, vector_index: VectorIndex):
        self.repository = repository
        self.vector_index = vector_index

    def search(self, query: str, mode: SearchMode, limit: int) -> list[Evidence]:
        query_type = self._detect_query_type(query)
        symbol_results = self._symbol_results(query, limit * 6)
        text_results = self._with_text_scores(self.repository.search_text(query, limit=limit * 6), query)

        if mode == SearchMode.text:
            results = self._merge([symbol_results, text_results], limit, symbol_first=query_type == "symbol_query")
            return self._group_by_file(results, limit)

        semantic_results = self._with_semantic_scores(self.vector_index.search(query, limit=limit * 4), query)
        if mode == SearchMode.semantic:
            return self._group_by_file(self._merge([semantic_results, symbol_results], limit, symbol_first=False), limit)

        if query_type == "symbol_query":
            results = self._merge([symbol_results, text_results, semantic_results], limit, symbol_first=True)
        else:
            expanded_text = self._expanded_text_results(query, limit)
            results = self._merge([text_results, expanded_text, symbol_results, semantic_results], limit, symbol_first=False)
        return self._group_by_file(results, limit)

    def _symbol_results(self, query: str, limit: int) -> list[Evidence]:
        query_norm = normalize_identifier(query)
        query_tokens = set(tokenize(query))
        seen_keys: set[tuple[str, int | None, str | None]] = set()
        results: list[Evidence] = []
        candidates = [
            *self.repository.symbol_candidates(query, limit=max(limit * 4, 100)),
            *self.repository.all_snippets(limit=10000),
        ]
        for item in candidates:
            key = (item.file_path, item.line_start, item.matchedSymbol)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            symbol_score, reason, match_type = self._score_symbol(item, query_norm, query_tokens)
            if symbol_score <= 0:
                continue
            item.symbolScore = symbol_score
            item.finalScore = symbol_score + item.textScore + item.semanticScore
            item.score = item.finalScore
            item.matchType = match_type
            item.reason = reason
            item.filePath = item.file_path
            item.fileName = item.fileName or Path(item.file_path).name
            results.append(item)
        results.sort(key=self._sort_key, reverse=True)
        return results[:limit]

    def _score_symbol(self, item: Evidence, query_norm: str, query_tokens: set[str]) -> tuple[float, str, str]:
        symbol_type = item.symbolType or ""
        file_name = normalize_identifier(item.fileName or Path(item.file_path).name)
        file_stem = normalize_identifier(Path(item.file_path).stem)
        class_name = normalize_identifier(item.class_name or item.entity_name or "")
        method_name = normalize_identifier(item.method_name or "")
        table_name = normalize_identifier(item.table_name or "")
        package_name = normalize_identifier(item.package or "")
        generic_superclass = normalize_identifier(item.genericSuperclass or "")
        generic_arguments = [normalize_identifier(arg) for arg in item.genericArguments]
        matched_symbol = item.matchedSymbol or item.method_name or item.class_name or item.table_name or item.fileName
        matched_norm = normalize_identifier(matched_symbol or "")
        snippet_norm = normalize_text(item.snippet)
        tags = {normalize_text(tag) for tag in item.tags}

        candidates = [
            (100, "classe/interface/enum com nome exato", "classe exata", symbol_type in {"class", "interface", "enum"} and equivalent(query_norm, matched_norm)),
            (100, "classe/interface/enum com nome exato", "classe exata", equivalent(query_norm, class_name)),
            (95, "arquivo com nome exato", "arquivo exato", equivalent(query_norm, file_name) or equivalent(query_norm, file_stem)),
            (90, "tabela com nome exato", "tabela exata", bool(table_name) and equivalent(query_norm, table_name)),
            (85, "entidade JPA correspondente", "entidade", bool(item.entity_name) and equivalent(query_norm, normalize_identifier(item.entity_name))),
            (80, "metodo com nome exato", "metodo exato", bool(method_name) and equivalent(query_norm, method_name)),
            (70, "campo/constante com nome exato", "campo/constante exato", symbol_type in {"field", "constant"} and equivalent(query_norm, matched_norm)),
            (60, "classe contendo o termo pesquisado", "classe relacionada", bool(class_name) and contains_term(class_name, query_norm)),
            (50, "metodo contendo o termo pesquisado", "metodo relacionado", bool(method_name) and contains_term(method_name, query_norm)),
            (45, "tabela contendo o termo pesquisado", "tabela relacionada", bool(table_name) and contains_term(table_name, query_norm)),
            (45, "tipo parametrizado contendo o termo pesquisado", "tipo parametrizado", any(contains_term(arg, query_norm) for arg in generic_arguments)),
            (40, "classe generica contendo o termo pesquisado", "classe generica", bool(generic_superclass) and contains_term(generic_superclass, query_norm)),
            (25, "pacote contendo o termo pesquisado", "pacote relacionado", bool(package_name) and contains_term(package_name, query_norm)),
            (10, "trecho de codigo contendo o termo", "mencao textual", contains_all_tokens(snippet_norm, query_tokens)),
        ]
        for score, reason, match_type, matched in candidates:
            if matched:
                if item.layer in TECHNICAL_LAYERS and score < 85:
                    score += 5
                    reason = f"{reason}; camada tecnica {item.layer}"
                if "entity" in tags and score < 85:
                    score += 5
                    reason = f"{reason}; entidade detectada"
                return float(score), reason, match_type
        return 0.0, "", ""

    def _with_text_scores(self, items: list[Evidence], query: str) -> list[Evidence]:
        query_tokens = set(tokenize(query))
        for item in items:
            item.textScore = max(item.textScore, item.score, self._score_text(item, query_tokens))
            item.finalScore = item.symbolScore + item.textScore + item.semanticScore
            item.score = item.finalScore
            item.matchType = item.matchType or "textual"
            if not item.reason:
                item.reason = "termo encontrado no texto indexado"
            item.filePath = item.file_path
            item.fileName = item.fileName or Path(item.file_path).name
        return items

    def _with_semantic_scores(self, items: list[Evidence], query: str) -> list[Evidence]:
        for item in items:
            item.semanticScore = max(item.semanticScore, item.score * 20)
            item.finalScore = item.symbolScore + item.textScore + item.semanticScore
            item.score = item.finalScore
            item.matchType = item.matchType or "semantico"
            item.reason = item.reason or "resultado por similaridade semantica"
            item.filePath = item.file_path
            item.fileName = item.fileName or Path(item.file_path).name
        return items

    def _expanded_text_results(self, query: str, limit: int) -> list[Evidence]:
        terms = tokenize(query)
        expanded = [term for term in terms if len(term) >= 4 and term not in TECHNICAL_WORDS]
        results: list[Evidence] = []
        for term in expanded[:6]:
            results.extend(self._with_text_scores(self.repository.search_text(term, limit=limit), query))
        return results

    def _score_text(self, item: Evidence, query_tokens: set[str]) -> float:
        haystack = normalize_text(
            " ".join(
                [
                    item.file_path,
                    item.package or "",
                    item.class_name or "",
                    item.method_name or "",
                    item.table_name or "",
                    item.message or "",
                    item.validation or "",
                    item.snippet,
                ]
            )
        )
        if not query_tokens:
            return 0.0
        matched = sum(1 for token in query_tokens if token in haystack)
        return float(matched * 10)

    def _merge(self, groups: list[list[Evidence]], limit: int, symbol_first: bool) -> list[Evidence]:
        merged: dict[tuple[str, int | None, str | None, str | None], Evidence] = {}
        for item in [candidate for group in groups for candidate in group]:
            key = (item.file_path, item.line_start, item.method_name, item.matchedSymbol)
            existing = merged.get(key)
            if existing:
                existing.symbolScore = max(existing.symbolScore, item.symbolScore)
                existing.textScore = max(existing.textScore, item.textScore)
                existing.semanticScore = max(existing.semanticScore, item.semanticScore)
                existing.finalScore = existing.symbolScore + existing.textScore + existing.semanticScore
                existing.score = existing.finalScore
                if item.reason and len(item.reason) > len(existing.reason):
                    existing.reason = item.reason
                if item.matchType and existing.matchType == "textual":
                    existing.matchType = item.matchType
                continue
            item.finalScore = item.symbolScore + item.textScore + item.semanticScore or item.score
            item.score = item.finalScore
            merged[key] = item

        results = list(merged.values())
        if symbol_first:
            results.sort(key=self._sort_key, reverse=True)
        else:
            results.sort(key=lambda item: (item.finalScore, item.symbolScore, item.textScore), reverse=True)
        return results[: max(limit * 3, limit)]

    def _group_by_file(self, items: list[Evidence], limit: int) -> list[Evidence]:
        best_by_file: dict[str, Evidence] = {}
        overflow: list[Evidence] = []
        for item in items:
            if item.file_path not in best_by_file:
                best_by_file[item.file_path] = item
            else:
                overflow.append(item)
        primary = sorted(best_by_file.values(), key=self._sort_key, reverse=True)
        secondary = sorted(overflow, key=self._sort_key, reverse=True)
        return [*primary, *secondary][:limit]

    def _detect_query_type(self, query: str) -> str:
        stripped = query.strip()
        tokens = tokenize(stripped)
        if len(tokens) <= 3 and any(item in normalize_text(stripped) for item in TECHNICAL_WORDS):
            return "symbol_query"
        if "/" in stripped or "\\" in stripped or stripped.lower().endswith((".java", ".class", ".xml")):
            return "symbol_query"
        compact = re.sub(r"[\s_.\-/]+", "", stripped)
        if len(tokens) <= 2 and compact and len(compact) <= 80:
            return "symbol_query"
        if re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", stripped):
            return "symbol_query"
        return "descriptive_query"

    def _sort_key(self, item: Evidence) -> tuple[float, float, float, float]:
        layer_bonus = 3.0 if item.layer in TECHNICAL_LAYERS else 0.0
        return (item.finalScore + layer_bonus, item.symbolScore, item.textScore, item.semanticScore)


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.casefold()


def normalize_identifier(value: str) -> str:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value or "")
    normalized = normalize_text(camel_split)
    normalized = normalized.strip().lstrip("/\\")
    normalized = re.sub(r"\.(java|class|xml)$", "", normalized)
    parts = re.findall(r"[a-z0-9]+", normalized)
    return "".join(singularize(normalize_text(part)) for part in parts)


def tokenize(value: str) -> list[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    normalized = normalize_text(value)
    return [singularize(token) for token in re.findall(r"[a-z0-9]+", normalized) if len(token) >= 2]


def singularize(value: str) -> str:
    if len(value) > 3 and value.endswith("es"):
        return value[:-2]
    if len(value) > 3 and value.endswith("s"):
        return value[:-1]
    return value


def equivalent(left: str, right: str) -> bool:
    return bool(left and right and singularize(left) == singularize(right))


def contains_term(haystack: str, needle: str) -> bool:
    return bool(needle and haystack and (needle in haystack or singularize(needle) in singularize(haystack)))


def contains_all_tokens(haystack: str, tokens: set[str]) -> bool:
    return bool(tokens) and all(token in haystack for token in tokens)
