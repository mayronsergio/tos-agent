from __future__ import annotations

from dataclasses import dataclass, field

from app.models.schemas import ChatEvidence, Evidence
from app.services.search import normalize_identifier, normalize_text, tokenize


@dataclass
class AttributeInfo:
    name: str
    type: str | None
    annotations: list[str]
    origin_class: str


@dataclass
class ClassStructure:
    class_name: str
    source_file: str
    superclass: str | None = None
    generic_superclass: str | None = None
    generic_arguments: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    overridden_methods: list[str] = field(default_factory=list)
    inherited_methods: list[str] = field(default_factory=list)
    superclass_file: str | None = None
    related_entity: str | None = None
    related_service_activity: str | None = None
    own_attributes: list[AttributeInfo] = field(default_factory=list)
    inherited_attributes: list[AttributeInfo] = field(default_factory=list)
    evidence: Evidence | None = None

    def all_attributes(self) -> list[AttributeInfo]:
        return [*self.own_attributes, *self.inherited_attributes]


class HeritageResolver:
    def __init__(self, evidences: list[Evidence]):
        self.evidences = evidences
        self.classes = [item for item in evidences if item.symbolType in {"class", "file"} and (item.class_name or item.matchedSymbol)]
        self.methods = [item for item in evidences if item.symbolType == "method"]
        self.fields = [item for item in evidences if item.symbolType in {"field", "constant"}]

    def find_entity_candidate(self, query: str) -> ClassStructure | None:
        tokens = set(tokenize(query))
        class_candidates = [item for item in self.classes if self._entity_like(item) or self._name_related(item, tokens)]
        if not class_candidates:
            return None
        class_candidates.sort(key=lambda item: self._entity_score(item, tokens), reverse=True)
        return self.resolve_class(class_candidates[0])

    def resolve_class(self, evidence: Evidence | str, visited: set[str] | None = None) -> ClassStructure:
        visited = visited or set()
        class_evidence = self._class_evidence(evidence)
        class_name = self._class_name(class_evidence) if class_evidence else str(evidence)
        if not class_evidence:
            return ClassStructure(class_name=class_name, source_file="")
        if normalize_identifier(class_name) in visited:
            return ClassStructure(class_name=class_name, source_file=class_evidence.file_path, evidence=class_evidence)
        visited.add(normalize_identifier(class_name))

        superclass = class_evidence.superclass
        parent = self.resolve_class(superclass, visited) if superclass else None
        generic_args = class_evidence.genericArguments
        own_methods = {item.method_name for item in self.methods if item.class_name == class_name and item.method_name}
        inherited_methods = sorted({item.method_name for item in self.methods if parent and item.class_name == parent.class_name and item.method_name and item.method_name not in own_methods})

        own_attributes = self.get_entity_attributes(class_name, include_inherited=False).own_attributes
        inherited_attributes = parent.all_attributes() if parent else []
        related_service = next((arg for arg in generic_args if self._looks_like_service(arg)), None)
        related_entity = next((arg for arg in generic_args if not self._looks_like_service(arg)), None)

        return ClassStructure(
            class_name=class_name,
            source_file=class_evidence.file_path,
            superclass=superclass,
            generic_superclass=class_evidence.genericSuperclass,
            generic_arguments=generic_args,
            interfaces=class_evidence.interfaces,
            overridden_methods=class_evidence.overriddenMethods,
            inherited_methods=inherited_methods,
            superclass_file=parent.source_file if parent else None,
            related_entity=related_entity,
            related_service_activity=related_service,
            own_attributes=own_attributes,
            inherited_attributes=inherited_attributes,
            evidence=class_evidence,
        )

    def get_entity_attributes(self, class_name: str, include_inherited: bool = True) -> ClassStructure:
        class_evidence = self._class_evidence(class_name)
        source_file = class_evidence.file_path if class_evidence else ""
        own = [
            AttributeInfo(
                name=item.matchedSymbol or "",
                type=item.attributeType,
                annotations=item.attributeAnnotations,
                origin_class=class_name,
            )
            for item in self.fields
            if normalize_identifier(item.class_name or "") == normalize_identifier(class_name)
        ]
        own = [item for item in own if item.name]
        inherited: list[AttributeInfo] = []
        superclass = class_evidence.superclass if class_evidence else None
        superclass_file = None
        if include_inherited and superclass:
            parent = self.get_entity_attributes(superclass, include_inherited=True)
            inherited = parent.own_attributes + parent.inherited_attributes
            superclass_file = parent.source_file
        return ClassStructure(
            class_name=class_name,
            source_file=source_file,
            superclass=superclass,
            generic_superclass=class_evidence.genericSuperclass if class_evidence else None,
            generic_arguments=class_evidence.genericArguments if class_evidence else [],
            interfaces=class_evidence.interfaces if class_evidence else [],
            overridden_methods=class_evidence.overriddenMethods if class_evidence else [],
            superclass_file=superclass_file,
            own_attributes=own,
            inherited_attributes=inherited,
            evidence=class_evidence,
        )

    def enrich_evidences(self, evidences: list[ChatEvidence]) -> list[ChatEvidence]:
        enriched: list[ChatEvidence] = []
        for evidence in evidences:
            structure = self.resolve_class(evidence.class_name) if evidence.class_name else None
            if structure:
                evidence.superclass = structure.superclass
                evidence.genericSuperclass = structure.generic_superclass
                evidence.genericArguments = structure.generic_arguments
                evidence.interfaces = structure.interfaces
                evidence.overriddenMethods = structure.overridden_methods
                evidence.inheritedMethods = structure.inherited_methods
                evidence.sourceFileOfSuperclass = structure.superclass_file
                evidence.genericClass = (structure.generic_superclass or "").split("<", 1)[0] or None
                evidence.relatedEntity = structure.related_entity
                evidence.relatedServiceActivity = structure.related_service_activity
                if structure.generic_superclass:
                    evidence.relationFromGraph = "CLASS_HAS_GENERIC_ARGUMENT"
                elif structure.superclass:
                    evidence.relationFromGraph = "CLASS_EXTENDS_CLASS"
            enriched.append(evidence)
        return enriched

    def limit_files(self, evidences: list[ChatEvidence], max_files: int = 25) -> list[ChatEvidence]:
        selected: list[ChatEvidence] = []
        seen_files: set[str] = set()
        overflow: list[ChatEvidence] = []
        for evidence in evidences:
            if evidence.file_path not in seen_files and len(seen_files) < max_files:
                selected.append(evidence)
                seen_files.add(evidence.file_path)
            elif evidence.file_path in seen_files:
                overflow.append(evidence)
        return [*selected, *overflow][: max_files]

    def _class_evidence(self, evidence: Evidence | str | None) -> Evidence | None:
        if evidence is None:
            return None
        if isinstance(evidence, Evidence):
            name = self._class_name(evidence)
        else:
            name = evidence
        name_norm = normalize_identifier(name)
        matches = [item for item in self.classes if normalize_identifier(self._class_name(item)) == name_norm]
        if not matches:
            return None
        matches.sort(key=lambda item: (1 if item.symbolType == "class" else 0, item.symbolScore, item.score), reverse=True)
        return matches[0]

    def _class_name(self, evidence: Evidence) -> str:
        return evidence.class_name or evidence.entity_name or evidence.matchedSymbol or evidence.fileName or evidence.file_path

    def _entity_like(self, evidence: Evidence) -> bool:
        text = normalize_text(" ".join([evidence.package or "", evidence.file_path, " ".join(evidence.tags), evidence.snippet]))
        return bool(evidence.entity_name or "@entity" in text or "@table" in text or "entity" in text or ".model" in text)

    def _name_related(self, evidence: Evidence, tokens: set[str]) -> bool:
        if not tokens:
            return False
        name = normalize_identifier(self._class_name(evidence))
        return any(token in name for token in tokens)

    def _entity_score(self, evidence: Evidence, tokens: set[str]) -> float:
        name = normalize_identifier(self._class_name(evidence))
        score = 0.0
        if any(token == name for token in tokens):
            score += 100
        if self._entity_like(evidence):
            score += 80
        if any(token in name for token in tokens):
            score += 50
        if evidence.layer in {"service", "controller/action"}:
            score -= 100
        return score

    def _looks_like_service(self, name: str) -> bool:
        normalized = normalize_text(name)
        return any(token in normalized for token in ("service", "activity", "controller", "dao", "repository"))
