"""Convert office documents (doc/docx/odt/rtf/epub/xls/xlsx/csv/ppt/pptx)
to Markdown using the optional firecrawl-anydoc backend.

The import is lazy so the server starts fine even when anydoc is missing;
in that case ``is_anydoc_available()`` returns False.
"""

OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".odt",
    ".rtf",
    ".epub",
    ".xls",
    ".xlsx",
    ".csv",
    ".ppt",
    ".pptx",
}

_anydoc = None


def _load_anydoc():
    global _anydoc
    if _anydoc is None:
        try:
            import anydoc
            _anydoc = anydoc
        except Exception:
            _anydoc = False
    return _anydoc


def is_anydoc_available() -> bool:
    return bool(_load_anydoc())


def is_document_file(filepath: str) -> bool:
    ext = None
    try:
        ext = filepath.rsplit(".", 1)[-1].lower()
    except Exception:
        return False
    return ("." + ext) in OFFICE_EXTENSIONS


def extract_document_markdown(filepath: str) -> str:
    anydoc = _load_anydoc()
    if not anydoc:
        raise RuntimeError(
            "anydoc backend not available. Install with: pip install firecrawl-anydoc"
        )
    markdown = anydoc.to_markdown(filepath)
    if not markdown:
        raise RuntimeError("Failed to extract markdown from document")
    return markdown