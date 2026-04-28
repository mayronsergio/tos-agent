from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    text = "text"
    semantic = "semantic"
    hybrid = "hybrid"


class Evidence(BaseModel):
    file_path: str
    fileName: str | None = None
    filePath: str | None = None
    artifact_id: str | None = None
    version: str | None = None
    source_type: str | None = None
    language: str | None = None
    package: str | None = None
    class_name: str | None = None
    superclass: str | None = None
    genericSuperclass: str | None = None
    genericArguments: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    overriddenMethods: list[str] = Field(default_factory=list)
    inheritedMethods: list[str] = Field(default_factory=list)
    sourceFileOfSuperclass: str | None = None
    genericClass: str | None = None
    relatedEntity: str | None = None
    relatedServiceActivity: str | None = None
    relationFromGraph: str | None = None
    attributeType: str | None = None
    attributeAnnotations: list[str] = Field(default_factory=list)
    method_name: str | None = None
    entity_name: str | None = None
    layer: str | None = None
    table_name: str | None = None
    message: str | None = None
    validation: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    snippet: str
    tags: list[str] = Field(default_factory=list)
    score: float = 0
    finalScore: float = 0
    semanticScore: float = 0
    textScore: float = 0
    symbolScore: float = 0
    matchType: str = "textual"
    matchedSymbol: str | None = None
    reason: str = ""
    symbolType: str | None = None


class ZipImportResponse(BaseModel):
    importId: str
    originalFilename: str
    metadataPath: str
    processedArtifacts: int = 0
    skippedArtifacts: int = 0
    decompiled: bool = False
    importedFiles: int
    indexedSymbols: int
    skippedFiles: int
    extractedFiles: int
    errors: list[str] = Field(default_factory=list)
    message: str


class ImportJobResponse(BaseModel):
    jobId: str
    importId: str
    status: str
    phase: str
    progress: int = 0
    message: str = ""


class ImportJobStatus(ImportJobResponse):
    current: int = 0
    total: int = 0
    result: ZipImportResponse | None = None
    error: str | None = None
    startedAt: str
    finishedAt: str | None = None


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class LogsResponse(BaseModel):
    source: str
    entries: list[LogEntry]


class SearchRequest(BaseModel):
    query: str
    mode: SearchMode = SearchMode.hybrid
    limit: int = Field(default=20, ge=1, le=100)


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode
    evidences: list[Evidence]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str | None = None
    question: str | None = None
    conversationId: str | None = None
    history: list[ChatMessage] = Field(default_factory=list)
    topK: int | None = Field(default=20, ge=1, le=60)
    limit: int | None = Field(default=None, ge=1, le=60)
    investigationMode: bool = False


class ChatEvidence(Evidence):
    reason: str = ""
    evidenceType: str = "regra de negócio"


class ChatResponse(BaseModel):
    answer: str
    confidence: str = "low"
    intent: str = "GENERIC"
    evidences: list[ChatEvidence]
    suggestedFollowUp: str = ""
    assumptions: list[str] = Field(default_factory=list)
    risk_alerts: list[str] = Field(default_factory=list)


class IndexStatus(BaseModel):
    indexed_files: int
    indexed_symbols: int
    indexed_chunks: int = 0
    entities: int = 0
    services: int = 0
    controllers: int = 0
    graph_relations: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphRelation(BaseModel):
    type: str
    source: str
    target: str
    filePath: str | None = None
    methodName: str | None = None
    reason: str = ""


class ClassGraphResponse(BaseModel):
    className: str
    superclass: str | None = None
    genericArguments: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    sourceFiles: list[str] = Field(default_factory=list)
    relations: list[GraphRelation]


class EntitySummary(BaseModel):
    className: str
    tableName: str | None = None
    filePath: str
    artifactId: str | None = None
    version: str | None = None
    sourceType: str | None = None
    superclass: str | None = None


class ServiceSummary(BaseModel):
    className: str
    layer: str | None = None
    filePath: str
    artifactId: str | None = None
    version: str | None = None
    sourceType: str | None = None
    superclass: str | None = None
    genericSuperclass: str | None = None
    genericArguments: list[str] = Field(default_factory=list)


class RuntimeConfig(BaseModel):
    allowed_import_roots: str = "/data/imports"
    max_import_size_mb: int = 5000
    max_import_file_size_mb: int = 512
    decompiler: str = "cfr"
    cfr_jar_path: str | None = None
    llm_provider: str = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "code_support_agent"
    enable_vector_index: bool = True


class RuntimeConfigResponse(RuntimeConfig):
    openai_api_key_set: bool = False
