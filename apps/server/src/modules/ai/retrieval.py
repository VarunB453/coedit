import re
from collections import Counter
from math import log

from django.db.models import OuterRef, Subquery

from editor.models import DocumentVersion, FileEntry

MAX_WORKSPACE_DOCUMENTS = 500
MAX_DOCUMENT_TEXT = 60_000
CHUNK_SIZE = 1_200
MAX_SOURCES = 6
TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class WorkspaceTooLargeError(Exception):
    pass


def _node_text(node, remaining):
    if remaining[0] <= 0:
        return ""
    if isinstance(node, dict):
        if node.get("type") == "text":
            text = node.get("text", "")
            if not isinstance(text, str):
                return ""
            text = text[:remaining[0]]
            remaining[0] -= len(text)
            return text
        children = node.get("content")
        if isinstance(children, list):
            parts = []
            for child in children:
                text = _node_text(child, remaining)
                if text:
                    parts.append(text)
                if remaining[0] <= 0:
                    break
            separator = "\n" if node.get("type") in {
                "doc", "paragraph", "heading", "blockquote", "bulletList",
                "orderedList", "listItem", "codeBlock", "callout",
            } else ""
            return separator.join(parts)
    elif isinstance(node, list):
        return _node_text({"type": "doc", "content": node}, remaining)
    return ""


def extract_document_text(content):
    return _node_text(content, [MAX_DOCUMENT_TEXT]).strip()


def _chunks(text):
    for paragraph in text.splitlines():
        remaining = paragraph.strip()
        while remaining:
            if len(remaining) <= CHUNK_SIZE:
                yield remaining
                break
            split_at = remaining.rfind(" ", 0, CHUNK_SIZE)
            if split_at < CHUNK_SIZE // 2:
                split_at = CHUNK_SIZE
            yield remaining[:split_at].strip()
            remaining = remaining[split_at:].strip()


def retrieve_workspace_context(workspace_id, query, limit=MAX_SOURCES):
    documents = FileEntry.objects.filter(
        workspace_id=workspace_id, kind=FileEntry.Kind.FILE
    )
    if documents.count() > MAX_WORKSPACE_DOCUMENTS:
        raise WorkspaceTooLargeError

    latest_snapshot = Subquery(
        DocumentVersion.objects.filter(document_id=OuterRef("pk"))
        .order_by("-created_at", "-id")
        .values("content")[:1]
    )
    document_rows = documents.annotate(
        snapshot_content=latest_snapshot
    ).values("id", "name", "content", "snapshot_content")

    passages = []
    for document in document_rows:
        content = document["snapshot_content"] or document["content"]
        text = extract_document_text(content)
        for chunk in _chunks(text):
            tokens = TOKEN_PATTERN.findall(chunk.lower())
            if tokens:
                passages.append({
                    "document_id": str(document["id"]),
                    "name": document["name"],
                    "text": chunk,
                    "tokens": tokens,
                })

    query_tokens = TOKEN_PATTERN.findall(query.lower())
    query_terms = set(query_tokens)
    if not query_terms or not passages:
        return []

    document_frequency = Counter(
        term
        for term in query_terms
        for passage in passages
        if term in set(passage["tokens"])
    )
    average_length = sum(len(passage["tokens"]) for passage in passages) / len(passages)
    query_phrase = " ".join(query_tokens)
    ranked = []
    for passage in passages:
        frequencies = Counter(passage["tokens"])
        length = len(passage["tokens"])
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies[term]
            if not term_frequency:
                continue
            inverse_frequency = log(
                1 + (len(passages) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            denominator = term_frequency + 1.2 * (
                0.25 + 0.75 * length / max(average_length, 1)
            )
            score += inverse_frequency * term_frequency * 2.2 / denominator
        if query_phrase and query_phrase in passage["text"].lower():
            score += 1.0
        if score:
            ranked.append((score, passage))

    ranked.sort(key=lambda result: result[0], reverse=True)
    return [
        {
            "document_id": passage["document_id"],
            "name": passage["name"],
            "excerpt": passage["text"],
        }
        for _, passage in ranked[:limit]
    ]
