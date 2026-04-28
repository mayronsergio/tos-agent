from __future__ import annotations

from pathlib import Path

from app.indexing.extractors import extract_symbols, is_supported
from app.services.repository import CodeRepository
from app.services.vector_index import VectorIndex


class CodeIndexer:
    def __init__(self, repository: CodeRepository, vector_index: VectorIndex, allowed_roots: list[Path]):
        self.repository = repository
        self.vector_index = vector_index
        self.allowed_roots = allowed_roots

    def validate_path(self, import_path: str) -> Path:
        path = Path(import_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Pasta nao encontrada: {path}")
        if self.allowed_roots and not any(path == root or root in path.parents for root in self.allowed_roots):
            roots = ", ".join(str(root) for root in self.allowed_roots)
            raise ValueError(f"Pasta fora das raizes permitidas: {roots}")
        return path

    def index_folder(self, import_path: str, reset: bool = True, context: dict | None = None) -> dict:
        root = self.validate_path(import_path)
        if reset:
            self.repository.reset()

        imported = 0
        skipped = 0
        symbols_count = 0
        for path in root.rglob("*"):
            if not is_supported(path):
                if path.is_file():
                    skipped += 1
                continue
            symbols = extract_symbols(path, root, context=context)
            rel = str(path.relative_to(root)).replace("\\", "/")
            self.repository.upsert_file(rel)
            symbols_count += self.repository.insert_symbols(symbols)
            imported += 1

        self.vector_index.rebuild(self.repository.all_snippets())
        return {"imported_files": imported, "indexed_symbols": symbols_count, "skipped_files": skipped}
