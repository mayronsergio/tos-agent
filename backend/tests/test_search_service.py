from types import SimpleNamespace

from app.indexing.extractors import CodeSymbol
from app.models.schemas import SearchMode
from app.services.repository import CodeRepository
from app.services.search import SearchService
from app.services.vector_index import VectorIndex


def build_search_service(tmp_path):
    repository = CodeRepository(tmp_path / "code.db")
    repository.insert_symbols(
        [
            CodeSymbol(
                file_path="src/main/java/acme/domain/Pedido.java",
                file_name="Pedido.java",
                symbol_type="class",
                name="Pedido",
                language="java",
                package="acme.domain",
                class_name="Pedido",
                entity_name="Pedido",
                table_name="TB_PEDIDO",
                layer="entity",
                snippet='@Entity\n@Table(name = "TB_PEDIDO")\npublic class Pedido { private String numero; }',
                tags=["class", "entity"],
            ),
            CodeSymbol(
                file_path="src/main/java/acme/service/PedidoService.java",
                file_name="PedidoService.java",
                symbol_type="method",
                name="calcularTotal",
                language="java",
                package="acme.service",
                class_name="PedidoService",
                method_name="calcularTotal",
                layer="service",
                line_start=20,
                line_end=28,
                snippet="public BigDecimal calcularTotal(Pedido pedido) { return pedido.total(); }",
                tags=["method", "service"],
            ),
            CodeSymbol(
                file_path="src/main/java/acme/repository/PedidoRepository.java",
                file_name="PedidoRepository.java",
                symbol_type="table",
                name="TB_PEDIDO",
                language="java",
                package="acme.repository",
                class_name="PedidoRepository",
                table_name="TB_PEDIDO",
                layer="dao/repository",
                line_start=12,
                line_end=18,
                snippet='String sql = "select * from TB_PEDIDO where ID = ?";',
                tags=["table", "repository"],
            ),
            CodeSymbol(
                file_path="src/main/java/acme/infra/Auditoria.java",
                file_name="Auditoria.java",
                symbol_type="message",
                name="Pedido atualizado pelo usuario",
                language="java",
                package="acme.infra",
                class_name="Auditoria",
                message="Pedido atualizado pelo usuario",
                line_start=30,
                line_end=35,
                snippet='log.info("Pedido atualizado pelo usuario");',
                tags=["message"],
            ),
            CodeSymbol(
                file_path="src/main/java/acme/domain/Pedido.java",
                file_name="Pedido.java",
                symbol_type="field",
                name="numero",
                language="java",
                package="acme.domain",
                class_name="Pedido",
                entity_name="Pedido",
                layer="entity",
                line_start=4,
                line_end=6,
                snippet="private String numero;",
                tags=["field", "entity"],
            ),
        ]
    )
    settings = SimpleNamespace(enable_vector_index=False, qdrant_url="", qdrant_collection="")
    return SearchService(repository, VectorIndex(settings))


def test_exact_class_name_returns_class_first(tmp_path):
    service = build_search_service(tmp_path)

    results = service.search("Pedido", SearchMode.hybrid, 5)

    assert results[0].class_name == "Pedido"
    assert results[0].matchType == "classe exata"
    assert results[0].symbolScore >= 100


def test_file_name_returns_file_first(tmp_path):
    service = build_search_service(tmp_path)

    results = service.search("/Pedido.java", SearchMode.hybrid, 5)

    assert results[0].file_path == "src/main/java/acme/domain/Pedido.java"
    assert results[0].matchType in {"arquivo exato", "classe exata"}
    assert results[0].symbolScore >= 95


def test_table_name_returns_related_repository_or_entity(tmp_path):
    service = build_search_service(tmp_path)

    results = service.search("tb_pedidos", SearchMode.hybrid, 5)

    assert results[0].table_name == "TB_PEDIDO"
    assert results[0].matchType == "tabela exata"
    assert results[0].layer in {"entity", "dao/repository"}


def test_method_name_returns_method_first(tmp_path):
    service = build_search_service(tmp_path)

    results = service.search("calcular-total", SearchMode.hybrid, 5)

    assert results[0].method_name == "calcularTotal"
    assert results[0].matchType == "metodo exato"
    assert results[0].symbolScore >= 80


def test_descriptive_query_keeps_hybrid_text_context(tmp_path):
    service = build_search_service(tmp_path)

    results = service.search("onde calcula o total do pedido", SearchMode.hybrid, 5)

    assert any(item.method_name == "calcularTotal" for item in results)
    assert all(item.finalScore >= item.textScore for item in results)


def test_results_are_grouped_by_file_before_repeating_chunks(tmp_path):
    service = build_search_service(tmp_path)

    results = service.search("Pedido", SearchMode.hybrid, 4)
    first_file_positions = {item.file_path: index for index, item in enumerate(results)}

    assert first_file_positions["src/main/java/acme/service/PedidoService.java"] < 3
    assert len({item.file_path for item in results[:3]}) == 3
