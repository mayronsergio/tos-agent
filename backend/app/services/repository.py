from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from app.indexing.extractors import CodeSymbol
from app.models.schemas import Evidence


class CodeRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self.connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    symbol_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    file_name TEXT,
                    artifact_id TEXT,
                    version TEXT,
                    source_type TEXT,
                    language TEXT,
                    package TEXT,
                    class_name TEXT,
                    enum_name TEXT,
                    interface_name TEXT,
                    superclass TEXT,
                    generic_superclass TEXT,
                    generic_arguments TEXT,
                    interfaces TEXT,
                    annotations TEXT,
                    methods TEXT,
                    constructors TEXT,
                    imports TEXT,
                    fields TEXT,
                    constants TEXT,
                    overridden_methods TEXT,
                    field_type TEXT,
                    field_annotations TEXT,
                    method_name TEXT,
                    entity_name TEXT,
                    layer TEXT,
                    table_name TEXT,
                    message TEXT,
                    validation TEXT,
                    line_start INTEGER,
                    line_end INTEGER,
                    snippet TEXT NOT NULL,
                    tags TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
            self._ensure_symbol_column(con, "artifact_id", "TEXT")
            self._ensure_symbol_column(con, "version", "TEXT")
            self._ensure_symbol_column(con, "source_type", "TEXT")
            self._ensure_symbol_column(con, "language", "TEXT")
            self._ensure_symbol_column(con, "file_name", "TEXT")
            self._ensure_symbol_column(con, "enum_name", "TEXT")
            self._ensure_symbol_column(con, "interface_name", "TEXT")
            self._ensure_symbol_column(con, "superclass", "TEXT")
            self._ensure_symbol_column(con, "generic_superclass", "TEXT")
            self._ensure_symbol_column(con, "generic_arguments", "TEXT")
            self._ensure_symbol_column(con, "interfaces", "TEXT")
            self._ensure_symbol_column(con, "annotations", "TEXT")
            self._ensure_symbol_column(con, "methods", "TEXT")
            self._ensure_symbol_column(con, "constructors", "TEXT")
            self._ensure_symbol_column(con, "imports", "TEXT")
            self._ensure_symbol_column(con, "fields", "TEXT")
            self._ensure_symbol_column(con, "constants", "TEXT")
            self._ensure_symbol_column(con, "overridden_methods", "TEXT")
            self._ensure_symbol_column(con, "field_type", "TEXT")
            self._ensure_symbol_column(con, "field_annotations", "TEXT")
            con.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file_name ON symbols(file_name)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_symbols_class ON symbols(class_name)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_symbols_table ON symbols(table_name)")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    file_path TEXT,
                    method_name TEXT,
                    reason TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_graph_relations_source ON graph_relations(source)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_graph_relations_target ON graph_relations(target)")

    def reset(self) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM symbols")
            con.execute("DELETE FROM files")
            con.execute("DELETE FROM graph_relations")

    def clear_settings(self) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM app_settings")

    def upsert_file(self, file_path: str) -> None:
        with self.connect() as con:
            con.execute("INSERT OR REPLACE INTO files(path, indexed_at) VALUES (?, CURRENT_TIMESTAMP)", (file_path,))

    def insert_symbols(self, symbols: Iterable[CodeSymbol]) -> int:
        rows = [
            (
                symbol.file_path,
                symbol.symbol_type,
                symbol.name,
                symbol.file_name,
                symbol.artifact_id,
                symbol.version,
                symbol.source_type,
                symbol.language,
                symbol.package,
                symbol.class_name,
                symbol.enum_name,
                symbol.interface_name,
                symbol.superclass,
                symbol.generic_superclass,
                json.dumps(symbol.generic_arguments),
                json.dumps(symbol.interfaces),
                json.dumps(symbol.annotations),
                json.dumps(symbol.methods),
                json.dumps(symbol.constructors),
                json.dumps(symbol.imports),
                json.dumps(symbol.fields),
                json.dumps(symbol.constants),
                json.dumps(symbol.overridden_methods),
                symbol.field_type,
                json.dumps(symbol.field_annotations),
                symbol.method_name,
                symbol.entity_name,
                symbol.layer,
                symbol.table_name,
                symbol.message,
                symbol.validation,
                symbol.line_start,
                symbol.line_end,
                symbol.snippet,
                json.dumps(symbol.tags),
            )
            for symbol in symbols
        ]
        if not rows:
            return 0
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO symbols (
                    file_path, symbol_type, name, file_name, artifact_id, version, source_type, language, package, class_name,
                    enum_name, interface_name, superclass, generic_superclass, generic_arguments, interfaces, annotations, methods, constructors, imports, fields, constants,
                    overridden_methods, field_type, field_annotations, method_name, entity_name,
                    layer, table_name, message, validation, line_start, line_end, snippet, tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def insert_graph_relations(self, relations: Iterable[dict]) -> int:
        rows = [
            (
                relation.get("type", ""),
                relation.get("source", ""),
                relation.get("target", ""),
                relation.get("filePath") or relation.get("file_path"),
                relation.get("methodName") or relation.get("method_name"),
                relation.get("reason", ""),
            )
            for relation in relations
            if relation.get("type") and relation.get("source") and relation.get("target")
        ]
        if not rows:
            return 0
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO graph_relations(type, source, target, file_path, method_name, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def graph_relations(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM graph_relations").fetchall()
        return [
            {
                "type": row["type"],
                "source": row["source"],
                "target": row["target"],
                "filePath": row["file_path"],
                "methodName": row["method_name"],
                "reason": row["reason"],
            }
            for row in rows
        ]

    def class_symbols(self, class_name: str) -> list[Evidence]:
        like = class_name
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM symbols
                WHERE class_name = ?
                   OR entity_name = ?
                   OR name = ?
                   OR superclass = ?
                   OR generic_arguments LIKE ?
                ORDER BY symbol_type, file_path, line_start
                """,
                (class_name, class_name, class_name, class_name, f"%{class_name}%"),
            ).fetchall()
        return [self._row_to_evidence(row, "", []) for row in rows]

    def status(self) -> dict:
        with self.connect() as con:
            files = con.execute("SELECT COUNT(*) AS count FROM files").fetchone()["count"]
            symbols = con.execute("SELECT COUNT(*) AS count FROM symbols").fetchone()["count"]
            entities = con.execute(
                "SELECT COUNT(DISTINCT class_name) AS count FROM symbols WHERE entity_name IS NOT NULL OR layer = 'entity'"
            ).fetchone()["count"]
            services = con.execute(
                "SELECT COUNT(DISTINCT class_name) AS count FROM symbols WHERE layer = 'service' OR lower(class_name) LIKE '%service%' OR lower(class_name) LIKE '%activity%'"
            ).fetchone()["count"]
            controllers = con.execute(
                "SELECT COUNT(DISTINCT class_name) AS count FROM symbols WHERE layer = 'controller/action'"
            ).fetchone()["count"]
            by_type = {
                row["symbol_type"]: row["count"]
                for row in con.execute("SELECT symbol_type, COUNT(*) AS count FROM symbols GROUP BY symbol_type")
            }
        return {
            "indexed_files": files,
            "indexed_symbols": symbols,
            "indexed_chunks": symbols,
            "entities": entities,
            "services": services,
            "controllers": controllers,
            "by_type": by_type,
        }

    def list_entities(self) -> list[Evidence]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM symbols
                WHERE symbol_type IN ('class', 'file')
                  AND (entity_name IS NOT NULL OR layer = 'entity' OR lower(package) LIKE '%entity%' OR lower(package) LIKE '%model%')
                ORDER BY class_name, file_path
                """
            ).fetchall()
        return [self._row_to_evidence(row, "", []) for row in rows]

    def list_services(self) -> list[Evidence]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM symbols
                WHERE symbol_type IN ('class', 'file')
                  AND (layer IN ('service', 'controller/action', 'dao/repository')
                       OR lower(class_name) LIKE '%service%'
                       OR lower(class_name) LIKE '%activity%'
                       OR lower(class_name) LIKE '%repository%'
                       OR lower(class_name) LIKE '%dao%')
                ORDER BY layer, class_name, file_path
                """
            ).fetchall()
        return [self._row_to_evidence(row, "", []) for row in rows]

    def search_text(self, query: str, limit: int = 20) -> list[Evidence]:
        like = f"%{query}%"
        terms = [term.lower() for term in query.split() if len(term) >= 2]
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM symbols
                WHERE lower(name) LIKE lower(?)
                   OR lower(file_path) LIKE lower(?)
                   OR lower(file_name) LIKE lower(?)
                   OR lower(package) LIKE lower(?)
                   OR lower(artifact_id) LIKE lower(?)
                   OR lower(version) LIKE lower(?)
                   OR lower(source_type) LIKE lower(?)
                   OR lower(class_name) LIKE lower(?)
                   OR lower(enum_name) LIKE lower(?)
                   OR lower(interface_name) LIKE lower(?)
                   OR lower(superclass) LIKE lower(?)
                   OR lower(generic_superclass) LIKE lower(?)
                   OR lower(generic_arguments) LIKE lower(?)
                   OR lower(interfaces) LIKE lower(?)
                   OR lower(annotations) LIKE lower(?)
                   OR lower(methods) LIKE lower(?)
                   OR lower(constructors) LIKE lower(?)
                   OR lower(imports) LIKE lower(?)
                   OR lower(fields) LIKE lower(?)
                   OR lower(constants) LIKE lower(?)
                   OR lower(overridden_methods) LIKE lower(?)
                   OR lower(method_name) LIKE lower(?)
                   OR lower(entity_name) LIKE lower(?)
                   OR lower(layer) LIKE lower(?)
                   OR lower(table_name) LIKE lower(?)
                   OR lower(message) LIKE lower(?)
                   OR lower(validation) LIKE lower(?)
                   OR lower(snippet) LIKE lower(?)
                LIMIT ?
                """,
                (
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    like,
                    limit * 4,
                ),
            ).fetchall()
        evidences = [self._row_to_evidence(row, query, terms) for row in rows]
        evidences.sort(key=lambda item: item.score, reverse=True)
        return evidences[:limit]

    def symbol_candidates(self, query: str, limit: int = 1000) -> list[Evidence]:
        terms = [term for term in query.replace("/", " ").replace("\\", " ").split() if term]
        like_terms = [f"%{term}%" for term in terms] or [f"%{query}%"]
        clauses: list[str] = []
        params: list[str | int] = []
        for like in like_terms:
            clauses.append(
                """
                lower(name) LIKE lower(?)
                OR lower(file_path) LIKE lower(?)
                OR lower(file_name) LIKE lower(?)
                OR lower(package) LIKE lower(?)
                OR lower(class_name) LIKE lower(?)
                OR lower(enum_name) LIKE lower(?)
                OR lower(interface_name) LIKE lower(?)
                OR lower(method_name) LIKE lower(?)
                OR lower(entity_name) LIKE lower(?)
                OR lower(table_name) LIKE lower(?)
                OR lower(methods) LIKE lower(?)
                OR lower(constructors) LIKE lower(?)
                OR lower(imports) LIKE lower(?)
                OR lower(fields) LIKE lower(?)
                OR lower(constants) LIKE lower(?)
                OR lower(generic_superclass) LIKE lower(?)
                OR lower(generic_arguments) LIKE lower(?)
                OR lower(overridden_methods) LIKE lower(?)
                """
            )
            params.extend([like] * 18)
        where = " OR ".join(f"({clause})" for clause in clauses)
        params.append(limit)
        with self.connect() as con:
            rows = con.execute(f"SELECT * FROM symbols WHERE {where} LIMIT ?", params).fetchall()
        return [self._row_to_evidence(row, query, []) for row in rows]

    def all_snippets(self, limit: int = 10000) -> list[Evidence]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM symbols LIMIT ?", (limit,)).fetchall()
        return [self._row_to_evidence(row, "", []) for row in rows]

    def get_settings(self) -> dict[str, str]:
        with self.connect() as con:
            rows = con.execute("SELECT key, value FROM app_settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_settings(self, values: dict[str, str]) -> None:
        with self.connect() as con:
            con.executemany(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                list(values.items()),
            )

    def _row_to_evidence(self, row: sqlite3.Row, query: str, terms: list[str]) -> Evidence:
        haystack = " ".join(
            str(row[key] or "")
            for key in (
                "name",
                "file_path",
                "file_name",
                "artifact_id",
                "version",
                "source_type",
                "language",
                "package",
                "class_name",
                "enum_name",
                "interface_name",
                "superclass",
                "generic_superclass",
                "generic_arguments",
                "interfaces",
                "annotations",
                "methods",
                "constructors",
                "imports",
                "fields",
                "constants",
                "overridden_methods",
                "method_name",
                "table_name",
                "message",
                "validation",
                "snippet",
            )
        ).lower()
        score = 0.0
        if query and query.lower() in haystack:
            score += 5
        score += sum(1 for term in terms if term in haystack)
        symbol_boost = {"class": 1.5, "method": 1.3, "table": 1.2, "message": 1.2, "validation": 1.2}.get(row["symbol_type"], 1)
        score *= symbol_boost
        return Evidence(
            file_path=row["file_path"],
            filePath=row["file_path"],
            fileName=row["file_name"] or Path(row["file_path"]).name,
            artifact_id=row["artifact_id"],
            version=row["version"],
            source_type=row["source_type"],
            language=row["language"],
            package=row["package"],
            class_name=row["class_name"],
            superclass=row["superclass"],
            genericSuperclass=row["generic_superclass"],
            genericArguments=json.loads(row["generic_arguments"] or "[]"),
            interfaces=json.loads(row["interfaces"] or "[]"),
            overriddenMethods=json.loads(row["overridden_methods"] or "[]"),
            attributeType=row["field_type"],
            attributeAnnotations=json.loads(row["field_annotations"] or "[]"),
            method_name=row["method_name"],
            entity_name=row["entity_name"],
            layer=row["layer"],
            table_name=row["table_name"],
            message=row["message"],
            validation=row["validation"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            snippet=row["snippet"],
            tags=json.loads(row["tags"] or "[]"),
            score=score,
            finalScore=score,
            textScore=score,
            symbolType=row["symbol_type"],
            matchedSymbol=row["name"],
        )

    def _ensure_symbol_column(self, con: sqlite3.Connection, column: str, definition: str) -> None:
        existing = {row["name"] for row in con.execute("PRAGMA table_info(symbols)").fetchall()}
        if column not in existing:
            con.execute(f"ALTER TABLE symbols ADD COLUMN {column} {definition}")
