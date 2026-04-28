from __future__ import annotations

from app.models.schemas import RuntimeConfig, RuntimeConfigResponse
from app.services.repository import CodeRepository


SECRET_MASK = "********"


class RuntimeConfigService:
    def __init__(self, repository: CodeRepository, defaults):
        self.repository = repository
        self.defaults = defaults

    def get(self, mask_secrets: bool = False) -> RuntimeConfig | RuntimeConfigResponse:
        stored = self.repository.get_settings()
        config = RuntimeConfig(
            allowed_import_roots=stored.get("allowed_import_roots", self.defaults.allowed_import_roots),
            max_import_size_mb=int(stored.get("max_import_size_mb", self.defaults.max_import_size_mb)),
            max_import_file_size_mb=int(stored.get("max_import_file_size_mb", self.defaults.max_import_file_size_mb)),
            decompiler=stored.get("decompiler", self.defaults.decompiler),
            cfr_jar_path=stored.get("cfr_jar_path", self.defaults.cfr_jar_path),
            llm_provider=stored.get("llm_provider", self.defaults.llm_provider),
            openai_api_key=stored.get("openai_api_key", self.defaults.openai_api_key),
            openai_model=stored.get("openai_model", self.defaults.openai_model),
            ollama_base_url=stored.get("ollama_base_url", self.defaults.ollama_base_url),
            ollama_model=stored.get("ollama_model", self.defaults.ollama_model),
            qdrant_url=stored.get("qdrant_url", self.defaults.qdrant_url),
            qdrant_collection=stored.get("qdrant_collection", self.defaults.qdrant_collection),
            enable_vector_index=self._to_bool(stored.get("enable_vector_index"), self.defaults.enable_vector_index),
        )
        if not mask_secrets:
            return config
        return RuntimeConfigResponse(
            **config.model_dump(exclude={"openai_api_key"}),
            openai_api_key=SECRET_MASK if config.openai_api_key else "",
            openai_api_key_set=bool(config.openai_api_key),
        )

    def update(self, config: RuntimeConfig) -> RuntimeConfigResponse:
        current = self.get(mask_secrets=False)
        openai_api_key = config.openai_api_key
        if openai_api_key == SECRET_MASK:
            openai_api_key = current.openai_api_key
        if openai_api_key == "":
            openai_api_key = None

        values = {
            "allowed_import_roots": config.allowed_import_roots,
            "max_import_size_mb": str(config.max_import_size_mb),
            "max_import_file_size_mb": str(config.max_import_file_size_mb),
            "decompiler": config.decompiler,
            "cfr_jar_path": config.cfr_jar_path or "",
            "llm_provider": config.llm_provider,
            "openai_model": config.openai_model,
            "ollama_base_url": config.ollama_base_url,
            "ollama_model": config.ollama_model,
            "qdrant_url": config.qdrant_url,
            "qdrant_collection": config.qdrant_collection,
            "enable_vector_index": str(config.enable_vector_index).lower(),
        }
        if openai_api_key is not None:
            values["openai_api_key"] = openai_api_key
        elif current.openai_api_key:
            values["openai_api_key"] = ""
        self.repository.set_settings(values)
        return self.get(mask_secrets=True)

    def _to_bool(self, value: str | None, default: bool) -> bool:
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "on"}
