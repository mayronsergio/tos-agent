from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Code Support Agent"
    data_dir: Path = Path("data")
    allowed_import_roots: str = "/data/imports"
    llm_provider: Literal["mock", "openai", "ollama"] = "mock"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.1"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "code_support_agent"
    enable_vector_index: bool = True
    max_import_size_mb: int = 5000
    max_import_file_size_mb: int = 512
    decompiler: str = "cfr"
    cfr_jar_path: str | None = None
    java_analysis_worker_command: str | None = None
    java_analysis_worker_timeout_seconds: int = 120

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "code_support_agent.sqlite3"

    @property
    def roots(self) -> list[Path]:
        return [Path(item).resolve() for item in self.allowed_import_roots.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings(
        app_name=os.getenv("APP_NAME", "Code Support Agent"),
        data_dir=Path(os.getenv("DATA_DIR", "data")),
        allowed_import_roots=os.getenv("ALLOWED_IMPORT_ROOTS", "/data/imports"),
        llm_provider=os.getenv("LLM_PROVIDER", "mock"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "code_support_agent"),
        enable_vector_index=os.getenv("ENABLE_VECTOR_INDEX", "true").lower() in {"1", "true", "yes", "on"},
        max_import_size_mb=int(os.getenv("MAX_IMPORT_SIZE_MB", "5000")),
        max_import_file_size_mb=int(os.getenv("MAX_IMPORT_FILE_SIZE_MB", "512")),
        decompiler=os.getenv("DECOMPILER", "cfr"),
        cfr_jar_path=os.getenv("CFR_JAR_PATH") or None,
        java_analysis_worker_command=os.getenv("JAVA_ANALYSIS_WORKER_COMMAND") or None,
        java_analysis_worker_timeout_seconds=int(os.getenv("JAVA_ANALYSIS_WORKER_TIMEOUT_SECONDS", "120")),
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
