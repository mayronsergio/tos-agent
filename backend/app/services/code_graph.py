from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from app.models.schemas import Evidence, GraphRelation
from app.services.search import normalize_identifier


@dataclass(frozen=True)
class CodeRelation:
    type: str
    source: str
    target: str
    filePath: str | None = None
    methodName: str | None = None
    reason: str = ""


class CodeGraphService:
    """Local dependency graph builder.

    The persisted JSON is intentionally simple so it can be migrated later to
    Neo4j without changing the ingestion pipeline.
    """

    def __init__(self, repository):
        self.repository = repository

    def build(self, output_path: Path | None = None) -> dict:
        evidences = self.repository.all_snippets()
        relations = self.relations_from(evidences)
        graph = {
            "nodes": sorted(
                {
                    self._class_name(item)
                    for item in evidences
                    if self._class_name(item)
                }
            ),
            "relations": [asdict(relation) for relation in relations],
        }
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
        return graph

    def relations_from(self, evidences: list[Evidence]) -> list[CodeRelation]:
        class_names = {self._class_name(item) for item in evidences if self._class_name(item)}
        class_names_norm = {normalize_identifier(name): name for name in class_names}
        relations: set[CodeRelation] = set()

        for item in evidences:
            source = self._class_name(item)
            if not source:
                continue
            if item.superclass:
                relations.add(CodeRelation("CLASS_EXTENDS_CLASS", source, item.superclass, item.file_path, reason="extends declarado"))
            for interface in item.interfaces:
                relations.add(CodeRelation("CLASS_IMPLEMENTS_INTERFACE", source, interface, item.file_path, reason="implements declarado"))
            for annotation in item.attributeAnnotations:
                relations.add(CodeRelation("ANNOTATED_WITH", source, annotation, item.file_path, reason="annotation em atributo"))
            for tag in item.tags:
                if tag.startswith("@"):
                    relations.add(CodeRelation("ANNOTATED_WITH", source, tag.lstrip("@"), item.file_path, reason="annotation detectada"))
            if item.table_name:
                relations.add(CodeRelation("ENTITY_MAPS_TABLE", source, item.table_name, item.file_path, reason="mapeamento @Table ou SQL"))
            if item.genericArguments:
                for argument in item.genericArguments:
                    relations.add(CodeRelation("CLASS_HAS_GENERIC_ARGUMENT", source, argument, item.file_path, reason="tipo parametrizado"))
            if item.attributeType:
                relations.add(CodeRelation("FIELD_HAS_TYPE", source, item.attributeType, item.file_path, reason=f"campo {item.matchedSymbol}"))
            for method in item.overriddenMethods:
                relations.add(CodeRelation("METHOD_OVERRIDES_METHOD", source, method, item.file_path, method, "metodo anotado com @Override"))

            if item.symbolType == "method":
                for called_class in self._class_mentions(item.snippet, class_names_norm):
                    if called_class != source:
                        relations.add(CodeRelation("CLASS_USES_CLASS", source, called_class, item.file_path, item.method_name, "referencia de classe no metodo"))
                for call in re.findall(r"\.([A-Za-z_]\w*)\s*\(", item.snippet):
                    relations.add(CodeRelation("METHOD_CALLS_METHOD", source, call, item.file_path, item.method_name, "chamada por padrao .metodo("))

            layer = (item.layer or "").lower()
            if "controller" in layer:
                for target in self._class_mentions(item.snippet + " " + " ".join(item.genericArguments), class_names_norm):
                    if target != source and self._looks_like(target, ("service", "activity")):
                        relations.add(CodeRelation("CONTROLLER_USES_SERVICE", source, target, item.file_path, item.method_name, "controller referencia service/activity"))
            if "service" in layer or "activity" in normalize_identifier(source):
                for target in self._class_mentions(item.snippet, class_names_norm):
                    if target != source and self._looks_like(target, ("repository", "dao")):
                        relations.add(CodeRelation("SERVICE_USES_REPOSITORY", source, target, item.file_path, item.method_name, "service referencia repository/dao"))

        class_by_name = {self._class_name(item): item for item in evidences if item.symbolType in {"class", "file"} and self._class_name(item)}
        for child_name, child in class_by_name.items():
            parent = class_by_name.get(child.superclass or "")
            if not parent:
                continue
            parent_methods = [
                item.method_name
                for item in evidences
                if item.symbolType == "method" and item.class_name == parent.class_name and item.method_name
            ]
            for method in parent_methods:
                relations.add(CodeRelation("CLASS_INHERITS_METHOD", child_name, method, child.file_path, method, f"metodo herdado de {parent.class_name}"))
            for field in [item for item in evidences if item.symbolType in {"field", "constant"} and item.class_name == parent.class_name]:
                relations.add(CodeRelation("CLASS_INHERITS_FIELD", child_name, field.matchedSymbol or "", child.file_path, reason=f"campo herdado de {parent.class_name}"))

        for relation in self.repository.graph_relations():
            relations.add(
                CodeRelation(
                    relation["type"],
                    relation["source"],
                    relation["target"],
                    relation.get("filePath"),
                    relation.get("methodName"),
                    relation.get("reason", "relacao gerada pelo worker JavaParser"),
                )
            )
        return sorted(relations, key=lambda item: (item.source, item.type, item.target))

    def class_relations(self, class_name: str) -> list[GraphRelation]:
        wanted = normalize_identifier(class_name)
        relations = [
            relation
            for relation in self.relations_from(self.repository.all_snippets())
            if normalize_identifier(relation.source) == wanted or normalize_identifier(relation.target) == wanted
        ]
        return [GraphRelation(**asdict(relation)) for relation in relations]

    def relation_count(self) -> int:
        return len(self.relations_from(self.repository.all_snippets()))

    def _class_name(self, item: Evidence) -> str:
        return item.class_name or item.entity_name or item.matchedSymbol or ""

    def _class_mentions(self, text: str, class_names_norm: dict[str, str]) -> set[str]:
        normalized = normalize_identifier(text)
        return {name for key, name in class_names_norm.items() if key and key in normalized}

    def _looks_like(self, name: str, suffixes: tuple[str, ...]) -> bool:
        normalized = normalize_identifier(name)
        return any(suffix in normalized for suffix in suffixes)
