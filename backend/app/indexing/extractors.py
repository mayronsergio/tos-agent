from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_EXTENSIONS = {
    ".java",
    ".xml",
    ".pom",
    ".properties",
    ".sql",
    ".jsp",
    ".jspx",
    ".xhtml",
    ".html",
    ".htm",
    ".yml",
    ".yaml",
    ".conf",
    ".cfg",
}


@dataclass
class CodeSymbol:
    file_path: str
    symbol_type: str
    name: str
    file_name: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    source_type: str | None = None
    language: str | None = None
    package: str | None = None
    class_name: str | None = None
    enum_name: str | None = None
    interface_name: str | None = None
    superclass: str | None = None
    generic_superclass: str | None = None
    generic_arguments: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    constructors: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    overridden_methods: list[str] = field(default_factory=list)
    field_type: str | None = None
    field_annotations: list[str] = field(default_factory=list)
    method_name: str | None = None
    entity_name: str | None = None
    layer: str | None = None
    table_name: str | None = None
    message: str | None = None
    validation: str | None = None
    line_start: int = 1
    line_end: int = 1
    snippet: str = ""
    tags: list[str] = field(default_factory=list)


PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(
    r"\b(class|interface|enum)\s+([A-Z]\w*)"
    r"(?:\s+extends\s+([\w.]+(?:\s*<[^>{}]+>)?))?"
    r"(?:\s+implements\s+([\w.,\s<>]+))?",
    re.MULTILINE,
)
METHOD_RE = re.compile(
    r"^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?[\w<>\[\], ?]+\s+(\w+)\s*\([^;{}]*\)\s*(?:throws\s+[\w., ]+)?\{",
    re.MULTILINE,
)
FIELD_RE = re.compile(
    r"^\s*((?:@\w+(?:\([^)]*\))?\s*)*)(?:public|protected|private)?\s*(?:(static)\s+)?(?:(final)\s+)?([\w<>\[\], ?]+)\s+([A-Za-z_]\w*)\s*(?:=\s*[^;]+)?;",
    re.MULTILINE,
)
OVERRIDE_METHOD_RE = re.compile(
    r"@Override\s+(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?[\w<>\[\], ?]+\s+(\w+)\s*\(",
    re.MULTILINE,
)
ANNOTATION_RE = re.compile(r"@(\w+)(?:\((.*?)\))?", re.DOTALL)
TABLE_RE = re.compile(
    r"(?:@Table\s*\(\s*name\s*=\s*\"([^\"]+)\"|"
    r"\b(?:from|join|update|into|delete\s+from)\s+([A-Za-z_][\w.$]*))",
    re.IGNORECASE,
)
MESSAGE_RE = re.compile(r"\"([^\"]*(?:erro|error|invalid|inval|obrigat|required|falha|fail|nao|não)[^\"]*)\"", re.IGNORECASE)
VALIDATION_RE = re.compile(r"@(NotNull|NotBlank|NotEmpty|Size|Min|Max|Pattern|Email|Valid)\b|\.addError\(|throw\s+new\s+\w*Exception", re.IGNORECASE)
ENTITY_RE = re.compile(r"@Entity\b|@Table\b")


def is_supported(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def snippet_around(lines: list[str], line: int, radius: int = 4) -> tuple[int, int, str]:
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    snippet = "\n".join(lines[start - 1 : end])
    return start, end, snippet[:4000]


def detect_layer(class_name: str | None, annotations: list[str], file_path: str) -> str | None:
    text = " ".join([class_name or "", file_path, *annotations]).lower()
    if any(item in text for item in ("controller", "action", "restcontroller", "managedbean")):
        return "controller/action"
    if "service" in text:
        return "service"
    if any(item in text for item in ("repository", "dao", "mapper")):
        return "dao/repository"
    if "entity" in text:
        return "entity"
    return None


def detect_language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".java":
        return "java"
    if suffix == ".sql":
        return "sql"
    if suffix in {".jsp", ".jspx", ".xhtml", ".html", ".htm"}:
        return "web"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    if suffix == ".properties":
        return "properties"
    if suffix in {".xml", ".pom"}:
        return "xml"
    return suffix.lstrip(".") or "text"


def extract_symbols(path: Path, root: Path, context: dict | None = None) -> list[CodeSymbol]:
    text = read_text(path)
    lines = text.splitlines() or [""]
    rel_path = str(path.relative_to(root)).replace("\\", "/")
    file_name = path.name
    context = context or {}
    artifact_id = context.get("artifact_id")
    version = context.get("version")
    source_type = context.get("source_type")
    language = context.get("language") or detect_language(path)
    package = (PACKAGE_RE.search(text) or [None, None])[1]
    imports = [match.group(1) for match in IMPORT_RE.finditer(text)]
    annotations = [match.group(1) for match in ANNOTATION_RE.finditer(text)]
    symbols: list[CodeSymbol] = []

    class_matches = list(CLASS_RE.finditer(text))
    primary_class = class_matches[0] if class_matches else None
    class_name = primary_class.group(2) if primary_class else None
    primary_kind = primary_class.group(1) if primary_class else None
    superclass = primary_class.group(3) if primary_class else None
    generic_superclass = superclass if superclass and "<" in superclass else None
    superclass_name = _raw_type_name(superclass)
    generic_arguments = _generic_arguments(generic_superclass)
    implemented_interfaces = _split_interfaces(primary_class.group(4) if primary_class else None)
    method_names = [match.group(1) for match in METHOD_RE.finditer(text)]
    overridden_methods = [match.group(1) for match in OVERRIDE_METHOD_RE.finditer(text)]
    field_matches = list(FIELD_RE.finditer(text))
    field_names = [match.group(5) for match in field_matches]
    constant_names = [match.group(5) for match in field_matches if match.group(2) and match.group(3)]
    layer = detect_layer(class_name, annotations, rel_path)

    file_tags = [path.suffix.lower().lstrip(".")]
    if layer:
        file_tags.append(layer)
    if ENTITY_RE.search(text):
        file_tags.append("entity")

    symbols.append(
        CodeSymbol(
            file_path=rel_path,
            symbol_type="file",
            name=rel_path,
            file_name=file_name,
            artifact_id=artifact_id,
            version=version,
            source_type=source_type,
            language=language,
            package=package,
            class_name=class_name,
            enum_name=class_name if primary_kind == "enum" else None,
            interface_name=class_name if primary_kind == "interface" else None,
            superclass=superclass_name,
            generic_superclass=generic_superclass,
            generic_arguments=generic_arguments,
            interfaces=implemented_interfaces,
            annotations=annotations,
            methods=method_names,
            imports=imports,
            fields=field_names,
            constants=constant_names,
            overridden_methods=overridden_methods,
            entity_name=class_name if ENTITY_RE.search(text) else None,
            layer=layer,
            line_start=1,
            line_end=min(len(lines), 80),
            snippet="\n".join(lines[:80])[:4000],
            tags=file_tags,
        )
    )

    for match in class_matches:
        line = line_for_offset(text, match.start())
        start, end, snippet = snippet_around(lines, line)
        current_kind = match.group(1)
        current_class = match.group(2)
        current_symbol_type = {"class": "class", "interface": "interface", "enum": "enum"}[current_kind]
        current_layer = detect_layer(current_class, annotations, rel_path)
        symbols.append(
            CodeSymbol(
                file_path=rel_path,
                symbol_type=current_symbol_type,
                name=current_class,
                file_name=file_name,
                artifact_id=artifact_id,
                version=version,
                source_type=source_type,
                language=language,
                package=package,
                class_name=current_class if current_kind == "class" else None,
                enum_name=current_class if current_kind == "enum" else None,
                interface_name=current_class if current_kind == "interface" else None,
                superclass=_raw_type_name(match.group(3)),
                generic_superclass=match.group(3) if match.group(3) and "<" in match.group(3) else None,
                generic_arguments=_generic_arguments(match.group(3)),
                interfaces=_split_interfaces(match.group(4)),
                annotations=annotations,
                methods=method_names,
                imports=imports,
                fields=field_names,
                constants=constant_names,
                overridden_methods=overridden_methods,
                entity_name=current_class if ENTITY_RE.search(text) else None,
                layer=current_layer,
                line_start=start,
                line_end=end,
                snippet=snippet,
                tags=[current_symbol_type] + ([current_layer] if current_layer else []),
            )
        )

    for match in METHOD_RE.finditer(text):
        method = match.group(1)
        if method in {"if", "for", "while", "switch", "catch", "return", "new"}:
            continue
        line = line_for_offset(text, match.start())
        start, end, snippet = snippet_around(lines, line, radius=8)
        symbols.append(
            CodeSymbol(
                file_path=rel_path,
                symbol_type="method",
                name=method,
                file_name=file_name,
                artifact_id=artifact_id,
                version=version,
                source_type=source_type,
                language=language,
                package=package,
                class_name=class_name,
                enum_name=class_name if primary_kind == "enum" else None,
                interface_name=class_name if primary_kind == "interface" else None,
                superclass=superclass_name,
                generic_superclass=generic_superclass,
                generic_arguments=generic_arguments,
                interfaces=implemented_interfaces,
                annotations=annotations,
                methods=method_names,
                imports=imports,
                fields=field_names,
                constants=constant_names,
                overridden_methods=overridden_methods,
                method_name=method,
                entity_name=class_name if ENTITY_RE.search(text) else None,
                layer=layer,
                line_start=start,
                line_end=end,
                snippet=snippet,
                tags=["method"] + ([layer] if layer else []),
            )
        )

    for match in field_matches:
        field_annotations = [ann.group(1) for ann in ANNOTATION_RE.finditer(match.group(1) or "")]
        field_type = " ".join((match.group(4) or "").split())
        field_name = match.group(5)
        is_constant = bool(match.group(2) and match.group(3))
        line = line_for_offset(text, match.start())
        start, end, snippet = snippet_around(lines, line, radius=3)
        symbols.append(
            CodeSymbol(
                file_path=rel_path,
                symbol_type="constant" if is_constant else "field",
                name=field_name,
                file_name=file_name,
                artifact_id=artifact_id,
                version=version,
                source_type=source_type,
                language=language,
                package=package,
                class_name=class_name,
                enum_name=class_name if primary_kind == "enum" else None,
                interface_name=class_name if primary_kind == "interface" else None,
                superclass=superclass_name,
                generic_superclass=generic_superclass,
                generic_arguments=generic_arguments,
                interfaces=implemented_interfaces,
                annotations=annotations,
                methods=method_names,
                imports=imports,
                fields=field_names,
                constants=constant_names,
                overridden_methods=overridden_methods,
                field_type=field_type,
                field_annotations=field_annotations,
                entity_name=class_name if ENTITY_RE.search(text) else None,
                layer=layer,
                line_start=start,
                line_end=end,
                snippet=snippet,
                tags=["constant" if is_constant else "field"] + ([layer] if layer else []),
            )
        )

    for match in TABLE_RE.finditer(text):
        table = next(group for group in match.groups() if group)
        line = line_for_offset(text, match.start())
        start, end, snippet = snippet_around(lines, line, radius=5)
        symbols.append(
            CodeSymbol(
                file_path=rel_path,
                symbol_type="table",
                name=table,
                file_name=file_name,
                artifact_id=artifact_id,
                version=version,
                source_type=source_type,
                language=language,
                package=package,
                class_name=class_name,
                enum_name=class_name if primary_kind == "enum" else None,
                interface_name=class_name if primary_kind == "interface" else None,
                superclass=superclass_name,
                generic_superclass=generic_superclass,
                generic_arguments=generic_arguments,
                interfaces=implemented_interfaces,
                annotations=annotations,
                methods=method_names,
                imports=imports,
                fields=field_names,
                constants=constant_names,
                overridden_methods=overridden_methods,
                table_name=table,
                layer=layer,
                line_start=start,
                line_end=end,
                snippet=snippet,
                tags=["table"],
            )
        )

    for match in MESSAGE_RE.finditer(text):
        message = match.group(1)
        line = line_for_offset(text, match.start())
        start, end, snippet = snippet_around(lines, line, radius=4)
        symbols.append(
            CodeSymbol(
                file_path=rel_path,
                symbol_type="message",
                name=message[:180],
                file_name=file_name,
                artifact_id=artifact_id,
                version=version,
                source_type=source_type,
                language=language,
                package=package,
                class_name=class_name,
                enum_name=class_name if primary_kind == "enum" else None,
                interface_name=class_name if primary_kind == "interface" else None,
                superclass=superclass_name,
                generic_superclass=generic_superclass,
                generic_arguments=generic_arguments,
                interfaces=implemented_interfaces,
                annotations=annotations,
                methods=method_names,
                imports=imports,
                fields=field_names,
                constants=constant_names,
                overridden_methods=overridden_methods,
                message=message,
                layer=layer,
                line_start=start,
                line_end=end,
                snippet=snippet,
                tags=["message", "error"],
            )
        )

    for match in VALIDATION_RE.finditer(text):
        validation = match.group(0)
        line = line_for_offset(text, match.start())
        start, end, snippet = snippet_around(lines, line, radius=5)
        symbols.append(
            CodeSymbol(
                file_path=rel_path,
                symbol_type="validation",
                name=validation,
                file_name=file_name,
                artifact_id=artifact_id,
                version=version,
                source_type=source_type,
                language=language,
                package=package,
                class_name=class_name,
                enum_name=class_name if primary_kind == "enum" else None,
                interface_name=class_name if primary_kind == "interface" else None,
                superclass=superclass_name,
                generic_superclass=generic_superclass,
                generic_arguments=generic_arguments,
                interfaces=implemented_interfaces,
                annotations=annotations,
                methods=method_names,
                imports=imports,
                fields=field_names,
                constants=constant_names,
                overridden_methods=overridden_methods,
                validation=validation,
                layer=layer,
                line_start=start,
                line_end=end,
                snippet=snippet,
                tags=["validation"],
            )
        )

    return symbols


def _split_interfaces(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().split("<", 1)[0] for item in value.split(",") if item.strip()]


def _raw_type_name(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().split("<", 1)[0].split(".")[-1]


def _generic_arguments(value: str | None) -> list[str]:
    if not value or "<" not in value or ">" not in value:
        return []
    inner = value[value.find("<") + 1 : value.rfind(">")]
    return [_raw_type_name(item) or item.strip() for item in inner.split(",") if item.strip()]
