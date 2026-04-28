from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.indexing.extractors import SUPPORTED_EXTENSIONS, extract_symbols
from app.models.schemas import ZipImportResponse
from app.services.maven_version import latest_version, sort_versions
from app.services.code_graph import CodeGraphService
from app.services.java_worker import JavaAnalysisWorker
from app.services.repository import CodeRepository
from app.services.vector_index import VectorIndex


INDEXABLE_EXTENSIONS = SUPPORTED_EXTENSIONS - {".pom"}
ZIP_EXTRACT_EXTENSIONS = INDEXABLE_EXTENSIONS | {".jar", ".class", ".pom"}
ProgressCallback = Callable[[str, str, int, int, int | None], None]


@dataclass
class MavenArtifact:
    artifact_id: str
    version: str
    version_dir: Path
    source_jar: Path | None
    binary_jar: Path | None


class ZipImporter:
    def __init__(self, repository: CodeRepository, vector_index: VectorIndex, settings):
        self.repository = repository
        self.vector_index = vector_index
        self.settings = settings
        self.java_worker = JavaAnalysisWorker(settings)
        self._write_lock = threading.Lock()
        self.log = logging.getLogger("code_support_agent.zip_importer")

    def import_zip(self, uploaded_file, reset: bool = True) -> ZipImportResponse:
        import_id = self.new_import_id()
        filename = Path(uploaded_file.filename or "codebase.zip").name
        temp_dir = self.settings.data_dir / "pending-imports"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{import_id}-{filename}"
        size = self._save_upload(uploaded_file.file, temp_path)
        self._validate_total_size(size)
        try:
            return self.import_zip_path(temp_path, filename, reset=reset, import_id=import_id)
        finally:
            temp_path.unlink(missing_ok=True)

    def new_import_id(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]

    def import_zip_path(
        self,
        source_zip_path: Path,
        filename: str,
        reset: bool = True,
        import_id: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> ZipImportResponse:
        started = time.perf_counter()
        filename = Path(filename or "codebase.zip").name
        if not filename.lower().endswith(".zip"):
            raise ValueError("Envie um arquivo .zip.")

        import_id = import_id or self.new_import_id()
        import_dir = (self.settings.data_dir / "imports" / import_id).resolve()
        raw_dir = import_dir / "raw"
        extracted_dir = import_dir / "extracted"
        decompiled_dir = import_dir / "decompiled"
        raw_dir.mkdir(parents=True, exist_ok=True)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        decompiled_dir.mkdir(parents=True, exist_ok=True)

        zip_path = (raw_dir / filename).resolve()
        self._emit(progress, "saving", "Copiando ZIP para area da importacao.", progress_value=3)
        self.log.info("Import %s: copied upload to %s", import_id, zip_path)
        shutil.copy2(source_zip_path, zip_path)
        size = zip_path.stat().st_size
        self._validate_total_size(size)
        checksum = self._checksum(zip_path)
        self._emit(progress, "extracting", "Extraindo arquivos relevantes do ZIP.", progress_value=8)
        self.log.info("Import %s: extracting ZIP %s", import_id, zip_path.name)
        extracted_files, extraction_errors = self._extract_zip(zip_path, extracted_dir, progress=progress)

        if not self._has_source_or_bytecode(extracted_dir):
            raise ValueError("Nenhum código fonte ou bytecode encontrado no ZIP")

        if reset:
            self._emit(progress, "resetting", "Recriando indice antes da importacao.", progress_value=25)
            self.log.info("Import %s: resetting repository before import", import_id)
            self.repository.reset()

        metadata_errors: list[str] = list(extraction_errors)
        artifacts_found: list[dict] = []
        artifacts_processed: list[dict] = []
        artifacts_skipped: list[dict] = []
        decompilation_errors: list[str] = []
        indexed_files = 0
        indexed_symbols = 0
        decompiled_any = False
        analysis_metrics = self._empty_analysis_metrics()

        maven_root = self._find_maven_root(extracted_dir)
        if maven_root:
            selections, skipped = self._select_latest_artifacts(maven_root)
            artifacts_skipped.extend(skipped)
            artifacts_found.extend(
                {
                    "artifactId": item.artifact_id,
                    "version": item.version,
                    "sourceJar": item.source_jar.name if item.source_jar else None,
                    "binaryJar": item.binary_jar.name if item.binary_jar else None,
                }
                for item in selections
            )
            total_artifacts = len(selections)
            for index, result in enumerate(self._process_artifacts_parallel(selections, import_dir, extracted_dir, decompiled_dir), start=1):
                metadata = result["metadata"]
                self._emit(
                    progress,
                    "processing",
                    f"Processado artifact {metadata.get('artifactId')}:{metadata.get('version')}.",
                    index,
                    total_artifacts,
                    30 + int((index / max(total_artifacts, 1)) * 45),
                )
                artifacts_processed.append(result["metadata"])
                metadata_errors.extend(result["errors"])
                decompilation_errors.extend(result["decompilationErrors"])
                self._merge_analysis_metrics(analysis_metrics, result.get("analysisMetrics", {}))
                indexed_files += result["indexedFiles"]
                indexed_symbols += result["indexedSymbols"]
                decompiled_any = decompiled_any or result["decompiled"]
        else:
            loose_jars = self._find_loose_jars(extracted_dir)
            if loose_jars and not any(path.suffix.lower() == ".java" for path in extracted_dir.rglob("*") if path.is_file()):
                artifacts: list[MavenArtifact] = []
                for jar_path in loose_jars:
                    is_sources = jar_path.name.endswith("-sources.jar")
                    artifact_id = jar_path.name.removesuffix("-sources.jar") if is_sources else jar_path.stem
                    artifact = MavenArtifact(artifact_id, "unknown", jar_path.parent, jar_path if is_sources else None, None if is_sources else jar_path)
                    artifacts.append(artifact)
                    artifacts_found.append({"artifactId": artifact.artifact_id, "version": artifact.version, "binaryJar": jar_path.name})
                for index, result in enumerate(self._process_artifacts_parallel(artifacts, import_dir, extracted_dir, decompiled_dir), start=1):
                    self._emit(
                        progress,
                        "processing",
                        f"Processado JAR {result['metadata'].get('artifactId')}.",
                        index,
                        len(artifacts),
                        30 + int((index / max(len(artifacts), 1)) * 45),
                    )
                    artifacts_processed.append(result["metadata"])
                    metadata_errors.extend(result["errors"])
                    decompilation_errors.extend(result["decompilationErrors"])
                    self._merge_analysis_metrics(analysis_metrics, result.get("analysisMetrics", {}))
                    indexed_files += result["indexedFiles"]
                    indexed_symbols += result["indexedSymbols"]
                    decompiled_any = decompiled_any or result["decompiled"]
            else:
                self._emit(progress, "indexing", "Indexando arvore de codigo fonte do ZIP.", progress_value=55)
                result = self._index_plain_source_tree(extracted_dir, import_dir)
                self._merge_analysis_metrics(analysis_metrics, result.get("analysisMetrics", {}))
                indexed_files += result["indexedFiles"]
                indexed_symbols += result["indexedSymbols"]
                artifacts_found.append({"artifactId": None, "version": None, "sourceType": "plain-zip"})
                artifacts_processed.append(result["metadata"])

        processing_seconds = round(time.perf_counter() - started, 3)
        metadata = {
            "importId": import_id,
            "importedAt": datetime.now(timezone.utc).isoformat(),
            "originalFilename": filename,
            "checksum": checksum,
            "sizeBytes": size,
            "rawPath": str(zip_path),
            "extractedPath": str(extracted_dir),
            "decompiledPath": str(decompiled_dir),
            "filesExtracted": extracted_files,
            "artifactsFound": artifacts_found,
            "artifactsProcessed": artifacts_processed,
            "artifactsSkipped": artifacts_skipped,
            "indexedUsefulFiles": indexed_files,
            "indexedSymbols": indexed_symbols,
            "processingSeconds": processing_seconds,
            "decompilationErrors": decompilation_errors,
            "errors": metadata_errors,
            "indexStatus": "indexed_with_errors" if metadata_errors else "indexed",
            "analysis": analysis_metrics,
        }
        metadata_path = import_dir / "index-metadata.json"
        graph_path = import_dir / "code-graph.json"
        self._emit(progress, "graph", "Gerando grafo local de dependencias.", progress_value=88)
        graph = CodeGraphService(self.repository).build(graph_path)
        metadata["codeGraphPath"] = str(graph_path)
        metadata["graphRelations"] = len(graph["relations"])
        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        self._emit(progress, "vector-index", "Reconstruindo indice vetorial.", progress_value=92)
        self.log.info("Import %s: rebuilding vector index", import_id)
        self.vector_index.rebuild(self.repository.all_snippets())

        return ZipImportResponse(
            importId=import_id,
            originalFilename=filename,
            metadataPath=str(metadata_path),
            processedArtifacts=len(artifacts_processed),
            skippedArtifacts=len(artifacts_skipped),
            decompiled=decompiled_any,
            importedFiles=indexed_files,
            indexedSymbols=indexed_symbols,
            skippedFiles=len(artifacts_skipped),
            extractedFiles=len(extracted_files),
            errors=metadata_errors,
            message="Importacao ZIP concluida.",
        )

    def _process_artifacts_parallel(
        self,
        artifacts: list[MavenArtifact],
        import_dir: Path,
        extracted_dir: Path,
        decompiled_dir: Path,
    ) -> list[dict]:
        if not artifacts:
            return []
        workers = min(4, max(1, len(artifacts)))
        if workers == 1:
            return [self._process_maven_artifact(artifact, import_dir, extracted_dir, decompiled_dir) for artifact in artifacts]
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="artifact-import") as executor:
            futures = [executor.submit(self._process_maven_artifact, artifact, import_dir, extracted_dir, decompiled_dir) for artifact in artifacts]
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def _process_maven_artifact(self, artifact: MavenArtifact, import_dir: Path, extracted_dir: Path, decompiled_dir: Path) -> dict:
        errors: list[str] = []
        decompilation_errors: list[str] = []
        indexed_files = 0
        indexed_symbols = 0
        analysis_metrics = self._empty_analysis_metrics()
        decompiled = False
        source_type = "sources"
        work_dir = import_dir / "work" / f"{artifact.artifact_id}-{artifact.version}"

        if artifact.source_jar:
            self._extract_nested_jar(artifact.source_jar, work_dir, allow_classes=False)
            source_type = "sources"
        elif artifact.binary_jar:
            source_type = "decompiled"
            try:
                decompiled_output = decompiled_dir / f"{artifact.artifact_id}-{artifact.version}"
                self._decompile_with_cfr(artifact.binary_jar, decompiled_output)
                self._copy_tree(decompiled_output, work_dir)
                decompiled = True
            except Exception as exc:
                message = f"{artifact.artifact_id}:{artifact.version}: {exc}"
                errors.append(message)
                decompilation_errors.append(message)

        context = {
            "artifact_id": artifact.artifact_id,
            "version": artifact.version,
            "source_type": source_type,
        }
        worker_result = self.java_worker.analyze(work_dir, import_dir, context=context)
        if worker_result and worker_result.symbols:
            self._merge_analysis_metrics(analysis_metrics, self._worker_metrics(worker_result))
            source_files = sorted({symbol.file_path for symbol in worker_result.symbols if symbol.file_path})
            with self._write_lock:
                for rel in source_files:
                    self.repository.upsert_file(rel)
                indexed_symbols += self.repository.insert_symbols(worker_result.symbols)
                self.repository.insert_graph_relations(worker_result.relations)
            indexed_files += len(source_files)
            extra = self._index_non_java_files(work_dir, import_dir, context)
            indexed_files += extra["indexedFiles"]
            indexed_symbols += extra["indexedSymbols"]
        else:
            analysis_metrics["workerFailures"] += 1
            for path in work_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                    continue
                symbols = extract_symbols(path, import_dir, context=context)
                rel = str(path.relative_to(import_dir)).replace("\\", "/")
                with self._write_lock:
                    self.repository.upsert_file(rel)
                    indexed_symbols += self.repository.insert_symbols(symbols)
                indexed_files += 1
                if path.suffix.lower() == ".java":
                    analysis_metrics["fallbackPythonFiles"] += 1

        return {
            "indexedFiles": indexed_files,
            "indexedSymbols": indexed_symbols,
            "decompiled": decompiled,
            "errors": errors,
            "decompilationErrors": decompilation_errors,
            "metadata": {
                "artifactId": artifact.artifact_id,
                "version": artifact.version,
                "sourceType": source_type,
                "indexedUsefulFiles": indexed_files,
                "indexedSymbols": indexed_symbols,
                "decompiled": decompiled,
                "errors": errors,
                "analysis": analysis_metrics,
            },
            "analysisMetrics": analysis_metrics,
        }

    def _index_plain_source_tree(self, extracted_dir: Path, import_dir: Path) -> dict:
        indexed_files = 0
        indexed_symbols = 0
        analysis_metrics = self._empty_analysis_metrics()
        context = {"source_type": "sources"}
        worker_result = self.java_worker.analyze(extracted_dir, import_dir, context=context)
        if worker_result and worker_result.symbols:
            self._merge_analysis_metrics(analysis_metrics, self._worker_metrics(worker_result))
            source_files = sorted({symbol.file_path for symbol in worker_result.symbols if symbol.file_path})
            with self._write_lock:
                for rel in source_files:
                    self.repository.upsert_file(rel)
                indexed_symbols += self.repository.insert_symbols(worker_result.symbols)
                self.repository.insert_graph_relations(worker_result.relations)
            indexed_files = len(source_files)
            extra = self._index_non_java_files(extracted_dir, import_dir, context)
            indexed_files += extra["indexedFiles"]
            indexed_symbols += extra["indexedSymbols"]
        else:
            analysis_metrics["workerFailures"] += 1
            for path in extracted_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                    continue
                symbols = extract_symbols(path, import_dir, context=context)
                rel = str(path.relative_to(import_dir)).replace("\\", "/")
                with self._write_lock:
                    self.repository.upsert_file(rel)
                    indexed_symbols += self.repository.insert_symbols(symbols)
                indexed_files += 1
                if path.suffix.lower() == ".java":
                    analysis_metrics["fallbackPythonFiles"] += 1
        return {
            "indexedFiles": indexed_files,
            "indexedSymbols": indexed_symbols,
            "analysisMetrics": analysis_metrics,
            "metadata": {
                "artifactId": None,
                "version": None,
                "sourceType": "sources",
                "indexedUsefulFiles": indexed_files,
                "indexedSymbols": indexed_symbols,
                "analysis": analysis_metrics,
            },
        }

    def _index_non_java_files(self, source_dir: Path, import_dir: Path, context: dict) -> dict:
        indexed_files = 0
        indexed_symbols = 0
        for path in source_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in INDEXABLE_EXTENSIONS or path.suffix.lower() == ".java":
                continue
            symbols = extract_symbols(path, import_dir, context=context)
            rel = str(path.relative_to(import_dir)).replace("\\", "/")
            with self._write_lock:
                self.repository.upsert_file(rel)
                indexed_symbols += self.repository.insert_symbols(symbols)
            indexed_files += 1
        return {"indexedFiles": indexed_files, "indexedSymbols": indexed_symbols}

    def _empty_analysis_metrics(self) -> dict[str, int]:
        return {
            "javaParserFiles": 0,
            "fallbackPythonFiles": 0,
            "workerFailures": 0,
            "relationsGenerated": 0,
            "resolvedMethodCalls": 0,
            "unresolvedMethodCalls": 0,
        }

    def _worker_metrics(self, worker_result) -> dict[str, int]:
        metrics = worker_result.metrics or {}
        return {
            "javaParserFiles": int(metrics.get("javaFilesAnalyzed", 0)),
            "fallbackPythonFiles": 0,
            "workerFailures": 0,
            "relationsGenerated": int(metrics.get("relationsGenerated", len(worker_result.relations))),
            "resolvedMethodCalls": int(metrics.get("resolvedMethodCalls", 0)),
            "unresolvedMethodCalls": int(metrics.get("unresolvedMethodCalls", 0)),
        }

    def _merge_analysis_metrics(self, target: dict[str, int], source: dict[str, int]) -> None:
        for key, value in source.items():
            target[key] = int(target.get(key, 0)) + int(value or 0)

    def _select_latest_artifacts(self, maven_root: Path) -> tuple[list[MavenArtifact], list[dict]]:
        selections: list[MavenArtifact] = []
        skipped: list[dict] = []
        for artifact_dir in sorted([item for item in maven_root.iterdir() if item.is_dir()], key=lambda item: item.name.lower()):
            versions = sort_versions([item.name for item in artifact_dir.iterdir() if item.is_dir()])
            version = latest_version(versions)
            if not version:
                skipped.append({"artifactId": artifact_dir.name, "reason": "sem versoes"})
                continue
            version_dir = artifact_dir / version
            source_jar = version_dir / f"{artifact_dir.name}-{version}-sources.jar"
            binary_jar = version_dir / f"{artifact_dir.name}-{version}.jar"
            if source_jar.is_file():
                selections.append(MavenArtifact(artifact_dir.name, version, version_dir, source_jar, binary_jar if binary_jar.is_file() else None))
            elif binary_jar.is_file():
                selections.append(MavenArtifact(artifact_dir.name, version, version_dir, None, binary_jar))
            else:
                skipped.append({"artifactId": artifact_dir.name, "version": version, "reason": "sem sources.jar ou jar"})
        return selections, skipped

    def _find_maven_root(self, extracted_dir: Path) -> Path | None:
        candidates = [path for path in extracted_dir.rglob("athenas/tosp") if path.is_dir()]
        if candidates:
            return sorted(candidates, key=lambda item: len(item.parts))[0]
        for path in extracted_dir.rglob("*"):
            if not path.is_dir():
                continue
            child_dirs = [item for item in path.iterdir() if item.is_dir()]
            if child_dirs and any(any(version_dir.is_dir() for version_dir in child.iterdir()) for child in child_dirs):
                if any(path.glob("*/*/*.jar")) or any(path.glob("*/*/*-sources.jar")):
                    return path
        return None

    def _find_loose_jars(self, extracted_dir: Path) -> list[Path]:
        jars = [path for path in extracted_dir.rglob("*.jar") if path.is_file() and not path.name.endswith("-sources.jar")]
        source_jars = [path for path in extracted_dir.rglob("*-sources.jar") if path.is_file()]
        return source_jars + jars

    def _decompile_with_cfr(self, jar_path: Path, output_dir: Path) -> None:
        cfr_jar = Path(self.settings.cfr_jar_path).resolve() if self.settings.cfr_jar_path else None
        if not cfr_jar or not cfr_jar.is_file():
            raise ValueError("CFR nao configurado. Informe CFR_JAR_PATH para decompilar bytecode.")
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["java", "-jar", str(cfr_jar), str(jar_path), "--outputdir", str(output_dir)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def _extract_nested_jar(self, jar_path: Path, target_dir: Path, allow_classes: bool) -> list[str]:
        extracted: list[str] = []
        target_dir = target_dir.resolve()
        with zipfile.ZipFile(jar_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = Path(member.filename)
                if self._is_unsafe_member(member_path):
                    continue
                suffix = member_path.suffix.lower()
                allowed = INDEXABLE_EXTENSIONS | ({".class"} if allow_classes else set())
                if suffix not in allowed:
                    continue
                self._validate_file_size(member.file_size)
                destination = (target_dir / member_path).resolve()
                if target_dir not in destination.parents:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.append(str(destination.relative_to(target_dir)).replace("\\", "/"))
        return extracted

    def _copy_tree(self, source_dir: Path, target_dir: Path) -> None:
        if not source_dir.exists():
            return
        for path in source_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                continue
            destination = target_dir / path.relative_to(source_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

    def _has_source_or_bytecode(self, extracted_dir: Path) -> bool:
        return any(path.suffix.lower() in {".java", ".jar", ".class"} for path in extracted_dir.rglob("*") if path.is_file())

    def _save_upload(self, source, destination: Path) -> int:
        total = 0
        max_bytes = self.settings.max_import_size_mb * 1024 * 1024
        with destination.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Arquivo ZIP excede MAX_IMPORT_SIZE_MB={self.settings.max_import_size_mb}.")
                target.write(chunk)
        return total

    def _extract_zip(self, zip_path: Path, target_dir: Path, progress: ProgressCallback | None = None) -> tuple[list[str], list[str]]:
        target_dir = target_dir.resolve()
        extracted: list[str] = []
        errors: list[str] = []
        with zipfile.ZipFile(zip_path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            total_members = len(members)
            total_uncompressed = 0
            for index, member in enumerate(members, start=1):
                if index == 1 or index % 250 == 0 or index == total_members:
                    self._emit(
                        progress,
                        "extracting",
                        f"Extraindo ZIP: {index}/{total_members} entradas verificadas.",
                        index,
                        total_members,
                        8 + int((index / max(total_members, 1)) * 17),
                    )
                member_path = Path(member.filename)
                if self._is_unsafe_member(member_path):
                    errors.append(f"Ignorado por path traversal: {member.filename}")
                    continue
                total_uncompressed += member.file_size
                self._validate_total_size(total_uncompressed)
                self._validate_file_size(member.file_size)
                if member_path.suffix.lower() not in ZIP_EXTRACT_EXTENSIONS:
                    continue
                destination = (target_dir / member_path).resolve()
                if target_dir not in destination.parents:
                    errors.append(f"Ignorado por destino invalido: {member.filename}")
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.append(str(destination.relative_to(target_dir)).replace("\\", "/"))
        return extracted, errors

    def _emit(
        self,
        progress: ProgressCallback | None,
        phase: str,
        message: str,
        current: int = 0,
        total: int = 0,
        progress_value: int | None = None,
    ) -> None:
        if progress:
            progress(phase, message, current, total, progress_value)

    def _validate_total_size(self, size_bytes: int) -> None:
        if size_bytes > self.settings.max_import_size_mb * 1024 * 1024:
            raise ValueError(f"Importacao excede MAX_IMPORT_SIZE_MB={self.settings.max_import_size_mb}.")

    def _validate_file_size(self, size_bytes: int) -> None:
        max_file_size = min(self.settings.max_import_file_size_mb * 1024 * 1024, self.settings.max_import_size_mb * 1024 * 1024)
        if size_bytes > max_file_size:
            raise ValueError(
                f"Arquivo dentro do ZIP excede MAX_IMPORT_FILE_SIZE_MB={self.settings.max_import_file_size_mb}: {size_bytes} bytes."
            )

    def _is_unsafe_member(self, member_path: Path) -> bool:
        return member_path.is_absolute() or any(part in {"..", ""} for part in member_path.parts)

    def _checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
