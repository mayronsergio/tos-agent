from __future__ import annotations

import shutil
from pathlib import Path

from app.services.chat import clear_conversations
from app.services.import_jobs import ImportJobManager
from app.services.repository import CodeRepository
from app.services.vector_index import VectorIndex


class ResetService:
    def __init__(
        self,
        repository: CodeRepository,
        vector_index: VectorIndex,
        import_jobs: ImportJobManager,
        data_dir: Path,
    ):
        self.repository = repository
        self.vector_index = vector_index
        self.import_jobs = import_jobs
        self.data_dir = data_dir

    def reset_all(self) -> dict[str, int]:
        self.repository.reset()
        self.repository.clear_settings()
        self.vector_index.clear()
        clear_conversations()
        self.import_jobs.clear()

        removed_dirs = 0
        for relative in ("imports", "pending-imports"):
            target = (self.data_dir / relative).resolve()
            if target.exists():
                shutil.rmtree(target)
                removed_dirs += 1
            target.mkdir(parents=True, exist_ok=True)
        return {"removed_dirs": removed_dirs}
