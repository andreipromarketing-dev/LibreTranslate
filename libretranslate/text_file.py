"""Codec-aware translation of plain-text file formats.

argostranslatefiles reads and writes .txt/.html/.srt using the locale
default encoding, which on Windows (cp1251) corrupts UTF-8 files. Here we
translate those formats ourselves with an explicit source codec (auto
detected via chardet) and always write UTF-8 output.
"""

import os
import textwrap

import chardet
import pysrt
from bs4 import BeautifulSoup

from argostranslatefiles import translatehtml
from argostranslate.translate import ITranslation

SUPPORTED_TEXT_EXTENSIONS = (".txt", ".html", ".htm", ".srt")

SUPPORTED_CODECS = [
    "auto",
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "cp1251",
    "cp1252",
    "koi8-r",
    "cp866",
    "iso-8859-5",
    "latin-1",
]

_PREVIEW_CHARS = 4096


def is_text_file(filepath: str) -> bool:
    ext = os.path.splitext(filepath)[1].lower()
    return ext in SUPPORTED_TEXT_EXTENSIONS


def is_supported_codec(codec: str) -> bool:
    return codec in SUPPORTED_CODECS


def get_supported_codecs():
    return list(SUPPORTED_CODECS)


def resolve_codec(filepath: str, codec: str = "auto") -> str:
    """Return a concrete codec name for reading the file.

    With ``auto`` the encoding is guessed with chardet from the file bytes,
    falling back to utf-8 when nothing reliable is detected.
    """
    if codec and codec != "auto":
        return codec

    with open(filepath, "rb") as f:
        raw = f.read(65536)

    detected = chardet.detect(raw)
    enc = detected.get("encoding")
    if enc:
        return enc
    return "utf-8"


def read_text(filepath: str, codec: str = "auto"):
    """Read the file content with an explicit codec.

    Returns a ``(text, used_codec)`` tuple. Decode errors are replaced so a
    wrong codec never crashes; it just produces mojibake (which the preview
    lets the user notice).
    """
    used_codec = resolve_codec(filepath, codec)
    with open(filepath, "rb") as f:
        raw = f.read()
    return raw.decode(used_codec, errors="replace"), used_codec


def get_output_path(underlying_translation: ITranslation, filepath: str) -> str:
    dir_path = os.path.dirname(filepath)
    file_name, file_ext = os.path.splitext(os.path.basename(filepath))
    to_code = underlying_translation.to_lang.code
    return dir_path + "/" + file_name + "_" + to_code + file_ext


def _srt_subs(filepath: str, codec: str = "auto"):
    used_codec = resolve_codec(filepath, codec)
    subs = pysrt.open(filepath, encoding=used_codec)
    return subs, used_codec


def translate_txt(underlying_translation: ITranslation, filepath: str, codec: str = "auto"):
    outfile_path = get_output_path(underlying_translation, filepath)

    text, _ = read_text(filepath, codec)
    translated_text = underlying_translation.translate(text)

    with open(outfile_path, "w", encoding="utf-8") as outfile:
        outfile.write(translated_text)

    return outfile_path


def translate_html(underlying_translation: ITranslation, filepath: str, codec: str = "auto"):
    outfile_path = get_output_path(underlying_translation, filepath)

    content, _ = read_text(filepath, codec)

    head = "<!DOCTYPE html>"
    head_present = content.startswith(head)
    if head_present:
        content = content[len(head):]

    translated = str(translatehtml.translate_html(underlying_translation, content))

    if head_present:
        translated = str(head) + translated

    with open(outfile_path, "w", encoding="utf-8") as outfile:
        outfile.write(translated)

    return outfile_path


def translate_srt(underlying_translation: ITranslation, filepath: str, codec: str = "auto"):
    outfile_path = get_output_path(underlying_translation, filepath)

    subs, _ = _srt_subs(filepath, codec)

    for sub in subs:
        cleaned_text = sub.text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        translated = underlying_translation.translate(cleaned_text)
        sub.text = textwrap.fill(translated, width=40)

    subs.save(outfile_path, encoding="utf-8")

    return outfile_path


def translate_text_file(underlying_translation: ITranslation, filepath: str, codec: str = "auto"):
    """Translate a text-based file, returning the output file path."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".srt":
        return translate_srt(underlying_translation, filepath, codec)
    if ext in (".html", ".htm"):
        return translate_html(underlying_translation, filepath, codec)
    return translate_txt(underlying_translation, filepath, codec)


def get_texts(filepath: str, codec: str = "auto"):
    """Return a ``(sample_text, used_codec)`` tuple for a text-based file.

    Used for language auto-detection and the translation preview. The sample
    is limited to a few thousand characters, mirroring argostranslatefiles.
    """
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".srt":
        subs, used_codec = _srt_subs(filepath, codec)
        text = "\n".join(sub.text for sub in subs)
        return text[:_PREVIEW_CHARS], used_codec

    if ext in (".html", ".htm"):
        content, used_codec = read_text(filepath, codec)
        soup = BeautifulSoup(content, "html.parser")
        return translatehtml.itag_of_soup(soup).text()[:_PREVIEW_CHARS], used_codec

    text, used_codec = read_text(filepath, codec)
    return text[:_PREVIEW_CHARS], used_codec


def total_chars(filepath: str, codec: str = "auto") -> int:
    """Total number of characters that will be translated (for progress)."""
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".srt":
        subs, _ = _srt_subs(filepath, codec)
        return sum(len(sub.text) for sub in subs)

    if ext in (".html", ".htm"):
        content, _ = read_text(filepath, codec)
        soup = BeautifulSoup(content, "html.parser")
        return len(translatehtml.itag_of_soup(soup).text())

    text, _ = read_text(filepath, codec)
    return len(text)
