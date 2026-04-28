from types import SimpleNamespace

import pytest

from app.indexing.extractors import CodeSymbol
from app.llm.providers import MockProvider
from app.services.chat import ChatService
from app.services.repository import CodeRepository
from app.services.search import SearchService
from app.services.vector_index import VectorIndex


def build_structural_chat_service(tmp_path):
    repository = CodeRepository(tmp_path / "code.db")
    repository.insert_symbols(
        [
            CodeSymbol(
                file_path="core/BaseEntity.java",
                file_name="BaseEntity.java",
                symbol_type="class",
                name="BaseEntity",
                language="java",
                package="acme.model",
                class_name="BaseEntity",
                layer="entity",
                line_start=1,
                line_end=20,
                snippet="public abstract class BaseEntity { private Long id; private LocalDateTime criadoEm; }",
                tags=["class", "entity"],
                fields=["id", "criadoEm"],
                methods=["getId"],
            ),
            CodeSymbol(
                file_path="core/BaseEntity.java",
                file_name="BaseEntity.java",
                symbol_type="field",
                name="id",
                language="java",
                package="acme.model",
                class_name="BaseEntity",
                layer="entity",
                field_type="Long",
                field_annotations=["Id"],
                snippet="@Id\nprivate Long id;",
                tags=["field", "entity"],
            ),
            CodeSymbol(
                file_path="core/BaseEntity.java",
                file_name="BaseEntity.java",
                symbol_type="field",
                name="criadoEm",
                language="java",
                package="acme.model",
                class_name="BaseEntity",
                layer="entity",
                field_type="LocalDateTime",
                snippet="private LocalDateTime criadoEm;",
                tags=["field", "entity"],
            ),
            CodeSymbol(
                file_path="domain/Navio.java",
                file_name="Navio.java",
                symbol_type="class",
                name="Navio",
                language="java",
                package="acme.entity",
                class_name="Navio",
                entity_name="Navio",
                superclass="BaseEntity",
                table_name="TB_NAVIO",
                layer="entity",
                line_start=1,
                line_end=20,
                snippet='@Entity\n@Table(name = "TB_NAVIO")\npublic class Navio extends BaseEntity { private String nome; private String imo; }',
                tags=["class", "entity"],
                fields=["nome", "imo"],
            ),
            CodeSymbol(
                file_path="domain/Navio.java",
                file_name="Navio.java",
                symbol_type="field",
                name="nome",
                language="java",
                package="acme.entity",
                class_name="Navio",
                entity_name="Navio",
                superclass="BaseEntity",
                layer="entity",
                field_type="String",
                field_annotations=["Column"],
                snippet='@Column(name = "NOME")\nprivate String nome;',
                tags=["field", "entity"],
            ),
            CodeSymbol(
                file_path="domain/Navio.java",
                file_name="Navio.java",
                symbol_type="field",
                name="imo",
                language="java",
                package="acme.entity",
                class_name="Navio",
                entity_name="Navio",
                superclass="BaseEntity",
                layer="entity",
                field_type="String",
                snippet="private String imo;",
                tags=["field", "entity"],
            ),
            CodeSymbol(
                file_path="web/CoMaintainController.java",
                file_name="CoMaintainController.java",
                symbol_type="class",
                name="CoMaintainController",
                language="java",
                package="acme.web",
                class_name="CoMaintainController",
                superclass="BaseController",
                generic_superclass="BaseController<VinculoNotaNavioServiceActivity>",
                generic_arguments=["VinculoNotaNavioServiceActivity"],
                layer="controller/action",
                line_start=1,
                line_end=10,
                snippet="public class CoMaintainController extends BaseController<VinculoNotaNavioServiceActivity> {}",
                tags=["class", "controller"],
            ),
            CodeSymbol(
                file_path="web/BaseController.java",
                file_name="BaseController.java",
                symbol_type="class",
                name="BaseController",
                language="java",
                package="acme.web",
                class_name="BaseController",
                layer="controller/action",
                methods=["manter"],
                snippet="public abstract class BaseController<T> { public void manter() { service.salvar(); } }",
                tags=["class", "controller"],
            ),
            CodeSymbol(
                file_path="web/BaseController.java",
                file_name="BaseController.java",
                symbol_type="method",
                name="manter",
                language="java",
                package="acme.web",
                class_name="BaseController",
                method_name="manter",
                layer="controller/action",
                snippet="public void manter() { service.salvar(); }",
                tags=["method", "controller"],
            ),
            CodeSymbol(
                file_path="service/VinculoNotaNavioServiceActivity.java",
                file_name="VinculoNotaNavioServiceActivity.java",
                symbol_type="method",
                name="salvar",
                language="java",
                package="acme.service",
                class_name="VinculoNotaNavioServiceActivity",
                method_name="salvar",
                layer="service",
                snippet="public void salvar(VinculoNotaNavio vinculo) { validar(vinculo); repository.save(vinculo); }",
                tags=["method", "service"],
            ),
        ]
    )
    settings = SimpleNamespace(enable_vector_index=False, qdrant_url="", qdrant_collection="")
    return ChatService(SearchService(repository, VectorIndex(settings)), MockProvider())


@pytest.mark.anyio
async def test_entity_attributes_include_own_and_inherited_fields(tmp_path):
    service = build_structural_chat_service(tmp_path)

    response = await service.answer("Quais sao os atributos da entidade Navio?", top_k=20)

    assert response.confidence == "high"
    assert "Atributos proprios:" in response.answer
    assert "String nome" in response.answer
    assert "String imo" in response.answer
    assert "Atributos herdados:" in response.answer
    assert "Long id" in response.answer
    assert "LocalDateTime criadoEm" in response.answer
    assert "BaseEntity" in response.answer
    assert not any(item.evidenceType == "service" for item in response.evidences)


@pytest.mark.anyio
async def test_generic_controller_maps_base_class_service_activity_and_inherited_method(tmp_path):
    service = build_structural_chat_service(tmp_path)

    response = await service.answer("Qual fluxo salva VinculoNotaNavio?", top_k=20, investigation_mode=True)

    assert response.confidence in {"medium", "high"}
    assert any(item.genericSuperclass == "BaseController<VinculoNotaNavioServiceActivity>" for item in response.evidences)
    assert any(item.relatedServiceActivity == "VinculoNotaNavioServiceActivity" for item in response.evidences)
    assert any("manter" in item.inheritedMethods for item in response.evidences)
    assert "Estrutura/heranca/generics considerados" in response.answer
