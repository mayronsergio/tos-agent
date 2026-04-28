from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from app.services.repository import CodeRepository
from app.services.vector_index import VectorIndex
from app.services.zip_importer import ZipImporter


class DummySettings:
    def __init__(self, tmp_path: Path, data_dir: Path | None = None):
        self.data_dir = data_dir or tmp_path / "data"
        self.data_dir.mkdir()
        self.max_import_size_mb = 50
        self.max_import_file_size_mb = 10
        self.enable_vector_index = False
        self.qdrant_url = "http://qdrant:6333"
        self.qdrant_collection = "test"
        self.cfr_jar_path = None


def test_import_zip_extracts_indexes_and_blocks_traversal(tmp_path: Path):
    zip_path = tmp_path / "code.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "src/br/com/acme/ClienteService.java",
            """
            package br.com.acme;
            public class ClienteService {
                public void validar() {
                    throw new IllegalArgumentException("Cliente obrigatorio");
                }
            }
            """,
        )
        archive.writestr("messages.properties", "cliente.nome=Cliente obrigatorio")
        archive.writestr("../escape.java", "public class Escape {}")

    settings = DummySettings(tmp_path)
    repository = CodeRepository(tmp_path / "db.sqlite3")
    importer = ZipImporter(repository, VectorIndex(settings), settings)

    with zip_path.open("rb") as handle:
        response = importer.import_zip(SimpleNamespace(filename="code.zip", file=handle), reset=True)

    assert response.importedFiles == 2
    assert response.indexedSymbols > 0
    assert response.errors
    evidence = repository.search_text("Cliente obrigatorio", limit=5)[0]
    assert evidence.source_type == "sources"
    metadata_path = Path(response.metadataPath)
    assert metadata_path.is_file()
    assert (metadata_path.parent / "code-graph.json").is_file()


def test_import_zip_with_relative_data_dir(tmp_path: Path, monkeypatch):
    zip_path = tmp_path / "code.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("src/Cliente.java", "public class Cliente {}")

    monkeypatch.chdir(tmp_path)
    settings = DummySettings(tmp_path, data_dir=Path("data"))
    repository = CodeRepository(tmp_path / "db.sqlite3")
    importer = ZipImporter(repository, VectorIndex(settings), settings)

    with zip_path.open("rb") as handle:
        response = importer.import_zip(SimpleNamespace(filename="code.zip", file=handle), reset=True)

    assert response.importedFiles == 1
    assert Path(response.metadataPath).is_absolute()


def test_import_zip_rejects_pom_only(tmp_path: Path):
    zip_path = tmp_path / "pom-only.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("athenas/tosp/aam/1.13.2/aam-1.13.2.pom", "<project></project>")

    settings = DummySettings(tmp_path)
    repository = CodeRepository(tmp_path / "db.sqlite3")
    importer = ZipImporter(repository, VectorIndex(settings), settings)

    with zip_path.open("rb") as handle:
        with pytest.raises(ValueError, match="Nenhum código fonte ou bytecode encontrado no ZIP"):
            importer.import_zip(SimpleNamespace(filename="pom-only.zip", file=handle), reset=True)


def test_import_zip_detects_maven_sources_and_latest(tmp_path: Path):
    zip_path = tmp_path / "maven.zip"
    with zipfile.ZipFile(tmp_path / "aam-1.13.2-sources.jar", "w") as sources:
        sources.writestr(
            "br/com/acme/ClienteService.java",
            "package br.com.acme; public class ClienteService { public void validar() {} }",
        )
    sources_bytes = (tmp_path / "aam-1.13.2-sources.jar").read_bytes()
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("athenas/tosp/aam/1.12.5/aam-1.12.5.pom", "<project></project>")
        archive.writestr("athenas/tosp/aam/1.13.2/aam-1.13.2-sources.jar", sources_bytes)

    settings = DummySettings(tmp_path)
    repository = CodeRepository(tmp_path / "db.sqlite3")
    importer = ZipImporter(repository, VectorIndex(settings), settings)

    with zip_path.open("rb") as handle:
        response = importer.import_zip(SimpleNamespace(filename="maven.zip", file=handle), reset=True)

    assert response.processedArtifacts == 1
    assert response.importedFiles == 1
    evidence = repository.search_text("ClienteService", limit=5)[0]
    assert evidence.artifact_id == "aam"
    assert evidence.version == "1.13.2"
    assert evidence.source_type == "sources"


def test_import_zip_logs_decompilation_error_without_cfr(tmp_path: Path):
    zip_path = tmp_path / "maven-bin.zip"
    with zipfile.ZipFile(tmp_path / "aam-1.13.2.jar", "w") as binary:
        binary.writestr("br/com/acme/Cliente.class", b"\xca\xfe\xba\xbe")
    binary_bytes = (tmp_path / "aam-1.13.2.jar").read_bytes()
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("athenas/tosp/aam/1.13.2/aam-1.13.2.jar", binary_bytes)

    settings = DummySettings(tmp_path)
    repository = CodeRepository(tmp_path / "db.sqlite3")
    importer = ZipImporter(repository, VectorIndex(settings), settings)

    with zip_path.open("rb") as handle:
        response = importer.import_zip(SimpleNamespace(filename="maven-bin.zip", file=handle), reset=True)

    assert response.processedArtifacts == 1
    assert response.importedFiles == 0
    assert response.errors
