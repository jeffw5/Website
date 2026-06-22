"""
chunking.py
===========
A small, dependency-free chunker. It splits on paragraph then sentence
boundaries, packs spans up to `chunk_size`, and carries `chunk_overlap`
characters of trailing context into the next chunk so claims that straddle a
boundary are not lost.

Swap this out for LangChain's RecursiveCharacterTextSplitter, a semantic
chunker, or a layout-aware splitter if your source documents need it — the
Extraction Agent only depends on the (text, char_start, char_end) tuples it
returns.
"""

from __future__ import annotations

import re
from typing import List, Tuple

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


def _split_sentences(paragraph: str) -> List[str]:
    parts = _SENTENCE_RE.split(paragraph)
    return [p for p in parts if p.strip()]


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[Tuple[str, int, int]]:
    """Return a list of (chunk_text, char_start, char_end) spans over `text`."""
    if not text.strip():
        return []

    # Build atomic units (sentences) with their absolute offsets.
    units: List[Tuple[str, int, int]] = []
    cursor = 0
    for para in re.split(r"\n\s*\n", text):
        if not para.strip():
            cursor += len(para) + 2
            continue
        para_start = text.find(para, cursor)
        local = para_start
        for sent in _split_sentences(para):
            s_start = text.find(sent, local)
            if s_start == -1:
                s_start = local
            s_end = s_start + len(sent)
            units.append((sent, s_start, s_end))
            local = s_end
        cursor = para_start + len(para)

    if not units:
        return [(text, 0, len(text))]

    chunks: List[Tuple[str, int, int]] = []
    cur: List[Tuple[str, int, int]] = []
    cur_len = 0

    def flush():
        if not cur:
            return
        start = cur[0][1]
        end = cur[-1][2]
        chunks.append((text[start:end], start, end))

    for unit in units:
        unit_len = unit[2] - unit[1]
        if cur_len + unit_len > chunk_size and cur:
            flush()
            # seed the next chunk with overlap from the tail of this one
            kept: List[Tuple[str, int, int]] = []
            acc = 0
            for u in reversed(cur):
                kept.insert(0, u)
                acc += u[2] - u[1]
                if acc >= overlap:
                    break
            cur = kept
            cur_len = acc
        cur.append(unit)
        cur_len += unit_len

    flush()
    return chunks
