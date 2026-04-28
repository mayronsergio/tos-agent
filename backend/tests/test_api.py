from pathlib import Path
import time
import zipfile

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_only_exposes_api_prefixed_routes():
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = set(response.json()["paths"])
    expected_paths = {
        "/api/health",
        "/api/index/status",
        "/api/config",
        "/api/imports/zip",
        "/api/reset",
        "/api/imports/{job_id}",
        "/api/search",
        "/api/chat",
        "/api/logs",
        "/api/graph/class/{class_name}",
        "/api/entities",
        "/api/services",
    }
    unprefixed_paths = {
        "/health",
        "/index/status",
        "/config",
        "/imports/zip",
        "/reset",
        "/imports/{job_id}",
        "/search",
        "/chat",
        "/logs",
    }

    assert expected_paths.issubset(paths)
    assert paths.isdisjoint(unprefixed_paths)


def test_public_routes_are_not_available_without_api_prefix():
    for path in ["/health", "/index/status", "/config", "/imports/zip", "/reset", "/search", "/chat", "/logs"]:
        assert client.get(path).status_code == 404


def test_search_empty_index():
    response = client.post("/api/search", json={"query": "Cliente", "mode": "text", "limit": 5})
    assert response.status_code == 200
    assert "evidences" in response.json()


def test_get_runtime_config():
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_provider"] in {"mock", "openai", "ollama"}
    assert "openai_api_key_set" in body


def test_backend_logs_endpoint_returns_recent_entries():
    client.get("/api/health")
    response = client.get("/api/logs?limit=20&source=backend")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "backend"
    assert isinstance(body["entries"], list)
    assert any("Health check invoked" in entry["message"] for entry in body["entries"])


def test_chat_accepts_message_payload_without_question():
    response = client.post(
        "/api/chat",
        json={
            "message": "Quais campos tem na entidade navio?",
            "topK": 20,
            "investigationMode": True,
            "conversationId": "test-conversation",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert body["confidence"] in {"low", "medium", "high"}


def test_zip_import_starts_background_job(tmp_path: Path):
    zip_path = tmp_path / "code.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("src/Navio.java", "public class Navio { private String nome; }")

    with zip_path.open("rb") as handle:
        response = client.post("/api/imports/zip", files={"file": ("code.zip", handle, "application/zip")}, data={"reset": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"queued", "running"}
    job_id = body["jobId"]

    status = None
    for _ in range(20):
        status = client.get(f"/api/imports/{job_id}")
        assert status.status_code == 200
        if status.json()["status"] in {"completed", "failed"}:
            break
        time.sleep(0.2)

    assert status is not None
    assert status.json()["status"] == "completed"
    assert status.json()["result"]["importedFiles"] >= 1


def test_reset_clears_data_and_settings():
    config = client.get("/api/config").json()
    updated = dict(config)
    updated["max_import_size_mb"] = 4321
    response = client.put("/api/config", json=updated)
    assert response.status_code == 200
    assert response.json()["max_import_size_mb"] == 4321

    reset_response = client.post("/api/reset")
    assert reset_response.status_code == 200
    assert reset_response.json()["status"] == "reset"

    status = client.get("/api/index/status")
    assert status.json()["indexed_files"] == 0
    assert status.json()["indexed_symbols"] == 0
    assert "graph_relations" in status.json()

    config_after = client.get("/api/config").json()
    assert config_after["max_import_size_mb"] == 5000


def test_graph_entities_and_services_endpoints():
    graph = client.get("/api/graph/class/ClienteService")
    assert graph.status_code == 200
    assert graph.json()["className"] == "ClienteService"
    assert "relations" in graph.json()

    entities = client.get("/api/entities")
    assert entities.status_code == 200
    assert isinstance(entities.json(), list)

    services = client.get("/api/services")
    assert services.status_code == 200
    assert isinstance(services.json(), list)
