#!/usr/bin/env python3
"""Measure deterministic structure fingerprints from persona exemplars.

The profiler intentionally uses only Python's standard library.  Korean sentence
boundaries are a documented regular-expression approximation, not morphology:

* ``다.``, ``요.``, ``음.``, ``함.``, ``죠.``, ``까?``, ``!``, ``?`` and ``…``
  terminate a sentence.  A remaining non-blank physical line is one sentence
  (the newline heuristic).
* Paragraphs are runs of non-blank lines separated by one or more blank lines.
* Sentence length is the number of Unicode code points in the stripped sentence,
  including internal whitespace and its terminal punctuation.  ``sentence_len``
  is nested: its ``mean``, ``cv``, ``p10`` and ``p90`` are per-document values;
  each of those is then summarized across the corpus with the standard band
  record described below.
* ``list_usage`` is marked-list lines divided by non-blank lines.  A document's
  categorical ``list_format`` is the most-used marker among ``N)``, ``N.`` and
  ``-`` (that order breaks ties), or ``none``.  Corpus output keeps this sole
  categorical feature as counts, proportions, and a dominant value rather than
  inventing numeric percentiles for strings.
* ``symbol_per10k`` contains per-10,000-character rates for literal ``→``, ``…``,
  single-quote/apostrophe glyphs (``'``, ``‘``, ``’``), non-overlapping ``ㅋㅋ``
  and ``ㅎㅎ`` pairs, and matched non-nested ASCII/full-width parentheses.
  ``bold_rate`` likewise counts non-empty ``**…**`` spans per 10,000 characters.
* ``chars`` counts the newline-normalized body, ``lines`` uses physical lines,
  ``opener_len``/``closer_len`` use the first/last stripped non-blank line, and
  ``blank_line_count`` counts physical whitespace-only lines.

Every numeric feature leaf is summarized as
``{mean,p10,p25,p50,p75,p90,band:[p10,p90]}``.  Percentiles use linear
interpolation at ``(n - 1) * q`` (the common inclusive/type-7 definition).

Input contract::

    personas/<persona>/exemplars.jsonl
    {"body": "...", "medium": "threads", "genre": "정보",
     "substance": {"level": "ok"}}

Only rows for the requested medium whose ``substance.level`` is exactly ``ok``
are measured.  ``body`` is canonical; ``text`` and ``content`` are tolerated as
fallbacks for older data.  The CLI writes
``personas/<persona>/packs/structure-<medium>.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union


SCHEMA_VERSION = "struct-v1"
PROOF_CLASS = "corpus-measured"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONAS_DIR = REPO_ROOT / "personas"

SUMMARY_KEYS = ("mean", "p10", "p25", "p50", "p75", "p90", "band")
LIST_FORMATS = ("N)", "N.", "-", "none")

_SENTENCE_END = re.compile(r'''(?:[다요음함죠]\.|까\?|[!?]+|…+)(?:["'”’」』)\]}]*)''')
_LIST_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("N)", re.compile(r"^\s*\d+\)")),
    ("N.", re.compile(r"^\s*\d+\.(?!\d)")),  # compact marker yes, decimal no
    ("-", re.compile(r"^\s*-(?!--|\d)")),      # compact marker yes, rule/negative no
)
_BOLD_SPAN = re.compile(r"\*\*(?=\S).*?(?<=\S)\*\*", re.DOTALL)
_PAREN_SPAN = re.compile(r"\([^()\n]*\)|（[^（）\n]*）")


class ProfileError(ValueError):
    """Raised when exemplar data cannot produce a trustworthy profile."""


def normalize_newlines(text: str) -> str:
    """Return *text* with CRLF and CR normalized to LF."""

    return text.replace("\r\n", "\n").replace("\r", "\n")


def percentile(values: Sequence[float], q: float) -> float:
    """Return an inclusive/type-7 percentile using linear interpolation."""

    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= q <= 1.0:
        raise ValueError("percentile q must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _rounded(value: float) -> float:
    """Keep JSON stable without obscuring meaningful profiler precision."""

    result = round(float(value), 6)
    return 0.0 if result == 0 else result


def summarize(values: Sequence[float]) -> Dict[str, Any]:
    """Summarize one scalar feature across documents."""

    if not values:
        raise ValueError("cannot summarize an empty feature")
    numeric = [float(value) for value in values]
    p10 = _rounded(percentile(numeric, 0.10))
    p90 = _rounded(percentile(numeric, 0.90))
    return {
        "mean": _rounded(sum(numeric) / len(numeric)),
        "p10": p10,
        "p25": _rounded(percentile(numeric, 0.25)),
        "p50": _rounded(percentile(numeric, 0.50)),
        "p75": _rounded(percentile(numeric, 0.75)),
        "p90": p90,
        "band": [p10, p90],
    }


def split_paragraphs(text: str) -> List[str]:
    """Split text into non-empty paragraphs at physical blank lines."""

    paragraphs: List[str] = []
    current: List[str] = []
    for line in normalize_newlines(text).split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def split_sentences(text: str) -> List[str]:
    """Split Korean prose with deterministic ending regexes plus line fallback."""

    sentences: List[str] = []
    for raw_line in normalize_newlines(text).split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        start = 0
        for match in _SENTENCE_END.finditer(line):
            sentence = line[start:match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
        remainder = line[start:].strip()
        if remainder:
            sentences.append(remainder)
    return sentences


def detect_list_format(text: str) -> Tuple[str, Dict[str, int], int]:
    """Return (dominant document format, marker counts, non-blank line count)."""

    counts = {name: 0 for name in LIST_FORMATS[:-1]}
    nonblank = 0
    for line in normalize_newlines(text).split("\n"):
        if not line.strip():
            continue
        nonblank += 1
        for name, pattern in _LIST_PATTERNS:
            if pattern.match(line):
                counts[name] += 1
                break
    if not any(counts.values()):
        return "none", counts, nonblank
    dominant = max(LIST_FORMATS[:-1], key=lambda name: counts[name])
    return dominant, counts, nonblank


def _per_10k(count: int, chars: int) -> float:
    return (count * 10000.0 / chars) if chars else 0.0


def document_metrics(text: str) -> Dict[str, Any]:
    """Return scalar features and the categorical list format for one body."""

    if not isinstance(text, str):
        raise TypeError("document body must be a string")
    body = normalize_newlines(text)
    physical_lines = body.splitlines()
    paragraphs = split_paragraphs(body)
    sentences = split_sentences(body)
    sentence_lengths = [len(sentence.strip()) for sentence in sentences]

    sentence_mean = (
        sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0.0
    )
    if sentence_lengths and sentence_mean:
        variance = sum(
            (length - sentence_mean) ** 2 for length in sentence_lengths
        ) / len(sentence_lengths)
        sentence_cv = math.sqrt(variance) / sentence_mean
        sentence_p10 = percentile(sentence_lengths, 0.10)
        sentence_p90 = percentile(sentence_lengths, 0.90)
    else:
        sentence_cv = sentence_p10 = sentence_p90 = 0.0

    sentence_counts = [len(split_sentences(paragraph)) for paragraph in paragraphs]
    paragraph_count = len(paragraphs)
    sentences_per_paragraph = (
        sum(sentence_counts) / paragraph_count if paragraph_count else 0.0
    )
    single_sentence_ratio = (
        sum(count == 1 for count in sentence_counts) / paragraph_count
        if paragraph_count
        else 0.0
    )
    question_ratio = (
        sum("?" in sentence for sentence in sentences) / len(sentences)
        if sentences
        else 0.0
    )

    nonblank_lines = [line.strip() for line in physical_lines if line.strip()]
    list_format, list_counts, nonblank_count = detect_list_format(body)
    list_markers = sum(list_counts.values())
    char_count = len(body)

    single_quotes = sum(body.count(char) for char in ("'", "‘", "’"))
    features: Dict[str, Any] = {
        "chars": char_count,
        "lines": len(physical_lines),
        "paragraphs": paragraph_count,
        "sentences_per_paragraph": sentences_per_paragraph,
        "single_sentence_para_ratio": single_sentence_ratio,
        "sentence_len": {
            "mean": sentence_mean,
            "cv": sentence_cv,
            "p10": sentence_p10,
            "p90": sentence_p90,
        },
        "list_usage": list_markers / nonblank_count if nonblank_count else 0.0,
        "question_ratio": question_ratio,
        "opener_len": len(nonblank_lines[0]) if nonblank_lines else 0,
        "closer_len": len(nonblank_lines[-1]) if nonblank_lines else 0,
        "symbol_per10k": {
            "arrow": _per_10k(body.count("→"), char_count),
            "ellipsis": _per_10k(body.count("…"), char_count),
            "single_quote": _per_10k(single_quotes, char_count),
            "kk": _per_10k(body.count("ㅋㅋ"), char_count),
            "hh": _per_10k(body.count("ㅎㅎ"), char_count),
            "parentheses": _per_10k(len(_PAREN_SPAN.findall(body)), char_count),
        },
        "bold_rate": _per_10k(len(_BOLD_SPAN.findall(body)), char_count),
        "blank_line_count": sum(not line.strip() for line in physical_lines),
    }
    return {"features": features, "list_format": list_format}


def document_features(text: str) -> Dict[str, Any]:
    """Convenience import API returning only one document's scalar features."""

    return document_metrics(text)["features"]


def _list_format_summary(formats: Sequence[str]) -> Dict[str, Any]:
    counts = {name: 0 for name in LIST_FORMATS}
    for name in formats:
        if name not in counts:
            raise ValueError("unknown list format: %s" % name)
        counts[name] += 1
    total = len(formats)
    distribution = {
        name: _rounded(counts[name] / total) if total else 0.0
        for name in LIST_FORMATS
    }
    dominant = (
        max(LIST_FORMATS, key=lambda name: counts[name]) if total else "none"
    )
    return {
        "counts": counts,
        "distribution": distribution,
        "dominant": dominant,
    }


def _summarize_documents(measured: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate measured document feature trees into one corpus cell."""

    scalar = [item["features"] for item in measured]
    features: Dict[str, Any] = {
        name: summarize([item[name] for item in scalar])
        for name in (
            "chars",
            "lines",
            "paragraphs",
            "sentences_per_paragraph",
            "single_sentence_para_ratio",
        )
    }
    features["sentence_len"] = {
        name: summarize([item["sentence_len"][name] for item in scalar])
        for name in ("mean", "cv", "p10", "p90")
    }
    features["list_usage"] = summarize([item["list_usage"] for item in scalar])
    features["list_format"] = _list_format_summary(
        [str(item["list_format"]) for item in measured]
    )
    for name in ("question_ratio", "opener_len", "closer_len"):
        features[name] = summarize([item[name] for item in scalar])
    features["symbol_per10k"] = {
        name: summarize([item["symbol_per10k"][name] for item in scalar])
        for name in (
            "arrow",
            "ellipsis",
            "single_quote",
            "kk",
            "hh",
            "parentheses",
        )
    }
    for name in ("bold_rate", "blank_line_count"):
        features[name] = summarize([item[name] for item in scalar])
    return features


def _body_from_row(row: Mapping[str, Any]) -> Optional[str]:
    body = row.get("body")
    if isinstance(body, str) and body.strip():
        return body
    for fallback in ("text", "content"):
        value = row.get(fallback)
        if isinstance(value, str) and value.strip():
            return value
    return None


def load_exemplars(
    exemplars_path: Union[str, os.PathLike[str]], medium: str
) -> List[Dict[str, Any]]:
    """Load and filter one persona's JSONL exemplar file.

    Malformed JSON and eligible rows without a usable body fail with a line-aware
    ``ProfileError``.  Rows for other media or without measured-ok substance are
    intentionally ignored.
    """

    path = Path(exemplars_path)
    selected: List[Dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise ProfileError("cannot read exemplars %s: %s" % (path, exc)) from exc
    with handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ProfileError(
                    "%s:%d: invalid JSON: %s" % (path, line_number, exc.msg)
                ) from exc
            if not isinstance(row, dict):
                raise ProfileError("%s:%d: exemplar must be an object" % (path, line_number))
            substance = row.get("substance")
            if row.get("medium") != medium:
                continue
            if not isinstance(substance, dict) or substance.get("level") != "ok":
                continue
            body = _body_from_row(row)
            if body is None:
                raise ProfileError(
                    "%s:%d: eligible exemplar has no non-blank body" % (path, line_number)
                )
            normalized = dict(row)
            normalized["body"] = body
            genre = normalized.get("genre")
            if isinstance(genre, str):
                normalized["genre"] = genre.strip()
            selected.append(normalized)
    return selected


def _cell(records: Sequence[Mapping[str, Any]], direction_only: Optional[bool] = None) -> Dict[str, Any]:
    measured = [document_metrics(str(record["body"])) for record in records]
    cell: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "n": len(records),
        "features": _summarize_documents(measured),
    }
    if direction_only is not None:
        cell["direction_only"] = direction_only
    return cell


def build_profile(
    exemplars: Sequence[Mapping[str, Any]], medium: str, persona: Optional[str] = None
) -> Dict[str, Any]:
    """Build a structure pack from already-filtered exemplar records."""

    if not exemplars:
        raise ProfileError(
            "no exemplars matched medium=%r with substance.level='ok'" % medium
        )
    for index, record in enumerate(exemplars, 1):
        if not isinstance(record.get("body"), str) or not str(record["body"]).strip():
            raise ProfileError("exemplar %d has no non-blank body" % index)

    profile = _cell(exemplars)
    profile["persona"] = persona
    profile["medium"] = medium

    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for record in exemplars:
        genre = record.get("genre")
        if isinstance(genre, str) and genre.strip():
            grouped.setdefault(genre.strip(), []).append(record)
    if grouped:
        profile["genres"] = {
            genre: {
                **_cell(records, direction_only=len(records) < 10),
                "genre": genre,
            }
            for genre, records in sorted(grouped.items())
        }
    return profile


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError("%s must be a non-blank name" % label)
    value = value.strip()
    if value in (".", "..") or Path(value).name != value or "\x00" in value:
        raise ProfileError("%s must be one path component" % label)
    return value


def persona_paths(
    persona: str,
    medium: str,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> Tuple[Path, Path]:
    """Return the canonical (input JSONL, output pack) paths."""

    persona_name = _safe_component(persona, "persona")
    medium_name = _safe_component(medium, "medium")
    persona_dir = Path(personas_dir).expanduser() / persona_name
    return (
        persona_dir / "exemplars.jsonl",
        persona_dir / "packs" / ("structure-%s.json" % medium_name),
    )


def write_profile(
    profile: Mapping[str, Any], output_path: Union[str, os.PathLike[str]]
) -> Path:
    """Atomically write one UTF-8 structure pack and return its path."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return path


def build_persona_pack(
    persona: str,
    medium: str,
    personas_dir: Union[str, os.PathLike[str]] = DEFAULT_PERSONAS_DIR,
) -> Tuple[Dict[str, Any], Path]:
    """Load, profile, and write the canonical pack for a persona and medium."""

    persona_name = _safe_component(persona, "persona")
    medium_name = _safe_component(medium, "medium")
    input_path, output_path = persona_paths(persona_name, medium_name, personas_dir)
    exemplars = load_exemplars(input_path, medium_name)
    profile = build_profile(exemplars, medium=medium_name, persona=persona_name)
    write_profile(profile, output_path)
    return profile, output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a corpus-measured structure pack from persona exemplars."
    )
    parser.add_argument("--persona", required=True, help="persona directory name")
    parser.add_argument("--medium", required=True, help="exact exemplar medium")
    parser.add_argument(
        "--personas-dir",
        default=str(DEFAULT_PERSONAS_DIR),
        help="persona data root (default: repo/personas)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point; accepts an optional no-op ``build`` command alias."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "build":
        arguments = arguments[1:]
    args = build_parser().parse_args(arguments)
    try:
        profile, output_path = build_persona_pack(
            args.persona, args.medium, args.personas_dir
        )
    except (OSError, UnicodeError, ProfileError) as exc:
        error = {
            "schema_version": SCHEMA_VERSION,
            "proof_class": PROOF_CLASS,
            "status": "error",
            "error": str(exc),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    status = {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "persona": args.persona,
        "medium": args.medium,
        "n": profile["n"],
        "output": str(output_path),
    }
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
