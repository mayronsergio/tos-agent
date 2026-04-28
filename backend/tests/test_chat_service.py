from types import SimpleNamespace

import pytest

from app.indexing.extractors import CodeSymbol
from app.llm.providers import MockProvider
from app.services.chat import ANTI_HALLUCINATION_MESSAGE, ChatService
from app.services.repository import CodeRepository
from app.services.search import SearchService
from app.services.vector_index import VectorIndex


def build_chat_service(tmp_path):
    repository = CodeRepository(tmp_path / "code.db")
    repository.insert_symbols(
        [
            CodeSymbol(
                file_path="aam/src/MercadoriaService.java",
                symbol_type="method",
                name="validarStatusSaida",
                artifact_id="aam",
                version="1.13.2",
                source_type="sources",
                language="java",
                package="br.com.tosp.aam",
                class_name="MercadoriaService",
                method_name="validarStatusSaida",
                layer="service",
                message="Mercadoria com status saida nao permite concluir pesagem",
                validation="throw new RegraNegocioException",
                line_start=12,
                line_end=24,
                snippet=(
                    "public void validarStatusSaida(Mercadoria mercadoria) {\n"
                    "  if (mercadoria.getStatus() == StatusMercadoria.SAIDA) {\n"
                    "    throw new RegraNegocioException(\"Mercadoria com status saida nao permite concluir pesagem\");\n"
                    "  }\n"
                    "}"
                ),
                tags=["method", "validation", "service"],
            ),
            CodeSymbol(
                file_path="aam/src/MovimentacaoSaidaService.java",
                symbol_type="method",
                name="salvarMovimentacaoSaida",
                artifact_id="aam",
                version="1.13.2",
                source_type="sources",
                language="java",
                package="br.com.tosp.aam",
                class_name="MovimentacaoSaidaService",
                method_name="salvarMovimentacaoSaida",
                layer="service",
                line_start=8,
                line_end=18,
                snippet="public void salvarMovimentacaoSaida(Mercadoria m) { movimentacaoRepository.save(m); }",
                tags=["method", "service"],
            ),
            CodeSymbol(
                file_path="aam/src/MovimentacaoRepository.java",
                symbol_type="table",
                name="TB_MOVIMENTACAO",
                artifact_id="aam",
                version="1.13.2",
                source_type="sources",
                language="java",
                package="br.com.tosp.aam",
                class_name="MovimentacaoRepository",
                layer="dao/repository",
                table_name="TB_MOVIMENTACAO",
                line_start=20,
                line_end=26,
                snippet='String sql = "insert into TB_MOVIMENTACAO (ID, STATUS) values (?, ?)";',
                tags=["table", "repository"],
            ),
            CodeSymbol(
                file_path="aam/src/Mercadoria.java",
                symbol_type="class",
                name="Mercadoria",
                artifact_id="aam",
                version="1.13.2",
                source_type="sources",
                language="java",
                package="br.com.tosp.aam",
                class_name="Mercadoria",
                entity_name="Mercadoria",
                layer="entity",
                table_name="TB_MERCADORIA",
                line_start=5,
                line_end=12,
                snippet='@Entity\n@Table(name = "TB_MERCADORIA")\npublic class Mercadoria { private StatusMercadoria status; }',
                tags=["class", "entity"],
            ),
        ]
    )
    settings = SimpleNamespace(enable_vector_index=False, qdrant_url="", qdrant_collection="")
    return ChatService(SearchService(repository, VectorIndex(settings)), MockProvider())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Onde e validado o status da mercadoria?", "MercadoriaService.validarStatusSaida"),
        ("Qual classe faz a movimentacao de saida?", "MovimentacaoSaidaService.salvarMovimentacaoSaida"),
        ("Por que a pesagem nao conclui?", "MercadoriaService.validarStatusSaida"),
        ("Qual entidade representa a mercadoria?", "Mercadoria"),
        ("Que metodo salva a movimentacao?", "MovimentacaoSaidaService.salvarMovimentacaoSaida"),
    ],
)
async def test_chat_answers_with_indexed_java_evidence(tmp_path, question, expected):
    service = build_chat_service(tmp_path)

    response = await service.answer(question, top_k=10, investigation_mode=True)

    assert response.confidence in {"medium", "high"}
    assert "Resumo:" in response.answer
    assert "Evidências encontradas:" in response.answer or "Evidencias encontradas:" in response.answer
    assert "Solução recomendada pela aplicação:" in response.answer or "Solucao recomendada pela aplicacao:" in response.answer
    assert any(expected in f"{item.class_name}.{item.method_name}" or expected == item.class_name for item in response.evidences)
    assert all(item.artifact_id == "aam" for item in response.evidences)
    assert all(item.version == "1.13.2" for item in response.evidences)
    assert response.suggestedFollowUp


@pytest.mark.anyio
async def test_chat_low_confidence_when_no_evidence(tmp_path):
    service = build_chat_service(tmp_path)

    response = await service.answer("Como configurar integracao bancaria remessa CNAB?", top_k=5)

    assert response.confidence == "low"
    assert ANTI_HALLUCINATION_MESSAGE in response.answer
