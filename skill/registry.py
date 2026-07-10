#!/usr/bin/env python3
"""Build and query per-persona exemplar registries.

The registry is intentionally deterministic and standard-library only.  Source
documents are cleaned, deduplicated, assigned stable IDs, and split with
``sha1(id)`` so repeated builds produce the same train/heldout assignment.

Canonical storage::

    personas/<persona>/exemplars.jsonl

Each JSONL row carries ``schema_version`` and ``proof_class`` alongside the v1
exemplar fields.  ``pull`` removes heldout and low-substance rows *before*
ranking unless their explicit opt-in flags are present.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

try:  # Script execution (python3 skill/registry.py)
    from build_corpus import (
        clean_alookso as _legacy_clean_alookso,
        clean_threads as _legacy_clean_threads,
        dedup_lines as _dedup_lines,
        drop_near_dups as _drop_near_dups,
        strip_cross_doc_boilerplate as _strip_cross_doc_boilerplate,
    )
except ImportError:  # Namespace-package import (import skill.registry)
    from .build_corpus import (  # type: ignore
        clean_alookso as _legacy_clean_alookso,
        clean_threads as _legacy_clean_threads,
        dedup_lines as _dedup_lines,
        drop_near_dups as _drop_near_dups,
        strip_cross_doc_boilerplate as _strip_cross_doc_boilerplate,
    )


SCHEMA_VERSION = "registry-v1"
PROOF_CLASS = "source-exemplar"
STATS_PROOF_CLASS = "registry-measured"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONAS_DIR = REPO_ROOT / "personas"
MEDIUMS = ("threads", "longform")
SOURCE_FORMATS = ("tk-jsonl", "gn-raw-jsonl", "md-dir")
GN_AUTHOR = "specal1849"

URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_.-]+")
TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9_-]{1,}")
FRONTMATTER_RE = re.compile(r"\A\ufeff?---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)

TOPIC_STOPWORDS = {
    "그리고", "그러나", "하지만", "그래서", "그런데", "이것", "저것", "그것",
    "있는", "없는", "있다", "없다", "한다", "했다", "됩니다", "입니다", "대한",
    "위한", "통해", "때문", "정말", "오늘", "이번", "우리", "제가", "나는", "너무",
    "the", "and", "for", "with", "this", "that", "from",
}
REACTION_RE = re.compile(
    r"(?:안녕(?:하세요)?|반갑(?:습니다|네요)?|감사(?:합니다|해요)?|축하(?:합니다|해요)?|"
    r"대박|최고|굿|와우|헉|앗|화이팅|힘내|좋아요|맞아요|그러게요|ㅋㅋ+|ㅎㅎ+|ㅠㅠ+|ㅜㅜ+)"
)
LINK_LINE_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:(?:https?://|www\.)\S+|\[[^\]]*\]\(https?://[^)]+\))"
    r"(?:\s+(?:(?:https?://|www\.)\S+|\[[^\]]*\]\(https?://[^)]+\)))*\s*$",
    re.I,
)

GN_CUT_MARKER_RE = re.compile(r"^(?:활동\s*보기|인기순|최신순)$", re.I)
GN_DROP_LINE_RE = re.compile(
    r"^(?:AI\s*Threads|Threads|작성자|·|/|더\s*보기|번역\s*보기|"
    r"좋아요(?:\s*\d[\d,.만천KkMm]*(?:개|회|건|명)?)?|"
    r"답글(?:\s*\d[\d,.만천KkMm]*(?:개|회|건|명)?)?|"
    r"리포스트(?:\s*\d[\d,.만천KkMm]*(?:개|회|건|명)?)?|"
    r"공유(?:\s*\d[\d,.만천KkMm]*(?:개|회|건|명)?)?|"
    r"조회(?:수)?(?:\s*\d[\d,.만천KkMm]*(?:개|회|건|명)?)?)$",
    re.I,
)
DATE_LINE_RE = re.compile(
    r"^(?:\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}(?:[-./]\d{2,4})?|"
    r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일)$"
)
RELATIVE_TIME_RE = re.compile(r"^(?:방금|\d+\s*(?:초|분|시간|일|주|개월|년)(?:\s*전)?)$")
COUNT_ONLY_RE = re.compile(r"^[\d,.]+(?:만|천|[KkMm])?$")
REPLY_CHROME_RE = re.compile(r"^(?:.+님에게\s*답글|답글\s*달기|답글을\s*입력하세요)$")


class RegistryError(ValueError):
    """Raised for invalid registry input or an unsafe data path."""


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{label} must be a non-blank name")
    value = value.strip()
    if value in (".", "..") or Path(value).name != value or "\x00" in value:
        raise RegistryError(f"{label} must be one path component")
    return value


def registry_path(
    persona: str,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> Path:
    return Path(personas_dir).expanduser() / _safe_component(persona, "persona") / "exemplars.jsonl"


def stable_id(ref: str, medium: str, source_kind: str = "source") -> str:
    """Return an opaque stable ID without embedding private source paths."""

    material = f"{source_kind}\0{medium}\0{ref}".encode("utf-8")
    return hashlib.sha1(material).hexdigest()


def deterministic_split(exemplar_id: str, heldout_ratio: float = 0.15) -> str:
    """Assign train/heldout solely from SHA1(id)."""

    if not 0.0 <= heldout_ratio <= 1.0:
        raise RegistryError("heldout_ratio must be between 0 and 1")
    digest = int(hashlib.sha1(exemplar_id.encode("utf-8")).hexdigest(), 16)
    fraction = digest / float(1 << 160)
    return "heldout" if fraction < heldout_ratio else "train"


def _frontmatter(raw: str) -> Tuple[Dict[str, str], str]:
    text = normalize_newlines(raw)
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.lstrip("\ufeff")
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        field = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if field:
            fields[field.group(1)] = field.group(2).strip().strip("\"'")
    return fields, text[match.end():]


def clean_threads(text: str) -> str:
    """Reuse the promoted Threads hygiene gate and normalize its result."""

    cleaned = normalize_newlines(_legacy_clean_threads(normalize_newlines(text)))
    lines: List[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped == "AI Threads":
            continue
        if re.match(r"^@?[^\s@]+님에게\s*(?:남긴\s*)?답글$", stripped):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _collapse_duplicate_passage(text: str) -> str:
    """Prefer the later complete copy when an archive contains a duplicated passage.

    AlookSo notes sometimes contain a partial plain scrape followed by the full
    Markdown article.  A repeated long paragraph is conservative evidence of
    that recapture; content before the second copy is removed only from the
    first repeated paragraph onward.
    """

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    normalized = [
        re.sub(r"[^0-9A-Za-z가-힣]+", "", URL_RE.sub("", paragraph)).lower()
        for paragraph in paragraphs
    ]
    first_seen: Dict[str, int] = {}
    for later, key in enumerate(normalized):
        if len(key) < 40:
            continue
        earlier = first_seen.get(key)
        if earlier is not None:
            return "\n\n".join(paragraphs[:earlier] + paragraphs[later:])
        first_seen[key] = later
    return text


def clean_markdown(raw: str) -> Tuple[str, Dict[str, str]]:
    """Return article prose and simple frontmatter metadata from an archive note.

    When ``글 전문:`` exists it is the authoritative boundary: everything before
    it is archive metadata/AI summary.  Known bio and navigation tails are cut
    before the existing build_corpus markdown hygiene runs.
    """

    fields, body = _frontmatter(raw)
    marker = re.search(r"^\s*(?:#{1,6}\s*)?글\s*전문\s*:\s*", body, re.M)
    if marker:
        body = body[marker.end():]
    body = re.split(
        r"\n\s*(?:#{1,6}\s*)?관련\s*노트\b|\n\s*←\s*\[\[|"
        r"\n\s*인공지능,?\s*정치과정.*?연구활동가",
        body,
        maxsplit=1,
        flags=re.I,
    )[0]
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = _collapse_duplicate_passage(body)
    cleaned = _legacy_clean_alookso(body)
    cleaned = _collapse_duplicate_passage(cleaned)
    return normalize_newlines(cleaned).strip(), fields


def clean_gn_block(text: str, author: str = GN_AUTHOR) -> str:
    """Strip rendered Threads-card chrome from one GN ``x`` block.

    Numeric-only lines are removed, while digits embedded in prose survive.
    Header-only date/relative-time rules are limited to the leading card region.
    """

    output: List[str] = []
    for index, raw_line in enumerate(normalize_newlines(text).split("\n")):
        line = raw_line.strip()
        if not line:
            if output and output[-1] != "":
                output.append("")
            continue
        if GN_CUT_MARKER_RE.match(line):
            break
        if line == author or line == f"@{author}":
            continue
        if GN_DROP_LINE_RE.match(line) or REPLY_CHROME_RE.match(line):
            continue
        if index < 8 and (DATE_LINE_RE.match(line) or RELATIVE_TIME_RE.match(line)):
            continue
        if COUNT_ONLY_RE.match(line):
            continue
        output.append(line)
    while output and not output[-1]:
        output.pop()
    return _dedup_lines("\n".join(output)).strip()


def _iter_jsonl(path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    try:
        handle = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise RegistryError(f"cannot read {path}: {exc}") from exc
    with handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise RegistryError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise RegistryError(f"{path}:{line_number}: expected a JSON object")
            yield line_number, value


def _tk_ref(url: str, line_number: int) -> Tuple[str, str]:
    match = re.search(r"/post/([^/?#]+)", url)
    if match:
        return url, match.group(1)
    fallback = url or f"line-{line_number}"
    return fallback, fallback


def load_tk_jsonl(source: Union[str, os.PathLike[str]]) -> List[Dict[str, str]]:
    path = Path(source)
    documents: List[Dict[str, str]] = []
    for line_number, value in _iter_jsonl(path):
        body = value.get("body")
        if not isinstance(body, str):
            continue
        cleaned = clean_threads(body)
        if not cleaned:
            continue
        url = str(value.get("url") or "")
        ref, source_key = _tk_ref(url, line_number)
        documents.append(
            {
                "ref": ref,
                "source_key": source_key,
                "date": str(value.get("dt") or ""),
                "text": cleaned,
            }
        )
    return documents


def load_md_dir(source: Union[str, os.PathLike[str]]) -> List[Dict[str, str]]:
    root = Path(source)
    if not root.is_dir():
        raise RegistryError(f"md-dir source is not a directory: {root}")
    documents: List[Dict[str, str]] = []
    for path in sorted(root.rglob("*.md"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        parts = set(relative.parts)
        if ".worktrees" in parts or "worktree" in parts:
            continue
        if "MOC" in path.name or "작업과정" in path.name:
            continue
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise RegistryError(f"cannot read {path}: {exc}") from exc
        cleaned, fields = clean_markdown(raw)
        if not cleaned:
            continue
        ref = relative.as_posix()
        documents.append(
            {
                "ref": ref,
                "source_key": ref,
                "date": fields.get("published") or fields.get("created") or "",
                "text": cleaned,
            }
        )
    return documents


def load_gn_raw_jsonl(
    source: Union[str, os.PathLike[str]], author: str = GN_AUTHOR
) -> List[Dict[str, str]]:
    path = Path(source)
    documents: List[Dict[str, str]] = []
    for line_number, value in _iter_jsonl(path):
        code = str(value.get("code") or f"line-{line_number}")
        blocks = value.get("blocks")
        if not isinstance(blocks, list):
            continue
        bodies: List[str] = []
        seen_bodies = set()
        first_date = ""
        for block in blocks:
            if not isinstance(block, dict) or block.get("a") != author:
                continue
            raw = block.get("x")
            if not isinstance(raw, str):
                continue
            cleaned = clean_gn_block(raw, author=author)
            normalized = re.sub(r"\s+", "", cleaned)
            if not cleaned or normalized in seen_bodies:
                continue
            seen_bodies.add(normalized)
            bodies.append(cleaned)
            if not first_date:
                first_date = str(block.get("dt") or "")
        if bodies:
            documents.append(
                {
                    "ref": code,
                    "source_key": code,
                    "date": first_date,
                    "text": "\n\n".join(bodies),
                }
            )
    return documents


def _deduplicate_documents(documents: Sequence[Mapping[str, str]]) -> List[Dict[str, str]]:
    """Apply promoted cross-document boilerplate, near-dup, and exact-dup gates."""

    working = [dict(document) for document in documents if str(document.get("text", "")).strip()]
    working, _boilerplate = _strip_cross_doc_boilerplate(working)
    working = [document for document in working if document["text"].strip()]
    working, _near_dropped = _drop_near_dups(working)
    seen = set()
    unique: List[Dict[str, str]] = []
    for document in working:
        digest = hashlib.sha1(
            re.sub(r"\s+", " ", document["text"]).strip().encode("utf-8")
        ).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(document)
    return unique


def topic_tokens(text: str, limit: Optional[int] = None) -> List[str]:
    """Return deterministic noun-like token approximations (no morphology)."""

    scrubbed = MENTION_RE.sub(" ", URL_RE.sub(" ", text))
    tokens: List[str] = []
    first_seen: Dict[str, int] = {}
    counts: Counter[str] = Counter()
    for match in TOKEN_RE.finditer(scrubbed):
        token = match.group(0).lower()
        if token in TOPIC_STOPWORDS:
            continue
        if token not in first_seen:
            first_seen[token] = len(first_seen)
            tokens.append(token)
        counts[token] += 1
    ranked = sorted(tokens, key=lambda token: (-counts[token], first_seen[token], token))
    return ranked if limit is None else ranked[:limit]


def _effective_content(text: str) -> str:
    without_links = URL_RE.sub(" ", text)
    without_mentions = MENTION_RE.sub(" ", without_links)
    without_markdown_urls = re.sub(r"\]\(\s*\)", "]", without_mentions)
    return re.sub(r"\s+", "", without_markdown_urls)


def _repeated_phrase_ratio(text: str) -> float:
    segments = [
        re.sub(r"[^0-9A-Za-z가-힣]+", "", part).lower()
        for part in re.split(r"\n+|(?<=[.!?…])\s*", text)
    ]
    segments = [segment for segment in segments if len(segment) >= 2]
    if len(segments) < 2:
        return 0.0
    counts = Counter(segments)
    repeated = max(counts.values())
    return repeated / len(segments) if repeated > 1 else 0.0


def classify_substance(text: str) -> Dict[str, Any]:
    """Conservatively classify v1 low-substance signals and record all reasons."""

    body = normalize_newlines(text).strip()
    reasons: List[str] = []
    lines = [line for line in body.splitlines() if line.strip()]
    if lines and all(LINK_LINE_RE.match(line) for line in lines):
        reasons.append("link_list_only")

    effective = _effective_content(body)
    if len(effective) < 40:
        reasons.append("effective_content_lt_40")

    compact_chars = len(re.sub(r"\s+", "", body))
    reactions = list(REACTION_RE.finditer(body))
    if compact_chars < 80 and reactions:
        reaction_chars = sum(len(match.group(0)) for match in reactions)
        remainder = REACTION_RE.sub("", effective)
        remainder = re.sub(r"[^0-9A-Za-z가-힣]", "", remainder)
        exclamations = body.count("!") + body.count("?")
        if len(remainder) < 20 or reaction_chars / max(len(effective), 1) >= 0.35 or exclamations >= 2:
            reasons.append("short_reaction_heavy")

    if _repeated_phrase_ratio(body) > 0.5:
        reasons.append("repeated_phrase_gt_0.5")

    return {"level": "low" if reasons else "ok", "reasons": reasons}


def make_exemplar(
    document: Mapping[str, str],
    medium: str,
    source_kind: str,
    heldout_ratio: float = 0.15,
) -> Dict[str, Any]:
    if medium not in MEDIUMS:
        raise RegistryError(f"unsupported medium: {medium}")
    body = normalize_newlines(str(document["text"])).strip()
    ref = str(document.get("ref") or "")
    source_key = str(document.get("source_key") or ref)
    exemplar_id = stable_id(source_key, medium, source_kind)
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "id": exemplar_id,
        "ref": ref,
        "medium": medium,
        "genre": None,
        "grade": {"src": "auto", "score": 0.5},
        "substance": classify_substance(body),
        "body": body,
        "chars": len(body),
        "date": str(document.get("date") or ""),
        "topic_keys": topic_tokens(body, limit=8),
        "skeleton": None,
        "split": deterministic_split(exemplar_id, heldout_ratio),
    }


def load_registry(path: Union[str, os.PathLike[str]]) -> List[Dict[str, Any]]:
    registry = Path(path)
    if not registry.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for _line_number, row in _iter_jsonl(registry):
        rows.append(row)
    return rows


def write_registry(rows: Sequence[Mapping[str, Any]], path: Union[str, os.PathLike[str]]) -> Path:
    """Atomically write sorted UTF-8 JSONL."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: str(row.get("id", "")))
    fd, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp", dir=str(destination.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in ordered:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return destination


def _load_source(source: Union[str, os.PathLike[str]], source_format: str) -> List[Dict[str, str]]:
    if source_format == "tk-jsonl":
        documents = load_tk_jsonl(source)
    elif source_format == "md-dir":
        documents = load_md_dir(source)
    elif source_format == "gn-raw-jsonl":
        documents = load_gn_raw_jsonl(source)
    else:
        raise RegistryError(f"unsupported source format: {source_format}")
    return _deduplicate_documents(documents)


def build_registry(
    persona: str,
    source: Union[str, os.PathLike[str]],
    medium: str,
    source_format: str,
    heldout_ratio: float = 0.15,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> Dict[str, Any]:
    """Clean a source batch and merge/upsert it into one persona registry."""

    if medium not in MEDIUMS:
        raise RegistryError(f"unsupported medium: {medium}")
    documents = _load_source(source, source_format)
    incoming = [
        make_exemplar(document, medium, source_format, heldout_ratio)
        for document in documents
    ]
    path = registry_path(persona, personas_dir)
    existing = load_registry(path)
    merged = {str(row.get("id")): row for row in existing if row.get("id")}
    before_ids = set(merged)
    merged.update({row["id"]: row for row in incoming})
    write_registry(list(merged.values()), path)
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "persona": _safe_component(persona, "persona"),
        "source_format": source_format,
        "medium": medium,
        "built": len(incoming),
        "inserted": sum(row["id"] not in before_ids for row in incoming),
        "updated": sum(row["id"] in before_ids for row in incoming),
        "total": len(merged),
        "output": str(path),
    }


def add_exemplar(
    persona: str,
    file_path: Union[str, os.PathLike[str]],
    medium: str,
    heldout_ratio: float = 0.15,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> Dict[str, Any]:
    """Add/upsert one UTF-8 text or Markdown file."""

    path = Path(file_path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RegistryError(f"cannot read {path}: {exc}") from exc
    if path.suffix.lower() == ".md":
        body, fields = clean_markdown(raw)
        date = fields.get("published") or fields.get("created") or ""
    else:
        body, date = clean_threads(raw), ""
    if not body:
        raise RegistryError(f"no usable body in {path}")
    resolved_ref = str(path.expanduser().resolve())
    row = make_exemplar(
        {"ref": str(path), "source_key": resolved_ref, "date": date, "text": body},
        medium,
        "add",
        heldout_ratio,
    )
    destination = registry_path(persona, personas_dir)
    merged = {str(item.get("id")): item for item in load_registry(destination) if item.get("id")}
    merged[row["id"]] = row
    write_registry(list(merged.values()), destination)
    return row


def pull_exemplars(
    persona: str,
    genre: Optional[str] = None,
    topic: Optional[str] = None,
    k: int = 3,
    include_heldout: bool = False,
    include_low_substance: bool = False,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> List[Dict[str, Any]]:
    """Return grade/topic-ranked exemplars after hard contamination filters."""

    if k < 0:
        raise RegistryError("k must be non-negative")
    rows = load_registry(registry_path(persona, personas_dir))
    rows = [
        row for row in rows
        if row.get("schema_version") == SCHEMA_VERSION
        and row.get("proof_class") == PROOF_CLASS
        and row.get("split") in ("train", "heldout")
        and isinstance(row.get("substance"), dict)
        and row["substance"].get("level") in ("ok", "low")
    ]
    if not include_heldout:
        rows = [row for row in rows if row.get("split") == "train"]
    if not include_low_substance:
        rows = [
            row for row in rows
            if isinstance(row.get("substance"), dict)
            and row["substance"].get("level") == "ok"
        ]
    if genre is not None:
        rows = [row for row in rows if row.get("genre") == genre]

    query = set(topic_tokens(topic or ""))

    def rank(row: Mapping[str, Any]) -> Tuple[float, int, str]:
        grade = row.get("grade")
        score = float(grade.get("score", 0.0)) if isinstance(grade, dict) else 0.0
        keys = {str(key).lower() for key in row.get("topic_keys", []) if isinstance(key, str)}
        return (-score, -len(query & keys), str(row.get("id", "")))

    return [dict(row) for row in sorted(rows, key=rank)[:k]]


def registry_stats(
    persona: str,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> Dict[str, Any]:
    rows = load_registry(registry_path(persona, personas_dir))
    medium_counts = Counter(str(row.get("medium") or "unknown") for row in rows)
    split_counts = Counter(str(row.get("split") or "unknown") for row in rows)
    substance_counts = Counter(
        str(row.get("substance", {}).get("level") or "unknown")
        if isinstance(row.get("substance"), dict) else "unknown"
        for row in rows
    )
    by_medium: Dict[str, Dict[str, Any]] = {}
    for medium in sorted(set(MEDIUMS) | set(medium_counts)):
        selected = [row for row in rows if row.get("medium") == medium]
        by_medium[medium] = {
            "total": len(selected),
            "split": dict(sorted(Counter(str(row.get("split") or "unknown") for row in selected).items())),
            "substance": dict(
                sorted(
                    Counter(
                        str(row.get("substance", {}).get("level") or "unknown")
                        if isinstance(row.get("substance"), dict) else "unknown"
                        for row in selected
                    ).items()
                )
            ),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": STATS_PROOF_CLASS,
        "persona": _safe_component(persona, "persona"),
        "total": len(rows),
        "medium": dict(sorted(medium_counts.items())),
        "split": dict(sorted(split_counts.items())),
        "substance": dict(sorted(substance_counts.items())),
        "by_medium": by_medium,
    }


# Short import aliases matching the CLI verbs.
build = build_registry
pull = pull_exemplars
add = add_exemplar
stats = registry_stats


def _add_personas_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--personas-dir",
        default=str(DEFAULT_PERSONAS_DIR),
        help="persona data root (default: repo/personas)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query persona exemplar registries.")
    commands = parser.add_subparsers(dest="command", required=True)

    build_command = commands.add_parser("build", help="import and merge one source batch")
    build_command.add_argument("--persona", required=True)
    build_command.add_argument("--source", required=True)
    build_command.add_argument("--medium", required=True, choices=MEDIUMS)
    build_command.add_argument("--format", required=True, choices=SOURCE_FORMATS, dest="source_format")
    build_command.add_argument("--heldout-ratio", type=float, default=0.15)
    _add_personas_dir(build_command)

    pull_command = commands.add_parser("pull", help="select safe exemplars")
    pull_command.add_argument("--persona", required=True)
    pull_command.add_argument("--genre")
    pull_command.add_argument("--topic")
    pull_command.add_argument("-k", type=int, default=3)
    pull_command.add_argument("--include-heldout", action="store_true")
    pull_command.add_argument("--include-low-substance", action="store_true")
    _add_personas_dir(pull_command)

    add_command = commands.add_parser("add", help="add one local text/Markdown file")
    add_command.add_argument("--persona", required=True)
    add_command.add_argument("file")
    add_command.add_argument("--medium", required=True, choices=MEDIUMS)
    add_command.add_argument("--heldout-ratio", type=float, default=0.15)
    _add_personas_dir(add_command)

    stats_command = commands.add_parser("stats", help="summarize a persona registry")
    stats_command.add_argument("--persona", required=True)
    _add_personas_dir(stats_command)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result: Any = build_registry(
                args.persona,
                args.source,
                args.medium,
                args.source_format,
                args.heldout_ratio,
                args.personas_dir,
            )
        elif args.command == "pull":
            result = pull_exemplars(
                args.persona,
                args.genre,
                args.topic,
                args.k,
                args.include_heldout,
                args.include_low_substance,
                args.personas_dir,
            )
        elif args.command == "add":
            result = add_exemplar(
                args.persona,
                args.file,
                args.medium,
                args.heldout_ratio,
                args.personas_dir,
            )
        else:
            result = registry_stats(args.persona, args.personas_dir)
    except (OSError, UnicodeError, RegistryError, ValueError) as exc:
        error = {
            "schema_version": SCHEMA_VERSION,
            "proof_class": PROOF_CLASS,
            "status": "error",
            "error": str(exc),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
