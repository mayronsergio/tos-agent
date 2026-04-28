from __future__ import annotations

from app.models.schemas import Evidence


class VectorIndex:
    """Thin LlamaIndex/Qdrant adapter with graceful fallback for local tests."""

    def __init__(self, settings):
        self.settings = settings
        self.enabled = bool(settings.enable_vector_index)
        self._index = None

    def rebuild(self, evidences: list[Evidence]) -> None:
        if not self.enabled or not evidences:
            return
        try:
            from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
            from llama_index.embeddings.fastembed import FastEmbedEmbedding
            from llama_index.vector_stores.qdrant import QdrantVectorStore
            import qdrant_client

            client = qdrant_client.QdrantClient(url=self.settings.qdrant_url)
            vector_store = QdrantVectorStore(client=client, collection_name=self.settings.qdrant_collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            Settings.embed_model = FastEmbedEmbedding(model_name="BAAI/bge-small-en-v1.5")
            Settings.llm = None
            documents = [
                Document(
                    text=evidence.snippet,
                    metadata={
                        "file_path": evidence.file_path,
                        "artifact_id": evidence.artifact_id,
                        "version": evidence.version,
                        "source_type": evidence.source_type,
                        "language": evidence.language,
                        "package": evidence.package,
                        "class_name": evidence.class_name,
                        "method_name": evidence.method_name,
                        "entity_name": evidence.entity_name,
                        "layer": evidence.layer,
                        "table_name": evidence.table_name,
                        "message": evidence.message,
                        "validation": evidence.validation,
                        "line_start": evidence.line_start,
                        "line_end": evidence.line_end,
                        "tags": ",".join(evidence.tags),
                    },
                )
                for evidence in evidences
            ]
            self._index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
        except Exception:
            self._index = None

    def clear(self) -> None:
        self._index = None
        if not self.enabled:
            return
        try:
            import qdrant_client

            client = qdrant_client.QdrantClient(url=self.settings.qdrant_url)
            client.delete_collection(collection_name=self.settings.qdrant_collection)
        except Exception:
            return

    def search(self, query: str, limit: int) -> list[Evidence]:
        if self._index is None:
            return []
        try:
            retriever = self._index.as_retriever(similarity_top_k=limit)
            nodes = retriever.retrieve(query)
            results: list[Evidence] = []
            for node in nodes:
                meta = node.metadata or {}
                results.append(
                    Evidence(
                        file_path=str(meta.get("file_path", "")),
                        artifact_id=meta.get("artifact_id"),
                        version=meta.get("version"),
                        source_type=meta.get("source_type"),
                        language=meta.get("language"),
                        package=meta.get("package"),
                        class_name=meta.get("class_name"),
                        method_name=meta.get("method_name"),
                        entity_name=meta.get("entity_name"),
                        layer=meta.get("layer"),
                        table_name=meta.get("table_name"),
                        message=meta.get("message"),
                        validation=meta.get("validation"),
                        line_start=meta.get("line_start"),
                        line_end=meta.get("line_end"),
                        snippet=node.get_text(),
                        tags=[tag for tag in str(meta.get("tags", "")).split(",") if tag],
                        score=float(node.score or 0),
                    )
                )
            return results
        except Exception:
            return []
