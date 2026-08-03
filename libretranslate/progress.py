import os
import threading
import time

import argostranslatefiles
from argostranslate.translate import ITranslation

from libretranslate import pdf_file, text_file
from libretranslate.pdf_inspector_backend import (
    is_available as pdf_inspector_available, classify_pdf, extract_markdown
)
from libretranslate.abbreviations import get_abbreviation_processor
from libretranslate.glossary import get_glossary_processor


class JobCancelledError(Exception):
    """Raised inside a worker thread when the job is cancelled."""


class FileTranslationJob:
    """State of a single background file-translation job."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = "running"  # running | paused | done | cancelled | error
        self.progress = 0.0      # 0..100
        self.processed_chars = 0
        self.total_chars = 0
        self.speed = 0.0         # chars per second
        self.eta = None          # remaining seconds (or None while unknown)
        self.error = None
        self.phase = "translate"  # translate | assembly
        self.translated_file_path = None
        self.source_path = None
        self.created_at = time.time()
        self.finished_at = None
        self.pause_event = threading.Event()
        self.pause_event.set()  # set = running, cleared = paused
        self.cancel_event = threading.Event()


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
                "phase": job.phase,
                "processedChars": job.processed_chars,
                "totalChars": job.total_chars,
                "speed": round(job.speed, 1),
                "eta": round(job.eta, 1) if job.eta is not None else None,
                "error": job.error,
            }

    def get_object(self, job_id: str) -> FileTranslationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[FileTranslationJob]:
        with self._lock:
            return list(self._jobs.values())

    def pause(self, job_id: str) -> FileTranslationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status == "running":
                job.pause_event.clear()
                job.status = "paused"
            return job

    def resume(self, job_id: str) -> FileTranslationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status == "paused":
                job.pause_event.set()
                job.status = "running"
            return job

    def cancel(self, job_id: str) -> FileTranslationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.status in ("running", "paused"):
                job.cancel_event.set()
                job.pause_event.set()  # wake any waiter so it can notice the cancel
                job.status = "cancelled"
                job.finished_at = time.time()
            return job

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
        self._start_time = time.time()

    def _wait_if_paused(self):
        """Block until the job is running again or cancelled.

        Called between paragraphs so a paused job stops consuming CPU/GPU.
        """
        while not self.job.pause_event.is_set():
            if self.job.cancel_event.is_set():
                raise JobCancelledError()
            self.job.pause_event.wait(timeout=0.2)

    def translate(self, input_text: str) -> str:
        paragraphs = ITranslation.split_into_paragraphs(input_text)
        with job_store._lock:
            self.job.phase = "translate"

        translated = []
        abbr_processor = get_abbreviation_processor()
        glossary_processor = get_glossary_processor()
        for paragraph in paragraphs:
            self._wait_if_paused()
            if self.job.cancel_event.is_set():
                raise JobCancelledError()

            # Pre-processing: expand abbreviations
            processed_paragraph = abbr_processor.expand(paragraph)

            # Get glossary for this language pair
            glossary = glossary_processor.get_glossary(self.from_lang, self.to_lang)

            if glossary:
                translated_text = self.underlying.translate_with_glossary(processed_paragraph, glossary)
            else:
                translated_text = self.underlying.translate(processed_paragraph)

            translated.append(translated_text)
            with job_store._lock:
                self.job.processed_chars += len(paragraph)
                if self.job.total_chars > 0:
                    # The translate phase reports 0..95%. The last 5% is
                    # driven by the file-assembly phase (e.g. PDF
                    # redaction/writing) so the UI never sits on a stuck
                    # "100%" while the output is still being produced.
                    self.job.progress = min(
                        95.0, 100.0 * self.job.processed_chars / self.job.total_chars
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


def set_job_progress(job: FileTranslationJob | None, progress: float, eta=None):
    """Set progress (0..100) and optionally eta outside the translate phase.

    ``eta=None`` clears it so the UI does not show a stale "time left" while
    the file-assembly phase is still working.
    """
    if job is None:
        return
    with job_store._lock:
        job.progress = min(100.0, progress)
        job.eta = eta


def _argos_output_path(translation: ITranslation, filepath: str):
    for supported_format in argostranslatefiles.get_supported_formats():
        if supported_format.support(filepath):
            return supported_format.get_output_path(translation, filepath)
    return None


def _compute_total_chars(translation: ITranslation, filepath: str, codec: str) -> int:
    """Pre-compute the total number of characters to translate for the job.

    Computed once at job start so the progress bar moves 0 -> 100 honestly
    instead of jumping to 100 on the first call.
    """
    if text_file.is_text_file(filepath):
        return text_file.total_chars(filepath, codec)
    if pdf_file.is_pdf_file(filepath):
        return pdf_file.total_chars(filepath)
    for supported_format in argostranslatefiles.get_supported_formats():
        if supported_format.support(filepath):
            return sum(len(t) for t in supported_format.get_texts(filepath))
    return 0


def _remove_partial_output(translation: ITranslation, filepath: str):
    try:
        if text_file.is_text_file(filepath):
            outfile = text_file.get_output_path(translation, filepath)
        elif pdf_file.is_pdf_file(filepath):
            outfile = pdf_file.get_output_path(translation, filepath)
        else:
            outfile = _argos_output_path(translation, filepath)
        if outfile and os.path.isfile(outfile):
            os.remove(outfile)
    except OSError:
        pass


def _translate_pdf_to_markdown(translation: ITranslation, filepath: str) -> str:
    """Extract a PDF as Markdown (pdf-inspector) and translate it.

    The translated Markdown is written into the upload directory so the
    regular ``download_file`` endpoint can serve it as ``*_translated.md``.
    """
    import uuid

    markdown = extract_markdown(filepath)
    if not markdown:
        raise Exception("Failed to extract markdown from PDF")

    # ProgressTranslation.translate() expands abbreviations and applies the
    # glossary for the current language pair, then reports progress.
    translated_markdown = translation.translate(markdown)

    from libretranslate.app import get_upload_dir
    upload_dir = get_upload_dir()
    os.makedirs(upload_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(filepath))[0]
    out_name = str(uuid.uuid4()) + "_" + base + ".md"
    out_path = os.path.join(upload_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(translated_markdown)
    return out_path


def run_file_job(job_id: str, translation: ITranslation, filepath: str, codec: str = "auto", pdf_backend: str = "pymupdf"):
    """Translate a file in the background and store the outcome on the job."""
    job = job_store.get_object(job_id)
    if job is None:
        return
    with job_store._lock:
        job.source_path = filepath
    try:
        with job_store._lock:
            job.total_chars = _compute_total_chars(translation, filepath, codec)
    except Exception:
        pass  # keep 0; progress will jump to 100 when the job completes
    try:
        if pdf_file.is_pdf_file(filepath) and pdf_backend in ("pdf-inspector", "auto") and pdf_inspector_available():
            # pdf-inspector backend: extract Markdown and translate it.
            # Falls back to the pymupdf pipeline when the document is scanned
            # or the confidence is too low.
            classification = classify_pdf(filepath)
            if classification and classification["pdf_type"] in ("text_based", "mixed") and classification["confidence"] > 0.4:
                markdown = extract_markdown(filepath)
                if markdown:
                    translated_file_path = _translate_pdf_to_markdown(translation, filepath)
                else:
                    translated_file_path = pdf_file.translate_pdf(translation, filepath)
            else:
                translated_file_path = pdf_file.translate_pdf(translation, filepath)
        elif pdf_file.is_pdf_file(filepath):
            translated_file_path = pdf_file.translate_pdf(translation, filepath)
        elif text_file.is_text_file(filepath):
            translated_file_path = text_file.translate_text_file(
                translation, filepath, codec
            )
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
    except JobCancelledError:
        _remove_partial_output(translation, filepath)
        with job_store._lock:
            job.status = "cancelled"
            job.finished_at = time.time()
    except Exception as e:
        with job_store._lock:
            job.error = str(e)
            job.status = "error"
            job.finished_at = time.time()
