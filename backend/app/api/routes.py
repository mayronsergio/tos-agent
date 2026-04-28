from fastapi import APIRouter, File, Form, HTTPException, UploadFile
import logging

from app.core.config import get_settings
from app.llm.providers import build_provider
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ClassGraphResponse,
    EntitySummary,
    ServiceSummary,
    ImportJobResponse,
    ImportJobStatus,
    IndexStatus,
    LogEntry,
    LogsResponse,
    RuntimeConfig,
    RuntimeConfigResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.chat import ChatService
from app.services.code_graph import CodeGraphService
from app.services.import_jobs import ImportJobManager
from app.services.reset_service import ResetService
from app.services.repository import CodeRepository
from app.services.runtime_config import RuntimeConfigService
from app.services.search import SearchService
from app.services.vector_index import VectorIndex
from app.services.zip_importer import ZipImporter
from app.core.logging import get_log_handler

router = APIRouter()
settings = get_settings()
default_settings = settings.model_copy(deep=True)
repository = CodeRepository(settings.sqlite_path)
vector_index = VectorIndex(settings)
search_service = SearchService(repository, vector_index)
runtime_config = RuntimeConfigService(repository, settings)
zip_importer = ZipImporter(repository, vector_index, settings)
import_jobs = ImportJobManager(zip_importer, settings.data_dir)
reset_service = ResetService(repository, vector_index, import_jobs, settings.data_dir)
code_graph = CodeGraphService(repository)
log = logging.getLogger("code_support_agent.api")


@router.get("/health")
def health() -> dict:
    log.info("Health check invoked.")
    return {"status": "ok", "app": settings.app_name}


@router.get("/index/status", response_model=IndexStatus)
def index_status() -> IndexStatus:
    status = repository.status()
    return IndexStatus(
        indexed_files=status["indexed_files"],
        indexed_symbols=status["indexed_symbols"],
        indexed_chunks=status["indexed_chunks"],
        entities=status["entities"],
        services=status["services"],
        controllers=status["controllers"],
        graph_relations=code_graph.relation_count(),
        metadata=status,
    )


@router.get("/config", response_model=RuntimeConfigResponse)
def get_config() -> RuntimeConfigResponse:
    return runtime_config.get(mask_secrets=True)


@router.put("/config", response_model=RuntimeConfigResponse)
def update_config(request: RuntimeConfig) -> RuntimeConfigResponse:
    if request.llm_provider not in {"mock", "openai", "ollama"}:
        raise HTTPException(status_code=400, detail="llm_provider deve ser mock, openai ou ollama.")
    updated = runtime_config.update(request)
    vector_index.settings.qdrant_url = updated.qdrant_url
    vector_index.settings.qdrant_collection = updated.qdrant_collection
    vector_index.settings.enable_vector_index = updated.enable_vector_index
    vector_index.enabled = updated.enable_vector_index
    settings.allowed_import_roots = updated.allowed_import_roots
    settings.max_import_size_mb = updated.max_import_size_mb
    settings.max_import_file_size_mb = updated.max_import_file_size_mb
    settings.decompiler = updated.decompiler
    settings.cfr_jar_path = updated.cfr_jar_path or None
    return updated


@router.post("/imports/zip", response_model=ImportJobResponse)
def import_zip(file: UploadFile = File(...), reset: bool = Form(True)) -> ImportJobResponse:
    try:
        log.info("Import request received: file=%s reset=%s", file.filename, reset)
        job = import_jobs.start_zip_import(file, reset=reset)
        return ImportJobResponse(**job.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset")
def reset_all() -> dict[str, str]:
    if import_jobs.has_active():
        raise HTTPException(status_code=409, detail="Existe importacao em andamento. Aguarde finalizar antes de resetar.")
    log.info("Reset requested.")
    reset_service.reset_all()
    _restore_runtime_defaults()
    return {"status": "reset", "message": "Todos os dados foram removidos e a aplicacao voltou ao estado inicial."}


@router.get("/imports/{job_id}", response_model=ImportJobStatus)
def import_status(job_id: str) -> ImportJobStatus:
    try:
        return import_jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Importacao nao encontrada.") from exc


@router.get("/graph/class/{class_name}", response_model=ClassGraphResponse)
def graph_class(class_name: str) -> ClassGraphResponse:
    symbols = repository.class_symbols(class_name)
    main = next((item for item in symbols if item.class_name == class_name and item.symbolType in {"class", "file"}), None)
    return ClassGraphResponse(
        className=class_name,
        superclass=main.superclass if main else None,
        genericArguments=main.genericArguments if main else [],
        fields=sorted({item.matchedSymbol or "" for item in symbols if item.symbolType in {"field", "constant"} and item.matchedSymbol}),
        methods=sorted({item.method_name or item.matchedSymbol or "" for item in symbols if item.symbolType == "method" and (item.method_name or item.matchedSymbol)}),
        sourceFiles=sorted({item.file_path for item in symbols if item.file_path}),
        relations=code_graph.class_relations(class_name),
    )


@router.get("/entities", response_model=list[EntitySummary])
def entities() -> list[EntitySummary]:
    return [
        EntitySummary(
            className=item.class_name or item.entity_name or item.matchedSymbol or item.file_path,
            tableName=item.table_name,
            filePath=item.file_path,
            artifactId=item.artifact_id,
            version=item.version,
            sourceType=item.source_type,
            superclass=item.superclass,
        )
        for item in repository.list_entities()
    ]


@router.get("/services", response_model=list[ServiceSummary])
def services() -> list[ServiceSummary]:
    return [
        ServiceSummary(
            className=item.class_name or item.matchedSymbol or item.file_path,
            layer=item.layer,
            filePath=item.file_path,
            artifactId=item.artifact_id,
            version=item.version,
            sourceType=item.source_type,
            superclass=item.superclass,
            genericSuperclass=item.genericSuperclass,
            genericArguments=item.genericArguments,
        )
        for item in repository.list_services()
    ]


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    log.info("Search request: query=%s mode=%s limit=%s", request.query, request.mode, request.limit)
    evidences = search_service.search(request.query, request.mode, request.limit)
    return SearchResponse(query=request.query, mode=request.mode, evidences=evidences)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    chat_service = ChatService(search_service, build_provider(runtime_config.get(mask_secrets=False)))
    message = request.message or request.question
    if not message:
        raise HTTPException(status_code=400, detail="message e obrigatorio.")
    top_k = request.topK or request.limit or 20
    return await chat_service.answer(
        message=message,
        top_k=top_k,
        conversation_id=request.conversationId,
        history=request.history,
        investigation_mode=request.investigationMode,
    )


@router.get("/logs", response_model=LogsResponse)
def logs(limit: int = 200, source: str = "backend") -> LogsResponse:
    if source == "backend":
        entries = [LogEntry(**item.__dict__) for item in get_log_handler().recent(limit)]
        return LogsResponse(source="backend", entries=entries)
    raise HTTPException(status_code=400, detail="Fonte de logs invalida.")


def _restore_runtime_defaults() -> None:
    settings.allowed_import_roots = default_settings.allowed_import_roots
    settings.llm_provider = default_settings.llm_provider
    settings.openai_api_key = default_settings.openai_api_key
    settings.openai_model = default_settings.openai_model
    settings.ollama_base_url = default_settings.ollama_base_url
    settings.ollama_model = default_settings.ollama_model
    settings.qdrant_url = default_settings.qdrant_url
    settings.qdrant_collection = default_settings.qdrant_collection
    settings.enable_vector_index = default_settings.enable_vector_index
    settings.max_import_size_mb = default_settings.max_import_size_mb
    settings.max_import_file_size_mb = default_settings.max_import_file_size_mb
    settings.decompiler = default_settings.decompiler
    settings.cfr_jar_path = default_settings.cfr_jar_path
    vector_index.settings.qdrant_url = default_settings.qdrant_url
    vector_index.settings.qdrant_collection = default_settings.qdrant_collection
    vector_index.settings.enable_vector_index = default_settings.enable_vector_index
    vector_index.enabled = default_settings.enable_vector_index
