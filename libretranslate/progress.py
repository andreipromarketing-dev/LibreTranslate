import threading
import time

import argostranslatefiles
from argostranslate.translate import ITranslation

from libretranslate import pdf_file, text_file


class FileTranslationJob:
    """State of a single background file-translation job."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = "running"  # running | done | error
        self.progress = 0.0      # 0..100
        self.processed_chars = 0
        self.total_chars = 0
        self.speed = 0.0         # chars per second
        self.eta = None          # remaining seconds (or None while unknown)
        self.error = None
        self.translated_file_path = None
        self.created_at = time.time()
        self.finished_at = None


class JobStore:
    """Thread-safe in-memory store of translation jobs."""

    def __init__(self, ttl: int = 3600):
        self._jobs = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def create(self, job_id: str) -> FileTranslationJob:
        job = FileTranslationJob(job_id)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "jobId": job.job_id,
                "status": job.status,
                "progress": round(min(100.0, job.progress), 1),
                "processedChars": job.processed_chars,
                "totalChars": job.total_chars,
                "speed": round(job.speed, 1),
                "eta": round(job.eta, 1) if job.eta is not None else None,
                "error": job.error,
            }

    def get_object(self, job_id: str) -> FileTranslationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cleanup(self):
        now = time.time()
        with self._lock:
            for job_id in list(self._jobs.keys()):
                job = self._jobs[job_id]
                if (
                    job.status != "running"
                    and job.finished_at is not None
                    and now - job.finished_at > self._ttl
                ):
                    del self._jobs[job_id]


job_store = JobStore()


class ProgressTranslation(ITranslation):
    """Wrapper that reports live progress to a FileTranslationJob.

    The underlying translation is called paragraph by paragraph, exactly like
    the Argos CachedTranslation already does internally, so the translated
    output is identical to a non-wrapped run.
    """

    def __init__(self, underlying: ITranslation, job: FileTranslationJob):
        self.underlying = underlying
        self.from_lang = underlying.from_lang
        self.to_lang = underlying.to_lang
        self.job = job
        self._start_time = None

    def translate(self, input_text: str) -> str:
        paragraphs = ITranslation.split_into_paragraphs(input_text)
        total_len = sum(len(p) for p in paragraphs)

        with job_store._lock:
            if self._start_time is None:
                self._start_time = time.time()
            self.job.total_chars += total_len

        translated = []
        for paragraph in paragraphs:
            translated.append(self.underlying.translate(paragraph))
            with job_store._lock:
                self.job.processed_chars += len(paragraph)
                if self.job.total_chars > 0:
                    self.job.progress = min(
                        100.0, 100.0 * self.job.processed_chars / self.job.total_chars
                    )
                elapsed = time.time() - self._start_time
                if elapsed > 0:
                    self.job.speed = self.job.processed_chars / elapsed
                    remaining = self.job.total_chars - self.job.processed_chars
                    if self.job.speed > 0 and remaining > 0:
                        self.job.eta = remaining / self.job.speed
                    else:
                        self.job.eta = None

        return "\n".join(translated)


def fail_job(job_id: str, error: str):
    job = job_store.get_object(job_id)
    if job is None:
        return
    with job_store._lock:
        job.error = str(error)
        job.status = "error"
        job.finished_at = time.time()


def run_file_job(job_id: str, translation: ITranslation, filepath: str, codec: str = "auto"):
    """Translate a file in the background and store the outcome on the job."""
    job = job_store.get_object(job_id)
    if job is None:
        return
    try:
        if text_file.is_text_file(filepath):
            translated_file_path = text_file.translate_text_file(
                translation, filepath, codec
            )
        elif pdf_file.is_pdf_file(filepath):
            translated_file_path = pdf_file.translate_pdf(translation, filepath)
        else:
            translated_file_path = argostranslatefiles.translate_file(
                translation, filepath
            )
        with job_store._lock:
            job.translated_file_path = translated_file_path
            job.status = "done"
            job.progress = 100.0
            job.eta = 0
            job.finished_at = time.time()
    except Exception as e:
        with job_store._lock:
            job.error = str(e)
            job.status = "error"
            job.finished_at = time.time()
