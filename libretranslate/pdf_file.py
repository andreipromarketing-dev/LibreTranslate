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
        super().translate_pdf()

    def _extract_text_with_pymupdf(self, page_num: int):
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


def translate_pdf(underlying_translation: ITranslation, filepath: str) -> str:
    """Translate a PDF, repairing broken text layers first."""
    outfile_path = Pdf().get_output_path(underlying_translation, filepath)

    translator = RepairedPdfTranslator(
        pdf_path=filepath,
        output_path=outfile_path,
        underlying_translation=underlying_translation,
    )
    translator.translate_pdf()

    return outfile_path


def is_pdf_file(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() == ".pdf"
