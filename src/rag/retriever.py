"""
EMS Knowledge Base Retriever for RAG
Parses and searches energy-ai-assistant-reference.md
"""

import os
import re
from typing import Dict, List, Optional
from src.core.config import settings

from src.core.normalizers import is_fuzzy_match

class EMSKnowledgeBase:
    def __init__(self, doc_paths: Optional[List[str]] = None):
        if doc_paths is None:
            self.doc_paths = [settings.REFERENCE_DOC_PATH, "EMS_DATA_COMPONENTS_AND_RULES.md"]
            components_dir = "docs/components"
            if os.path.exists(components_dir):
                for f in sorted(os.listdir(components_dir)):
                    if f.endswith(".md"):
                        self.doc_paths.append(os.path.join(components_dir, f))
        else:
            self.doc_paths = doc_paths
        self.sections: List[Dict[str, str]] = []
        for path in self.doc_paths:
            self._load_document(path)

    def _load_document(self, path: str):
        if not os.path.exists(path):
            return

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split by top-level headers (# 1., # 2., etc.)
        pattern = r"(^#+ .+$)"
        splits = re.split(pattern, content, flags=re.MULTILINE)

        current_header = f"Introduction ({os.path.basename(path)})"
        current_body = []

        for part in splits:
            part = part.strip()
            if not part:
                continue
            if part.startswith("#"):
                if current_body:
                    self.sections.append({
                        "header": current_header,
                        "content": "\n".join(current_body),
                        "source": path
                    })
                    current_body = []
                current_header = f"{part.lstrip('#').strip()} ({os.path.basename(path)})"
            else:
                current_body.append(part)

        if current_body:
            self.sections.append({
                "header": current_header,
                "content": "\n".join(current_body),
                "source": path
            })

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, str]]:
        """Keyword-ranked and typo-tolerant search across reference sections."""
        query_words = set(query.lower().split())
        scored_sections = []

        for sec in self.sections:
            text = f"{sec['header']} {sec['content']}".lower()
            matches = sum(2 for w in query_words if w in text)
            # Typo-tolerant fuzzy fallback if exact word not found
            if matches == 0:
                header_words = sec['header'].lower().split()
                if any(any(is_fuzzy_match(qw, hw, cutoff=0.75) for hw in header_words) for qw in query_words):
                    matches += 1

            if matches > 0:
                scored_sections.append((matches, sec))

        scored_sections.sort(key=lambda x: x[0], reverse=True)
        return [sec for _, sec in scored_sections[:top_k]]

ems_kb = EMSKnowledgeBase()
