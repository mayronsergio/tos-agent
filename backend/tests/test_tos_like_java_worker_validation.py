from pathlib import Path
from types import SimpleNamespace
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.routes import settings as api_settings
from app.main import app
from app.services.repository import CodeRepository
from app.services.vector_index import VectorIndex
from app.services.zip_importer import ZipImporter


def worker_command() -> str:
    jar = Path(__file__).resolve().parents[2] / "code-analysis-worker" / "target" / "code-analysis-worker.jar"
    if not jar.is_file():
        pytest.skip("code-analysis-worker jar not built")
    return f"java -jar {jar}"


class WorkerSettings:
    def __init__(self, tmp_path: Path):
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir()
        self.max_import_size_mb = 50
        self.max_import_file_size_mb = 10
        self.enable_vector_index = False
        self.qdrant_url = "http://qdrant:6333"
        self.qdrant_collection = "test"
        self.cfr_jar_path = None
        self.java_analysis_worker_command = worker_command()
        self.java_analysis_worker_timeout_seconds = 30


def write_tos_like_sources(root: Path) -> None:
    (root / "br/com/tos/domain").mkdir(parents=True)
    (root / "br/com/tos/web").mkdir(parents=True)
    (root / "br/com/tos/service").mkdir(parents=True)
    (root / "br/com/tos/repository").mkdir(parents=True)
    (root / "javax/persistence").mkdir(parents=True)

    for annotation in ["Entity", "Table", "Column", "Id", "ManyToOne"]:
        (root / f"javax/persistence/{annotation}.java").write_text(
            f"package javax.persistence; public @interface {annotation} {{ String name() default \"\"; }}",
            encoding="utf-8",
        )

    (root / "br/com/tos/domain/Transporte.java").write_text(
        """
        package br.com.tos.domain;
        import javax.persistence.*;
        public abstract class Transporte {
            @Id
            @Column(name = "ID_TRANSPORTE")
            private Long id;
            @Column(name = "CODIGO")
            private String codigo;
        }
        """,
        encoding="utf-8",
    )
    (root / "br/com/tos/domain/Navio.java").write_text(
        """
        package br.com.tos.domain;
        import javax.persistence.*;
        @Entity
        @Table(name = "TB_NAVIO")
        public class Navio extends Transporte {
            @Column(name = "NOME")
            private String nome;
            @ManyToOne
            private Armador armador;
            @Override
            public String toString() { return nome; }
        }
        class Armador {}
        """,
        encoding="utf-8",
    )
    (root / "br/com/tos/web/CoMaintainController.java").write_text(
        """
        package br.com.tos.web;
        public abstract class CoMaintainController<T> {
            protected T service;
            public void manter() { }
        }
        """,
        encoding="utf-8",
    )
    (root / "br/com/tos/web/ManutenirVinculoNotaNavioController.java").write_text(
        """
        package br.com.tos.web;
        import br.com.tos.service.VinculoNotaNavioServiceActivity;
        public class ManutenirVinculoNotaNavioController extends CoMaintainController<VinculoNotaNavioServiceActivity> {
            private final VinculoNotaNavioServiceActivity service = new VinculoNotaNavioServiceActivity();
            @Override
            public void manter() { service.salvar(); }
        }
        """,
        encoding="utf-8",
    )
    (root / "br/com/tos/service/VinculoNotaNavioServiceActivity.java").write_text(
        """
        package br.com.tos.service;
        import br.com.tos.repository.VinculoNotaNavioRepository;
        public class VinculoNotaNavioServiceActivity {
            private final VinculoNotaNavioRepository repository = new VinculoNotaNavioRepository();
            public void salvar() { repository.save(); }
        }
        """,
        encoding="utf-8",
    )
    (root / "br/com/tos/repository/VinculoNotaNavioRepository.java").write_text(
        """
        package br.com.tos.repository;
        public class VinculoNotaNavioRepository {
            public void save() { }
        }
        """,
        encoding="utf-8",
    )


def import_tos_like_zip(tmp_path: Path):
    source_root = tmp_path / "source"
    write_tos_like_sources(source_root)
    zip_path = tmp_path / "tos.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for file in source_root.rglob("*.java"):
            archive.write(file, file.relative_to(source_root).as_posix())

    settings = WorkerSettings(tmp_path)
    repository = CodeRepository(tmp_path / "db.sqlite3")
    importer = ZipImporter(repository, VectorIndex(settings), settings)
    with zip_path.open("rb") as handle:
        response = importer.import_zip(SimpleNamespace(filename="tos.zip", file=handle), reset=True)
    return response, repository, settings


def test_worker_tos_like_import_generates_structural_graph_and_report(tmp_path: Path):
    response, repository, _settings = import_tos_like_zip(tmp_path)
    metadata = json.loads(Path(response.metadataPath).read_text(encoding="utf-8"))
    relations = repository.graph_relations()

    assert metadata["analysis"]["javaParserFiles"] >= 6
    assert metadata["analysis"]["fallbackPythonFiles"] == 0
    assert metadata["analysis"]["workerFailures"] == 0
    assert metadata["analysis"]["relationsGenerated"] > 0
    assert metadata["analysis"]["resolvedMethodCalls"] > 0
    assert any(item["type"] == "CLASS_HAS_GENERIC_ARGUMENT" and item["target"] == "VinculoNotaNavioServiceActivity" for item in relations)
    assert any(item["type"] == "METHOD_OVERRIDES_METHOD" and item["source"] == "ManutenirVinculoNotaNavioController" for item in relations)
    assert any(item["type"] == "ENTITY_MAPS_TABLE" and item["source"] == "Navio" and item["target"] == "TB_NAVIO" for item in relations)
    assert any(item["type"] == "FIELD_HAS_TYPE" and item["source"] == "Navio" and "Armador" in item["target"] for item in relations)
    assert any(item["type"] == "METHOD_CALLS_METHOD" and "VinculoNotaNavioRepository.save" in item["target"] for item in relations)


def test_chat_entity_attributes_uses_navio_and_inherited_transporte(tmp_path: Path, monkeypatch):
    response, repository, settings = import_tos_like_zip(tmp_path)
    monkeypatch.setattr("app.api.routes.repository", repository)
    monkeypatch.setattr("app.api.routes.settings", api_settings)
    monkeypatch.setattr("app.api.routes.search_service.repository", repository)
    monkeypatch.setattr("app.api.routes.vector_index.enabled", False)

    client = TestClient(app)
    chat = client.post("/api/chat", json={"message": "Quais sao os atributos da entidade Navio?", "topK": 20})
    body = chat.json()

    assert chat.status_code == 200
    assert body["confidence"] == "high"
    assert body["intent"] == "ENTITY_ATTRIBUTES"
    assert "Navio" in body["answer"]
    assert "String nome" in body["answer"]
    assert "Armador armador" in body["answer"]
    assert "Long id" in body["answer"]
    assert "String codigo" in body["answer"]
    assert all("Controller" not in item.get("class_name", "") for item in body["evidences"] if item["evidenceType"] in {"entidade", "atributo proprio", "atributo herdado"})


def test_graph_class_debug_includes_superclass_generics_fields_methods_and_sources(tmp_path: Path, monkeypatch):
    _response, repository, _settings = import_tos_like_zip(tmp_path)
    monkeypatch.setattr("app.api.routes.repository", repository)
    monkeypatch.setattr("app.api.routes.code_graph.repository", repository)

    client = TestClient(app)
    navio = client.get("/api/graph/class/Navio").json()
    controller = client.get("/api/graph/class/ManutenirVinculoNotaNavioController").json()

    assert navio["superclass"] == "Transporte"
    assert "nome" in navio["fields"]
    assert "toString" in navio["methods"]
    assert any(path.endswith("Navio.java") for path in navio["sourceFiles"])
    assert any(item["type"] == "CLASS_EXTENDS_CLASS" and item["target"] == "Transporte" for item in navio["relations"])
    assert "VinculoNotaNavioServiceActivity" in controller["genericArguments"]
    assert any(item["type"] == "CLASS_HAS_GENERIC_ARGUMENT" for item in controller["relations"])
