"""
Abbreviation dictionary with JSON file storage.
Pre-processing for translation pipeline.
"""
import json
import os
import re
import threading
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class AbbreviationEntry:
    id: int
    abbreviation: str
    expansion: str
    case_sensitive: bool
    created_at: str

class AbbreviationStore:
    """Thread-safe JSON file storage for abbreviations."""
    
    def __init__(self, filepath: Optional[str] = None):
        if filepath is None:
            base_dir = Path(__file__).parent.parent / "data"
            base_dir.mkdir(exist_ok=True)
            filepath = base_dir / "abbreviations.json"
        self.filepath = Path(filepath)
        self._lock = threading.RLock()
        self._entries: List[AbbreviationEntry] = []
        self._next_id = 1
        self.load()
    
    def load(self) -> None:
        with self._lock:
            if self.filepath.exists():
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self._entries = [
                        AbbreviationEntry(**e) for e in data.get('entries', [])
                    ]
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
    
    def list_all(self) -> List[AbbreviationEntry]:
        with self._lock:
            return list(self._entries)
    
    def get(self, entry_id: int) -> Optional[AbbreviationEntry]:
        with self._lock:
            for e in self._entries:
                if e.id == entry_id:
                    return e
            return None
    
    def create(self, abbreviation: str, expansion: str, case_sensitive: bool = False) -> AbbreviationEntry:
        with self._lock:
            entry = AbbreviationEntry(
                id=self._next_id,
                abbreviation=abbreviation,
                expansion=expansion,
                case_sensitive=case_sensitive,
                created_at=datetime.utcnow().isoformat() + 'Z'
            )
            self._next_id += 1
            self._entries.append(entry)
            self.save()
            return entry
    
    def update(self, entry_id: int, abbreviation: str, expansion: str, case_sensitive: bool) -> Optional[AbbreviationEntry]:
        with self._lock:
            for i, e in enumerate(self._entries):
                if e.id == entry_id:
                    self._entries[i] = AbbreviationEntry(
                        id=entry_id,
                        abbreviation=abbreviation,
                        expansion=expansion,
                        case_sensitive=case_sensitive,
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


# Глобальный синглтон
_abbreviation_store: Optional[AbbreviationStore] = None

def get_abbreviation_store() -> AbbreviationStore:
    global _abbreviation_store
    if _abbreviation_store is None:
        _abbreviation_store = AbbreviationStore()
    return _abbreviation_store


class AbbreviationProcessor:
    """Pre-processing for abbreviation expansion."""
    
    def __init__(self, store: Optional[AbbreviationStore] = None):
        self.store = store or get_abbreviation_store()
        self._compiled_patterns: Dict[int, tuple] = {}
        self._rebuild_patterns()
    
    def _rebuild_patterns(self) -> None:
        self._compiled_patterns = {}
        for entry in self.store.list_all():
            flags = 0 if entry.case_sensitive else re.IGNORECASE
            pattern = r'\b' + re.escape(entry.abbreviation) + r'\b'
            self._compiled_patterns[entry.id] = (re.compile(pattern, flags), entry.expansion)
    
    def reload(self) -> None:
        self._rebuild_patterns()
    
    def expand(self, text: str) -> str:
        if not text:
            return text
        for pattern, expansion in self._compiled_patterns.values():
            text = pattern.sub(expansion, text)
        return text


_abbreviation_processor: Optional[AbbreviationProcessor] = None

def get_abbreviation_processor() -> AbbreviationProcessor:
    global _abbreviation_processor
    if _abbreviation_processor is None:
        _abbreviation_processor = AbbreviationProcessor()
    return _abbreviation_processor


# CSV утилиты
def export_to_csv(store: AbbreviationStore) -> str:
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['abbreviation', 'expansion', 'case_sensitive'])
    for entry in store.list_all():
        writer.writerow([entry.abbreviation, entry.expansion, str(entry.case_sensitive).lower()])
    return output.getvalue()

def import_from_csv(store: AbbreviationStore, csv_content: str, skip_existing: bool = True) -> tuple[int, int]:
    import csv
    import io
    reader = csv.DictReader(io.StringIO(csv_content))
    added = skipped = 0
    existing = {e.abbreviation.lower() for e in store.list_all()}
    for row in reader:
        abbr = row.get('abbreviation', '').strip()
        exp = row.get('expansion', '').strip()
        case_sens = row.get('case_sensitive', 'false').lower() == 'true'
        if not abbr or not exp:
            continue
        if skip_existing and abbr.lower() in existing:
            skipped += 1
            continue
        store.create(abbr, exp, case_sens)
        existing.add(abbr.lower())
        added += 1
    return added, skipped