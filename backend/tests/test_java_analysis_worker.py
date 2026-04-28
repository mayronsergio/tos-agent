from pathlib import Path
from types import SimpleNamespace

import pytest

from app.indexing.extractors import extract_symbols
from app.services.java_worker import JavaAnalysisWorker


def test_java_worker_returns_none_when_command_fails(tmp_path: Path):
    settings = SimpleNamespace(java_analysis_worker_command="java -jar missing-worker.jar", java_analysis_worker_timeout_seconds=5)

    assert JavaAnalysisWorker(settings).analyze(tmp_path, tmp_path) is None


def test_java_worker_ast_output_improves_method_call_precision(tmp_path: Path):
    jar = Path(__file__).resolve().parents[2] / "code-analysis-worker" / "target" / "code-analysis-worker.jar"
    if not jar.is_file():
        pytest.skip("code-analysis-worker jar not built")

    source = tmp_path / "src"
    source.mkdir()
    service = source / "PedidoService.java"
    service.write_text(
        """
        package acme;
        public class PedidoService {
            private final PedidoRepository repository = new PedidoRepository();
            public void salvar(Pedido pedido) {
                repository.save(pedido);
            }
        }
        class PedidoRepository {
            public void save(Pedido pedido) {}
        }
        class Pedido {}
        """,
        encoding="utf-8",
    )

    fallback_symbols = extract_symbols(service, tmp_path, context={"source_type": "sources"})
    settings = SimpleNamespace(
        java_analysis_worker_command=f"java -jar {jar}",
        java_analysis_worker_timeout_seconds=30,
    )
    result = JavaAnalysisWorker(settings).analyze(source, tmp_path, context={"source_type": "sources"})

    assert result is not None
    assert any(item.class_name == "PedidoService" for item in fallback_symbols)
    assert len(result.symbols) >= 3
    assert any(symbol.class_name == "PedidoService" and symbol.method_name == "salvar" for symbol in result.symbols)
    assert any(relation["type"] == "METHOD_CALLS_METHOD" and "save" in relation["target"] for relation in result.relations)
    assert any(relation["type"] == "FIELD_HAS_TYPE" and "PedidoRepository" in relation["target"] for relation in result.relations)
