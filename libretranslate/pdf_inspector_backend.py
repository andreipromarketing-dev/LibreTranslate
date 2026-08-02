"""
PDF backend using pdf-inspector for enhanced extraction.
Falls back gracefully if not installed or on error.
"""
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Global flag for availability
_PDF_INSPECTOR_AVAILABLE = False
_pdf_inspector = None

def _try_import_pdf_inspector() -> bool:
    """Try to import pdf-inspector, return availability."""
    global _PDF_INSPECTOR_AVAILABLE, _pdf_inspector
    if _PDF_INSPECTOR_AVAILABLE:
        return True
    try:
        import pdf_inspector
        _pdf_inspector = pdf_inspector
        _PDF_INSPECTOR_AVAILABLE = True
        return True
    except ImportError:
        _PDF_INSPECTOR_AVAILABLE = False
        return False

def is_available() -> bool:
    """Check if pdf-inspector is available."""
    return _try_import_pdf_inspector()

def classify_pdf(filepath: str) -> Optional[Dict[str, Any]]:
    """Fast PDF classification. Returns None if unavailable."""
    if not _try_import_pdf_inspector():
        return None
    try:
        result = _pdf_inspector.classify_pdf(filepath)
        return {
            "pdf_type": result.pdf_type,  # "text_based", "scanned", "image_based", "mixed"
            "confidence": result.confidence,  # 0.0 - 1.0
            "page_count": result.page_count,
            "pages_needing_ocr": result.pages_needing_ocr,  # 0-indexed
        }
    except Exception as e:
        logger.warning(f"pdf-inspector classification failed: {e}")
        return None

def extract_markdown(filepath: str, pages: Optional[List[int]] = None) -> Optional[str]:
    """Extract Markdown from PDF. Returns None if unavailable or not text-based."""
    if not _try_import_pdf_inspector():
        return None
    try:
        # pages are 1-indexed in our API, pdf-inspector expects 0-indexed
        pdf_pages = [p - 1 for p in pages] if pages else None
        result = _pdf_inspector.process_pdf(filepath, pages=pdf_pages)
        if result.pdf_type in ("text_based", "mixed") and result.confidence > 0.4:
            return result.markdown
        return None
    except Exception as e:
        logger.warning(f"pdf-inspector extraction failed: {e}")
        return None

def extract_text_with_positions(filepath: str, pages: Optional[List[int]] = None) -> Optional[List[Dict]]:
    """Extract text items with position/font info."""
    if not _try_import_pdf_inspector():
        return None
    try:
        pdf_pages = [p - 1 for p in pages] if pages else None
        items = _pdf_inspector.extract_text_with_positions(filepath, pages=pdf_pages)
        return [
            {
                "text": item.text,
                "x": item.x, "y": item.y,
                "width": item.width, "height": item.height,
                "font": item.font, "font_size": item.font_size,
                "page": item.page + 1,  # Convert to 1-indexed
                "is_bold": item.is_bold, "is_italic": item.is_italic,
                "is_underline": item.is_underline, "is_strikeout": item.is_strikeout,
                "item_type": item.item_type,
            }
            for item in items
        ]
    except Exception as e:
        logger.warning(f"pdf-inspector position extraction failed: {e}")
        return None