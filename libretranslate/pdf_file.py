"""PDF file translation with repair of broken Unicode text layers.

Some PDFs exported from DTP tools (e.g. Adobe InDesign) use embedded fonts
with Identity-H encoding whose ToUnicode maps are missing or broken. Text
extraction then yields mojibake: Cyrillic glyphs come out as Latin Extended-B
/ IPA characters (e.g. ``Ʉɚɥɭɝɢɧ`` instead of ``Калугин``).

We detect such documents and repair the extracted text before it reaches the
translator:

* ``U+023A..U+02AE`` shifted by ``+0x1D6`` produce the correct Cyrillic letter
  (``Ʉ`` -> ``К``, ``ɚ`` -> ``а``, ...).
* ``U+0013..U+001C`` shifted by ``+0x1D`` produce the digits ``0``..``9``.
* Common typographic substitutions restore quotes and dashes.
* Other control characters become spaces.

The heuristic only triggers when the document is dominated by repairable
characters, so regular PDFs are untouched.
"""

import os

import pymupdf as fitz

from argostranslate.translate import ITranslation
from argostranslatefiles.formats.pdf import Pdf, PdfTranslator

_PREVIEW_CHARS = 4096

_REPAIR_CYRILLIC_LO = 0x023A
_REPAIR_CYRILLIC_HI = 0x02AE
_CYRILLIC_LO = 0x0401
_CYRILLIC_HI = 0x045F
_REPAIR_SHIFT = 0x1D6

_DIGIT_LO = 0x13
_DIGIT_HI = 0x1C
_DIGIT_SHIFT = 0x1D

_SPECIAL_MAP = {
    "\u00A9": "\u00AB",  # © -> «
    "\u00AA": "\u00BB",  # ª -> »
    "\u00B2": "\u2014",  # ² -> —
    "\u00B1": "\u2014",  # ± -> —
    "\u0087": "\u2022",  # -> •
    "\u028B": "\u2116",  # ʋ -> №
}

# Threshold for the share of repairable characters that marks a document as
# having a broken text layer.
_REPAIR_RATIO = 0.3


def needs_repair(text: str) -> bool:
    """Whether ``text`` looks like it comes from a broken Unicode text layer."""
    total = max(1, len(text))
    repairable = sum(
        1
        for ch in text
        if _REPAIR_CYRILLIC_LO <= ord(ch) <= _REPAIR_CYRILLIC_HI
        and _CYRILLIC_LO <= ord(ch) + _REPAIR_SHIFT <= _CYRILLIC_HI
    )
    return repairable > _REPAIR_RATIO * total and repairable > 10


def repair_text(text: str) -> str:
    """Repair a string extracted from a PDF with a broken Unicode text layer."""
    out = []
    for ch in text:
        o = ord(ch)
        if _REPAIR_CYRILLIC_LO <= o <= _REPAIR_CYRILLIC_HI:
            repaired = o + _REPAIR_SHIFT
            if _CYRILLIC_LO <= repaired <= _CYRILLIC_HI:
                out.append(chr(repaired))
                continue
        if _DIGIT_LO <= o <= _DIGIT_HI:
            out.append(chr(o + _DIGIT_SHIFT))
            continue
        if ch in _SPECIAL_MAP:
            out.append(_SPECIAL_MAP[ch])
            continue
        if o < 0x20 and ch not in "\n\t\r":
            out.append(" ")
            continue
        out.append(ch)
    return "".join(out)


def _repair_if_needed(text: str) -> str:
    return repair_text(text) if needs_repair(text) else text


def get_texts(filepath: str) -> str:
    """Extract a text sample (used for detection and the translation preview).

    Mirrors ``argostranslatefiles.get_texts`` but repairs broken text layers.
    """
    doc = fitz.open(filepath)
    try:
        parts = []
        count = 0
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            text = page.get_text().strip()
            if text:
                parts.append(text)
                count += len(text)
                if count >= _PREVIEW_CHARS:
                    break
        sample = " ".join(parts)[:_PREVIEW_CHARS]
        return _repair_if_needed(sample)
    finally:
        doc.close()


class RepairedPdfTranslator(PdfTranslator):
    """``PdfTranslator`` that repairs broken text layers before translation."""

    def _job(self):
        # ProgressTranslation exposes the backing job; base PdfTranslator is
        # used without a job (direct API calls), in which case there is none.
        return getattr(self.underlying_translation, "job", None)

    def _check_cancelled(self):
        job = self._job()
        if job is not None and job.cancel_event.is_set():
            from libretranslate.progress import JobCancelledError

            raise JobCancelledError()

    def _check_paused(self):
        job = self._job()
        if job is None:
            return
        from libretranslate.progress import JobCancelledError

        while not job.pause_event.is_set():
            if job.cancel_event.is_set():
                raise JobCancelledError()
            job.pause_event.wait(timeout=0.2)

    def translate_pdf(self):
        sample = []
        count = 0
        for page_num in range(min(10, self.doc.page_count)):
            text = self.doc.load_page(page_num).get_text().strip()
            if text:
                sample.append(text)
                count += len(text)
                if count >= _PREVIEW_CHARS:
                    break
        self._repair = needs_repair(" ".join(sample)[:_PREVIEW_CHARS])

        self._extract_text_from_pages()
        self._check_cancelled()
        self._translate_pages_data()
        self._check_cancelled()
        self._apply_translations_to_pdf()
        self._check_cancelled()
        self._save_translated_pdf()

    def _extract_text_with_pymupdf(self, page_num: int):
        self._check_paused()
        self._check_cancelled()

        while len(self.pages_data) <= page_num:
            self.pages_data.append([])

        page = self.doc.load_page(page_num)

        links = page.get_links()
        link_map = {}
        for link in links:
            rect = fitz.Rect(link["from"])
            link_map[rect] = {
                "uri": link.get("uri", ""),
                "page": link.get("page", -1),
                "to": link.get("to", None),
                "kind": link.get("kind", 0),
            }

        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span.get("text", "").strip()
                        if (
                            text
                            and not self._is_math(text, page_num, None)
                            and not self._is_non_text(text)
                        ):
                            if self._repair:
                                text = repair_text(text)
                            bbox = span.get("bbox", (0, 0, 0, 0))
                            font_size = span.get("size", 12)
                            font_flags = span.get("flags", 0)
                            color = span.get("color", 0)
                            is_bold = bool(font_flags & 2**4)
                            span_rect = fitz.Rect(bbox)
                            link_info = None
                            for link_rect, link_data in link_map.items():
                                if span_rect.intersects(link_rect):
                                    link_info = link_data
                                    break

                            self.pages_data[page_num].append(
                                [
                                    text,
                                    tuple(bbox),
                                    None,  # Translation placeholder
                                    0,  # Angle (rotation)
                                    self._decimal_to_hex_color(color),
                                    0,  # Text indent
                                    is_bold,
                                    font_size,
                                    link_info,  # Link information
                                ]
                            )

    def _translate_pages_data(self):
        # Same as the base PdfTranslator, but JobCancelledError (pause/stop)
        # must propagate instead of being swallowed by the base fallback that
        # silently keeps the original text and finishes the job as "done".
        from libretranslate.progress import JobCancelledError

        for page_blocks in self.pages_data:
            for block in page_blocks:
                try:
                    translated_text = self.underlying_translation.translate(block[0])
                except JobCancelledError:
                    raise
                except Exception:
                    # Keep the base behaviour for genuinely failing spans:
                    # leave the original text rather than aborting the book.
                    translated_text = block[0]
                block[2] = translated_text

    def _report_assembly_progress(self, done_pages: int, total_pages: int):
        job = self._job()
        if job is None or total_pages <= 0:
            return
        from libretranslate.progress import set_job_progress

        fraction = min(1.0, done_pages / total_pages)
        # Translate phase caps at 95%; assembly reports the remaining 5%.
        set_job_progress(job, 95.0 + fraction * 5.0)

    def _apply_translations_to_pdf(self):
        # Same layout logic as the base PdfTranslator, with:
        #  * pause/cancel checks per page (pause/stop free the CPU during this phase);
        #  * all redactions of a page batched into ONE apply_redactions() call
        #    (calling it per span re-processes the whole page every time and
        #    makes large documents take tens of minutes after translation);
        #  * progress reported per page so the bar moves 95% -> 100% instead of
        #    sitting on a stuck "100%".
        total_pages = len(self.pages_data)
        done_pages = 0

        for page_index, blocks in enumerate(self.pages_data):
            self._check_paused()
            self._check_cancelled()

            done_pages += 1

            if not blocks:
                self._report_assembly_progress(done_pages, total_pages)
                continue

            page = self.doc.load_page(page_index)

            normal_blocks = []
            bold_blocks = []
            redact_rects = []

            for block in blocks:
                coords = block[1]
                translated_text = block[2] if block[2] is not None else block[0]

                # Calculate expansion factor based on text length ratio
                len_ratio = min(1.05, max(1.01, len(translated_text) / max(1, len(block[0]))))

                x0, y0, x1, y1 = coords
                width = x1 - x0
                height = y1 - y0

                # Expand horizontally to accommodate longer text
                h_expand = (len_ratio - 1) * width
                x1 = x1 + h_expand

                # Reduce vertical coverage to be more precise
                vertical_margin = min(height * 0.1, 3)
                y0 = y0 + vertical_margin
                y1 = y1 - vertical_margin

                # Ensure minimum height
                if y1 - y0 < 10:
                    y_center = (coords[1] + coords[3]) / 2
                    y0 = y_center - 5
                    y1 = y_center + 5

                enlarged_coords = (x0, y0, x1, y1)
                redact_rects.append(fitz.Rect(*enlarged_coords))

                is_bold = len(block) > 6 and block[6]
                if is_bold:
                    bold_blocks.append((block, enlarged_coords))
                else:
                    normal_blocks.append((block, enlarged_coords))

            # Cover original text with white rectangles (batched).
            for rect in redact_rects:
                try:
                    page.add_redact_annot(rect)
                except Exception:
                    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            except Exception:
                for rect in redact_rects:
                    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

            self._insert_styled_text_blocks(page, normal_blocks, is_bold=False)
            self._insert_styled_text_blocks(page, bold_blocks, is_bold=True)

            self._report_assembly_progress(done_pages, total_pages)

    def _save_translated_pdf(self):
        self._check_paused()
        self._check_cancelled()
        new_doc = fitz.open()
        new_doc.insert_pdf(self.doc)
        self._check_cancelled()
        
        # 1. Save to original output_path (argostranslatefiles location)
        new_doc.save(self.output_path, garbage=4, deflate=True)
        
        # 2. Copy to upload_dir for web accessibility
        try:
            import shutil
            from libretranslate.app import get_upload_dir
            upload_dir = get_upload_dir()
            os.makedirs(upload_dir, exist_ok=True)
            
            # Generate user-friendly filename: original_translated.pdf
            original_name = os.path.basename(self.output_path)
            if '_' in original_name:
                parts = original_name.split('_', 1)
                if len(parts) == 2:
                    web_name = f"{parts[1].rsplit('.', 1)[0]}_translated.pdf"
                else:
                    web_name = f"translated_{original_name}"
            else:
                web_name = f"translated_{original_name}"
            
            web_path = os.path.join(upload_dir, web_name)
            shutil.copy2(self.output_path, web_path)
            
            # Store web path for frontend
            self.web_output_path = web_path
            self.web_filename = web_name
            print(f"[PDF] Saved to upload_dir: {web_path}")
        except Exception as e:
            print(f"[PDF] Warning: Could not copy to upload_dir: {e}")
            self.web_output_path = self.output_path
            self.web_filename = os.path.basename(self.output_path)
        
        new_doc.close()
        self.doc.close()


def translate_pdf(underlying_translation: ITranslation, filepath: str) -> str:
    """Translate a PDF, repairing broken text layers first."""
    outfile_path = Pdf().get_output_path(underlying_translation, filepath)

    translator = RepairedPdfTranslator(
        pdf_path=filepath,
        output_path=outfile_path,
        underlying_translation=underlying_translation,
    )
    translator.translate_pdf()

    # Return the web-accessible path (in upload_dir) for frontend download
    return getattr(translator, 'web_output_path', outfile_path)


def get_web_filename(filepath: str) -> str:
    """Generate user-friendly filename for web download: original_translated.pdf"""
    original_name = os.path.basename(filepath)
    if '_' in original_name:
        parts = original_name.split('_', 1)
        if len(parts) == 2:
            return f"{parts[1].rsplit('.', 1)[0]}_translated.pdf"
    return f"translated_{original_name}"


def is_pdf_file(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() == ".pdf"


def get_output_path(underlying_translation: ITranslation, filepath: str) -> str:
    """Output path produced by ``translate_pdf`` for the given input."""
    return Pdf().get_output_path(underlying_translation, filepath)


def total_chars(filepath: str) -> int:
    """Total number of characters that will be translated (for progress)."""
    doc = fitz.open(filepath)
    try:
        # Same repair detection as RepairedPdfTranslator.translate_pdf
        sample = []
        count = 0
        for page_num in range(min(10, doc.page_count)):
            text = doc.load_page(page_num).get_text().strip()
            if text:
                sample.append(text)
                count += len(text)
                if count >= _PREVIEW_CHARS:
                    break
        repair = needs_repair(" ".join(sample)[:_PREVIEW_CHARS])

        total = 0
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            for block in page.get_text("dict")["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span.get("text", "").strip()
                        if text:
                            total += len(repair_text(text) if repair else text)
        return total
    finally:
        doc.close()
