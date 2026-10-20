"""
EMS Knowledge Base Retriever for RAG
Parses and searches energy-ai-assistant-reference.md
"""

import os
import re
from typing import Dict, List
from src.core.config import settings

class EMSKnowledgeBase:
    def __init__(self, doc_path: str = settings.REFERENCE_DOC_PATH):
        self.doc_path = doc_path
        self.sections: List[Dict[str, str]] = []
        self._load_document()

    def _load_document(self):
        if not os.path.exists(self.doc_path):
            return

        with open(self.doc_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Split by top-level headers (# 1., # 2., etc.)
        pattern = r"(^#+ .+$)"
        splits = re.split(pattern, content, flags=re.MULTILINE)

        current_header = "Introduction"
        current_body = []

        for part in splits:
            part = part.strip()
            if not part:
                continue
            if part.startswith("#"):
                if current_body:
                    self.sections.append({
                        "header": current_header,
                        "content": "\n".join(current_body)
                    })
                    current_body = []
                current_header = part.lstrip("#").strip()
            else:
                current_body.append(part)

        if current_body:
            self.sections.append({
                "header": current_header,
                "content": "\n".join(current_body)
            })

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, str]]:
        """Keyword-ranked search across reference sections."""
        query_words = set(query.lower().split())
        scored_sections = []

        for sec in self.sections:
            text = f"{sec['header']} {sec['content']}".lower()
            matches = sum(1 for w in query_words if w in text)
            if matches > 0:
                scored_sections.append((matches, sec))

        scored_sections.sort(key=lambda x: x[0], reverse=True)
        return [sec for _, sec in scored_sections[:top_k]]

ems_kb = EMSKnowledgeBase()
