"""
Glossary/Terminology dictionary with JSON file storage.
Integrates with Argos translate_with_glossary.
"""
import json
import threading
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class GlossaryEntry:
    id: int
    source_term: str
    target_term: str
    source_lang: str
    target_lang: str
    case_sensitive: bool
    context: str
    created_at: str

class GlossaryStore:
    """Thread-safe JSON file storage for glossary."""
    
    def __init__(self, filepath: Optional[str] = None):
        if filepath is None:
            base_dir = Path(__file__).parent.parent / "data"
            base_dir.mkdir(exist_ok=True)
            filepath = base_dir / "glossary.json"
        self.filepath = Path(filepath)
        self._lock = threading.RLock()
        self._entries: List[GlossaryEntry] = []
        self._next_id = 1
        self.load()
    
    def load(self) -> None:
        with self._lock:
            if self.filepath.exists():
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self._entries = [GlossaryEntry(**e) for e in data.get('entries', [])]
                    self._next_id = max([e.id for e in self._entries], default=0) + 1
                except (json.JSONDecodeError, KeyError):
                    self._entries = []
                    self._next_id = 1
            else:
                self._entries = []
                self._next_id = 1
    
    def save(self) -> None:
        with self._lock:
            data = {
                'version': 1,
                'updated_at': datetime.utcnow().isoformat() + 'Z',
                'entries': [asdict(e) for e in self._entries]
            }
            tmp = self.filepath.with_suffix('.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.filepath)
    
    def list_all(self) -> List[GlossaryEntry]:
        with self._lock:
            return list(self._entries)
    
    def get(self, entry_id: int) -> Optional[GlossaryEntry]:
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    return e
            return None
    
    def list_for_pair(self, source_lang: str, target_lang: str) -> List[GlossaryEntry]:
        with self._lock:
            return [e for e in self._entries 
                    if e.source_lang == source_lang and e.target_lang == target_lang]
    
    def create(self, source_term: str, target_term: str, source_lang: str, 
               target_lang: str, case_sensitive: bool = False, context: str = "") -> GlossaryEntry:
        with self._lock:
            entry = GlossaryEntry(
                id=self._next_id,
                source_term=source_term,
                target_term=target_term,
                source_lang=source_lang,
                target_lang=target_lang,
                case_sensitive=case_sensitive,
                context=context,
                created_at=datetime.utcnow().isoformat() + 'Z'
            )
            self._next_id += 1
            self._entries.append(entry)
            self.save()
            return entry
    
    def update(self, entry_id: int, source_term: str, target_term: str,
               source_lang: str, target_lang: str, case_sensitive: bool, context: str) -> Optional[GlossaryEntry]:
        with self._lock:
            for i, e in enumerate(self._entries):
                if e.id == entry_id:
                    self._entries[i] = GlossaryEntry(
                        id=entry_id,
                        source_term=source_term,
                        target_term=target_term,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        case_sensitive=case_sensitive,
                        context=context,
                        created_at=e.created_at
                    )
                    self.save()
                    return self._entries[i]
            return None
    
    def delete(self, entry_id: int) -> bool:
        with self._lock:
            for i, e in enumerate(self._entries):
                if e.id == entry_id:
                    self._entries.pop(i)
                    self.save()
                    return True
            return False
    
    def clear_all(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries = []
            self._next_id = 1
            self.save()
            return count


_glossary_store: Optional[GlossaryStore] = None

def get_glossary_store() -> GlossaryStore:
    global _glossary_store
    if _glossary_store is None:
        _glossary_store = GlossaryStore()
    return _glossary_store


class GlossaryProcessor:
    """Builds glossary dict for Argos translate_with_glossary."""
    
    def __init__(self, store: Optional[GlossaryStore] = None):
        self.store = store or get_glossary_store()
        self._glossary_cache: Dict[tuple, dict] = {}
        self._rebuild_cache()
    
    def _rebuild_cache(self) -> None:
        self._glossary_cache = {}
        for entry in self.store.list_all():
            key = (entry.source_lang, entry.target_lang)
            if key not in self._glossary_cache:
                self._glossary_cache[key] = {}
            self._glossary_cache[key][entry.source_term] = entry.target_term
    
    def reload(self) -> None:
        self._rebuild_cache()
    
    def get_glossary(self, source_lang: str, target_lang: str) -> dict:
        return self._glossary_cache.get((source_lang, target_lang), {})


_glossary_processor: Optional[GlossaryProcessor] = None

def get_glossary_processor() -> GlossaryProcessor:
    global _glossary_processor
    if _glossary_processor is None:
        _glossary_processor = GlossaryProcessor()
    return _glossary_processor


# CSV утилиты для глоссария
def export_glossary_csv(store: GlossaryStore) -> str:
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['source_term', 'target_term', 'source_lang', 'target_lang', 'case_sensitive', 'context'])
    for entry in store.list_all():
        writer.writerow([entry.source_term, entry.target_term, entry.source_lang, 
                         entry.target_lang, str(entry.case_sensitive).lower(), entry.context])
    return output.getvalue()

def import_glossary_csv(store: GlossaryStore, csv_content: str, skip_existing: bool = True) -> tuple[int, int]:
    import csv
    import io
    reader = csv.DictReader(io.StringIO(csv_content))
    added = skipped = 0
    existing = {(e.source_term.lower(), e.source_lang, e.target_lang) for e in store.list_all()}
    for row in reader:
        src = row.get('source_term', '').strip()
        tgt = row.get('target_term', '').strip()
        src_lang = row.get('source_lang', '').strip()
        tgt_lang = row.get('target_lang', '').strip()
        case_sens = row.get('case_sensitive', 'false').lower() == 'true'
        context = row.get('context', '').strip()
        if not src or not tgt or not src_lang or not tgt_lang:
            continue
        key = (src.lower(), src_lang, tgt_lang)
        if skip_existing and key in existing:
            skipped += 1
            continue
        store.create(src, tgt, src_lang, tgt_lang, case_sens, context)
        existing.add((src.lower(), src_lang, tgt_lang))
        added += 1
    return added, skipped