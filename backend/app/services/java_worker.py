from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.indexing.extractors import CodeSymbol


@dataclass
class JavaAnalysisResult:
    symbols: list[CodeSymbol] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class JavaAnalysisWorker:
    def __init__(self, settings):
        self.settings = settings
        self.log = logging.getLogger("code_support_agent.java_worker")

    def analyze(self, source_dir: Path, root_dir: Path, context: dict | None = None) -> JavaAnalysisResult | None:
        command = self._command()
        if not command:
            return None
        context = context or {}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as temp:
            output_path = Path(temp.name)
        try:
            args = [
                *command,
                "--source",
                str(source_dir.resolve()),
                "--root",
                str(root_dir.resolve()),
                "--output",
                str(output_path.resolve()),
                "--artifactId",
                str(context.get("artifact_id") or ""),
                "--version",
                str(context.get("version") or ""),
                "--sourceType",
                str(context.get("source_type") or "sources"),
            ]
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=getattr(self.settings, "java_analysis_worker_timeout_seconds", 120),
            )
            if completed.returncode != 0:
                self.log.warning("Java analysis worker failed: %s", completed.stderr.strip() or completed.stdout.strip())
                return None
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            return JavaAnalysisResult(
                symbols=[self._symbol(item) for item in payload.get("symbols", [])],
                relations=list(payload.get("relations", [])),
                metrics=dict(payload.get("metrics", {})),
                raw=payload,
            )
        except Exception as exc:
            self.log.warning("Java analysis worker unavailable, falling back to Python analyzer: %s", exc)
            return None
        finally:
            output_path.unlink(missing_ok=True)

    def _command(self) -> list[str] | None:
        configured = getattr(self.settings, "java_analysis_worker_command", None)
        if configured:
            return shlex.split(configured, posix=os.name != "nt")
        for base in [Path.cwd(), *Path.cwd().parents]:
            jar_path = base / "code-analysis-worker" / "target" / "code-analysis-worker.jar"
            if jar_path.is_file():
                return ["java", "-jar", str(jar_path)]
        return None

    def _symbol(self, item: dict) -> CodeSymbol:
        return CodeSymbol(
            file_path=item.get("filePath") or item.get("file_path") or "",
            file_name=item.get("fileName") or item.get("file_name"),
            symbol_type=item.get("symbolType") or item.get("symbol_type") or "class",
            name=item.get("name") or item.get("className") or item.get("methodName") or item.get("fieldName") or "",
            artifact_id=item.get("artifactId") or item.get("artifact_id") or None,
            version=item.get("version") or None,
            source_type=item.get("sourceType") or item.get("source_type") or None,
            language=item.get("language") or "java",
            package=item.get("packageName") or item.get("package") or None,
            class_name=item.get("className") or item.get("class_name") or None,
            enum_name=item.get("enumName") or item.get("enum_name") or None,
            interface_name=item.get("interfaceName") or item.get("interface_name") or None,
            superclass=item.get("superclass") or None,
            generic_superclass=item.get("genericSuperclass") or item.get("generic_superclass") or None,
            generic_arguments=list(item.get("genericArguments") or item.get("generic_arguments") or []),
            interfaces=list(item.get("interfaces") or []),
            annotations=list(item.get("annotations") or []),
            methods=list(item.get("methods") or []),
            constructors=list(item.get("constructors") or []),
            imports=list(item.get("imports") or []),
            fields=list(item.get("fields") or []),
            constants=list(item.get("constants") or []),
            overridden_methods=list(item.get("overriddenMethods") or item.get("overridden_methods") or []),
            field_type=item.get("fieldType") or item.get("field_type") or None,
            field_annotations=list(item.get("fieldAnnotations") or item.get("field_annotations") or []),
            method_name=item.get("methodName") or item.get("method_name") or None,
            entity_name=item.get("entityName") or item.get("entity_name") or None,
            layer=item.get("layer") or None,
            table_name=item.get("tableName") or item.get("table_name") or None,
            message=item.get("message") or None,
            validation=item.get("validation") or None,
            line_start=int(item.get("lineStart") or item.get("line_start") or 1),
            line_end=int(item.get("lineEnd") or item.get("line_end") or item.get("lineStart") or item.get("line_start") or 1),
            snippet=item.get("snippet") or "",
            tags=list(item.get("tags") or []),
        )
