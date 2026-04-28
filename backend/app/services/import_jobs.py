from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from pathlib import Path
from threading import Lock

from app.models.schemas import ImportJobStatus
from app.services.zip_importer import ZipImporter


class ImportJobManager:
    def __init__(self, importer: ZipImporter, data_dir: Path):
        self.importer = importer
        self.upload_dir = data_dir / "pending-imports"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="zip-import")
        self.jobs: dict[str, dict] = {}
        self.lock = Lock()
        self.log = logging.getLogger("code_support_agent.import_jobs")

    def start_zip_import(self, uploaded_file, reset: bool) -> ImportJobStatus:
        filename = Path(uploaded_file.filename or "codebase.zip").name
        if not filename.lower().endswith(".zip"):
            raise ValueError("Envie um arquivo .zip.")

        import_id = self.importer.new_import_id()
        job_id = import_id
        upload_path = (self.upload_dir / f"{job_id}-{filename}").resolve()
        self.importer._save_upload(uploaded_file.file, upload_path)

        started_at = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.jobs[job_id] = {
                "jobId": job_id,
                "importId": import_id,
                "status": "queued",
                "phase": "queued",
                "progress": 0,
                "current": 0,
                "total": 0,
                "message": "Importacao adicionada a fila.",
                "result": None,
                "error": None,
                "startedAt": started_at,
                "finishedAt": None,
            }
        self.log.info("Queued import job %s for %s", job_id, filename)

        self.executor.submit(self._run_job, job_id, import_id, upload_path, filename, reset)
        return self.get(job_id)

    def get(self, job_id: str) -> ImportJobStatus:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return ImportJobStatus(**job)

    def has_active(self) -> bool:
        with self.lock:
            return any(job["status"] in {"queued", "running"} for job in self.jobs.values())

    def clear(self) -> None:
        with self.lock:
            self.jobs.clear()

    def update(self, job_id: str, **values) -> None:
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(values)

    def _run_job(self, job_id: str, import_id: str, zip_path: Path, filename: str, reset: bool) -> None:
        try:
            self.update(job_id, status="running", phase="starting", progress=1, message="Iniciando processamento do ZIP.")

            def progress(phase: str, message: str, current: int = 0, total: int = 0, progress_value: int | None = None) -> None:
                value = progress_value if progress_value is not None else self._progress_from_counts(current, total)
                self.update(job_id, phase=phase, message=message, current=current, total=total, progress=value)

            result = self.importer.import_zip_path(zip_path, filename, reset=reset, import_id=import_id, progress=progress)
            self.log.info("Completed import job %s with status %s", job_id, result.message)
            self.update(
                job_id,
                status="completed",
                phase="completed",
                progress=100,
                message=result.message,
                result=result,
                finishedAt=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            self.log.exception("Import job %s failed", job_id)
            self.update(
                job_id,
                status="failed",
                phase="failed",
                progress=100,
                message=str(exc),
                error=str(exc),
                finishedAt=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            zip_path.unlink(missing_ok=True)

    def _progress_from_counts(self, current: int, total: int) -> int:
        if total <= 0:
            return 0
        return max(1, min(99, int((current / total) * 100)))
