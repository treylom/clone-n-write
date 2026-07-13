#!/usr/bin/env python3
"""Extract deterministic writing skeletons and merge offline function labels.

The core is platform-neutral and standard-library only. Persona-backed modes
require an explicit ``--data-root`` pointing at the directory that contains
``<persona>/exemplars.jsonl``; standalone file extraction requires an explicit
``--output``. No host discovery, HOME convention, subprocess, or LLM call is
performed here. LLM-produced labels enter only through ``merge-labels`` JSONL.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

try:  # Script execution (python3 skill/skeleton_extract.py)
    import check_endings
    import registry
    import structure_profiler
except ImportError:  # Namespace-package import (import skill.skeleton_extract)
    from . import check_endings, registry, structure_profiler  # type: ignore


SCHEMA_VERSION = "skeleton-v1"
PROOF_CLASS = "deterministic"
TRANSITION_RE = re.compile(r"^(?:하지만|근데|다만|그런데|그렇다면)(?:\b|\s|[,.:!?…])")
FRONTMATTER_RE = re.compile(
    r"\A\ufeff?---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.S
)
QUESTION_RE = re.compile(r"\?(?:[\"'”’」』)\]}]*)\s*$")
TERMINAL_PUNCTUATION_RE = re.compile(r"[.!?…](?:[\"'”’」』)\]}]*)\s*$")


class SkeletonError(ValueError):
    """Raised for an invalid skeleton request or label item."""


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkeletonError(f"{label} must be a non-blank name")
    normalized = value.strip()
    if normalized in (".", "..") or Path(normalized).name != normalized or "\x00" in normalized:
        raise SkeletonError(f"{label} must be one path component")
    return normalized


def strip_frontmatter(text: str) -> str:
    """Remove one leading Markdown frontmatter block from measured prose."""

    normalized = structure_profiler.normalize_newlines(text)
    return FRONTMATTER_RE.sub("", normalized, count=1).lstrip("\ufeff")


def _slot(index: int, total: int, paragraph: str) -> str:
    # In the unavoidable one-block tie, opening precedence is deterministic.
    if index == 0:
        return "도입"
    if index == total - 1:
        return "마무리"
    if TRANSITION_RE.match(paragraph.lstrip()):
        return "전환"
    return "전개"


def _last_sentence(paragraph: str) -> str:
    sentences = check_endings.split_sentences(paragraph)
    if sentences:
        return sentences[-1]
    return next(
        (line.strip() for line in reversed(paragraph.splitlines()) if line.strip()),
        "",
    )


def classify_block_ending(paragraph: str) -> str:
    """Map the final sentence to the skeleton-v1 ending vocabulary."""

    sentence = _last_sentence(paragraph).strip()
    if not sentence:
        return "기타"
    if QUESTION_RE.search(sentence):
        return "질문"
    legacy = check_endings.classify(sentence)
    mapped = {
        "합니다체": "합니다",
        "해요체": "해요",
        "평어단정": "평어다",
        "음슴체": "음슴",
    }.get(legacy)
    if mapped:
        return mapped
    if not TERMINAL_PUNCTUATION_RE.search(sentence):
        return "명사종결"
    return "기타"


def extract_skeleton(text: str) -> Dict[str, Any]:
    """Return a deterministic skeleton from blank-line paragraph blocks."""

    if not isinstance(text, str):
        raise SkeletonError("input text must be a string")
    body = strip_frontmatter(text).strip()
    paragraphs = structure_profiler.split_paragraphs(body)
    if not paragraphs:
        raise SkeletonError("input contains no non-blank paragraph")

    blocks: List[Dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs):
        list_format, counts, _nonblank = structure_profiler.detect_list_format(paragraph)
        blocks.append(
            {
                "idx": index,
                "slot": _slot(index, len(paragraphs), paragraph),
                "subtype": None,
                "lines": len(paragraph.splitlines()),
                "chars": len(paragraph),
                "has_list": any(counts.values()),
                "list_format": list_format,
                "ending": classify_block_ending(paragraph),
                "fn": None,
            }
        )

    measured = structure_profiler.document_metrics(body)
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "blocks": blocks,
        "paragraphs": len(paragraphs),
        "single_sentence_para_ratio": measured["features"][
            "single_sentence_para_ratio"
        ],
        "list_format": measured["list_format"],
        "provenance": "결정골격=py",
    }


def _write_json(value: Mapping[str, Any], output: Union[str, os.PathLike[str]]) -> Path:
    """Atomically write stable, human-readable UTF-8 JSON."""

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return path


def _persona_dir(data_root: Union[str, os.PathLike[str]], persona: str) -> Path:
    return Path(data_root) / _safe_component(persona, "persona")


def _registry_rows(data_root: Union[str, os.PathLike[str]], persona: str) -> Tuple[Path, List[Dict[str, Any]]]:
    path = _persona_dir(data_root, persona) / "exemplars.jsonl"
    if not path.is_file():
        raise SkeletonError(f"registry does not exist: {path}")
    try:
        return path, registry.load_registry(path)
    except registry.RegistryError as exc:
        raise SkeletonError(str(exc)) from exc


def extract_registry_item(
    data_root: Union[str, os.PathLike[str]],
    persona: str,
    exemplar_id: str,
    output: Optional[Union[str, os.PathLike[str]]] = None,
    unseal_final: bool = False,
) -> Dict[str, Any]:
    """Extract one named registry row, respecting the final seal."""

    identifier = _safe_component(exemplar_id, "id")
    _path, rows = _registry_rows(data_root, persona)
    matches = [row for row in rows if row.get("id") == identifier]
    if not matches:
        raise SkeletonError(f"registry id not found: {identifier}")
    row = matches[0]
    if row.get("split") == "final" and not unseal_final:
        raise SkeletonError("final split is sealed; pass --unseal-final explicitly")
    body = row.get("body")
    if not isinstance(body, str) or not body.strip():
        raise SkeletonError(f"registry id has no non-blank body: {identifier}")
    destination = (
        Path(output)
        if output is not None
        else _persona_dir(data_root, persona) / "skeletons" / f"{identifier}.json"
    )
    skeleton = extract_skeleton(body)
    _write_json(skeleton, destination)
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "id": identifier,
        "output": str(destination),
    }


def extract_file(
    input_path: Union[str, os.PathLike[str]],
    output_path: Union[str, os.PathLike[str]],
) -> Dict[str, Any]:
    """Extract a standalone UTF-8 Markdown/text file to an explicit path."""

    source = Path(input_path)
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SkeletonError(f"cannot read {source}: {exc}") from exc
    skeleton = extract_skeleton(text)
    destination = _write_json(skeleton, output_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "input": str(source),
        "output": str(destination),
    }


def batch_extract(
    data_root: Union[str, os.PathLike[str]],
    persona: str,
    split: str = "train",
    medium: Optional[str] = None,
    unseal_final: bool = False,
) -> Dict[str, Any]:
    """Extract eligible rows and atomically link their portable skeleton paths."""

    if split not in registry.SPLITS:
        raise SkeletonError(f"split must be one of: {', '.join(registry.SPLITS)}")
    if split == "final" and not unseal_final:
        raise SkeletonError("final split is sealed; pass --unseal-final explicitly")
    registry_path, rows = _registry_rows(data_root, persona)
    persona_path = _persona_dir(data_root, persona)
    failures: List[Dict[str, str]] = []
    extracted_ids: List[str] = []
    skipped_low = 0
    selected = 0

    for row in sorted(rows, key=lambda value: str(value.get("id", ""))):
        if row.get("split") != split:
            continue
        if medium is not None and row.get("medium") != medium:
            continue
        selected += 1
        substance = row.get("substance")
        if not isinstance(substance, dict) or substance.get("level") != "ok":
            skipped_low += 1
            continue
        identifier = row.get("id")
        body = row.get("body")
        if not isinstance(identifier, str) or not identifier.strip():
            failures.append({"id": "", "reason": "missing id"})
            continue
        if not isinstance(body, str) or not body.strip():
            failures.append({"id": identifier, "reason": "missing body"})
            continue
        try:
            identifier = _safe_component(identifier, "id")
            skeleton = extract_skeleton(body)
            destination = persona_path / "skeletons" / f"{identifier}.json"
            _write_json(skeleton, destination)
            row["skeleton"] = f"skeletons/{identifier}.json"
            extracted_ids.append(identifier)
        except (OSError, UnicodeError, SkeletonError) as exc:
            failures.append({"id": identifier, "reason": str(exc)})

    try:
        registry.write_registry(rows, registry_path)
    except registry.RegistryError as exc:
        raise SkeletonError(str(exc)) from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "persona": _safe_component(persona, "persona"),
        "split": split,
        "medium": medium,
        "selected": selected,
        "extracted": len(extracted_ids),
        "failed": len(failures),
        "skipped_low_substance": skipped_low,
        "sample_id": extracted_ids[0] if extracted_ids else None,
        "failures": failures,
        "registry": str(registry_path),
    }


def _load_subtype_whitelist(path: Path) -> Optional[Set[str]]:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkeletonError(f"cannot read subtype whitelist {path}: {exc}") from exc

    allowed: Set[str] = set()

    def visit(item: Any, parent_key: Optional[str] = None) -> None:
        if isinstance(item, str):
            if parent_key in {None, "subtypes", "items", "values", "allowed"}:
                if item.strip():
                    allowed.add(item.strip())
            return
        if isinstance(item, list):
            for child in item:
                visit(child, parent_key)
            return
        if isinstance(item, dict):
            for field in ("id", "code", "name", "label", "subtype"):
                candidate = item.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    allowed.add(candidate.strip())
            for key, child in item.items():
                if key in {"schema_version", "proof_class", "description", "notes"}:
                    continue
                if isinstance(child, (dict, list)):
                    # Mapping-form dictionaries commonly use subtype codes as keys.
                    if isinstance(child, dict) and key not in {
                        "slots", "subtypes", "items", "values", "allowed"
                    }:
                        allowed.add(str(key).strip())
                    visit(child, str(key))
                elif key in {"subtypes", "items", "values", "allowed"}:
                    visit(child, key)

    visit(value)
    return allowed


def _iter_label_items(path: Path) -> Iterable[Tuple[int, Optional[Dict[str, Any]], Optional[str]]]:
    try:
        handle = path.open("r", encoding="utf-8-sig")
    except OSError as exc:
        raise SkeletonError(f"cannot read labels {path}: {exc}") from exc
    with handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                yield line_number, None, f"invalid JSON: {exc.msg}"
                continue
            if not isinstance(item, dict):
                yield line_number, None, "label item must be an object"
                continue
            yield line_number, item, None


def _validated_label_blocks(
    item: Mapping[str, Any],
    skeleton: Mapping[str, Any],
    whitelist: Optional[Set[str]],
) -> Dict[int, Tuple[Optional[str], Optional[str]]]:
    expected = skeleton.get("blocks")
    supplied = item.get("blocks")
    if not isinstance(expected, list) or not isinstance(supplied, list):
        raise SkeletonError("both skeleton and labels must contain blocks arrays")
    if len(expected) != len(supplied):
        raise SkeletonError(
            f"block count mismatch: skeleton={len(expected)} labels={len(supplied)}"
        )
    expected_indexes: Set[int] = set()
    for position, block in enumerate(expected):
        if not isinstance(block, dict):
            raise SkeletonError(f"skeleton block {position} must be an object")
        index = block.get("idx")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index != position
        ):
            raise SkeletonError(
                f"skeleton block indexes must be contiguous from zero: {index!r}"
            )
        expected_indexes.add(index)
    labels: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
    for block in supplied:
        if not isinstance(block, dict):
            raise SkeletonError("each label block must be an object")
        index = block.get("idx")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index not in expected_indexes
            or index in labels
        ):
            raise SkeletonError(f"invalid or duplicate block idx: {index!r}")
        subtype = block.get("subtype")
        function = block.get("fn")
        if subtype is not None and (not isinstance(subtype, str) or not subtype.strip()):
            raise SkeletonError(f"block {index} subtype must be null or non-blank text")
        if function is not None and (not isinstance(function, str) or not function.strip()):
            raise SkeletonError(f"block {index} fn must be null or non-blank text")
        normalized_subtype = subtype.strip() if isinstance(subtype, str) else None
        normalized_function = function.strip() if isinstance(function, str) else None
        if (
            whitelist is not None
            and normalized_subtype is not None
            and normalized_subtype not in whitelist
        ):
            raise SkeletonError(
                f"block {index} subtype is not in whitelist: {normalized_subtype!r}"
            )
        labels[index] = (normalized_subtype, normalized_function)
    if set(labels) != expected_indexes:
        raise SkeletonError("label block indexes do not cover the skeleton")
    return labels


def merge_labels(
    data_root: Union[str, os.PathLike[str]],
    persona: str,
    labels_path: Union[str, os.PathLike[str]],
    report_output: Optional[Union[str, os.PathLike[str]]] = None,
    unseal_final: bool = False,
) -> Dict[str, Any]:
    """Validate and merge each JSONL label item without aborting the batch."""

    persona_path = _persona_dir(data_root, persona)
    _registry_path, rows = _registry_rows(data_root, persona)
    registry_splits = {
        str(row.get("id")): row.get("split")
        for row in rows
        if isinstance(row.get("id"), str)
    }
    whitelist = _load_subtype_whitelist(persona_path / "subtypes.json")
    accepted = 0
    rejects: List[Dict[str, Any]] = []
    for line_number, item, parse_error in _iter_label_items(Path(labels_path)):
        if parse_error is not None or item is None:
            rejects.append({"line": line_number, "id": None, "reason": parse_error})
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            rejects.append({"line": line_number, "id": None, "reason": "missing id"})
            continue
        identifier = identifier.strip()
        try:
            _safe_component(identifier, "id")
            if identifier not in registry_splits:
                raise SkeletonError(f"registry id not found: {identifier}")
            if registry_splits[identifier] == "final" and not unseal_final:
                raise SkeletonError(
                    "final split is sealed; pass --unseal-final explicitly"
                )
            skeleton_path = persona_path / "skeletons" / f"{identifier}.json"
            skeleton = json.loads(skeleton_path.read_text(encoding="utf-8-sig"))
            if not isinstance(skeleton, dict):
                raise SkeletonError("skeleton must be an object")
            if skeleton.get("schema_version") != SCHEMA_VERSION:
                raise SkeletonError("skeleton schema_version mismatch")
            if skeleton.get("proof_class") != PROOF_CLASS:
                raise SkeletonError("skeleton proof_class mismatch")
            labels = _validated_label_blocks(item, skeleton, whitelist)
            merged = dict(skeleton)
            merged_blocks: List[Dict[str, Any]] = []
            for raw_block in skeleton["blocks"]:
                block = dict(raw_block)
                subtype, function = labels[block["idx"]]
                block["subtype"] = subtype
                block["fn"] = function
                merged_blocks.append(block)
            merged["blocks"] = merged_blocks
            merged["provenance"] = "결정골격=py|기능라벨=llm"
            _write_json(merged, skeleton_path)
            accepted += 1
        except (OSError, UnicodeError, json.JSONDecodeError, SkeletonError) as exc:
            rejects.append({"line": line_number, "id": identifier, "reason": str(exc)})

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "persona": _safe_component(persona, "persona"),
        "accepted": accepted,
        "rejected": len(rejects),
        "rejects": rejects,
    }
    if report_output is not None:
        _write_json(report, report_output)
        report["report_output"] = str(Path(report_output))
    return report


def _extract_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract one deterministic writing skeleton.")
    parser.add_argument("--data-root", help="directory containing persona data")
    parser.add_argument("--persona")
    parser.add_argument("--id")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--unseal-final", action="store_true")
    return parser


def _batch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-extract registry skeletons.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--split", choices=registry.SPLITS, default="train")
    parser.add_argument("--medium")
    parser.add_argument("--unseal-final", action="store_true")
    return parser


def _merge_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and merge offline function labels.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--persona", required=True)
    parser.add_argument("labels")
    parser.add_argument("--output", help="optional item-level merge report path")
    parser.add_argument("--unseal-final", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = arguments.pop(0) if arguments and arguments[0] in {"batch", "merge-labels"} else "extract"
    try:
        if command == "batch":
            args = _batch_parser().parse_args(arguments)
            result = batch_extract(
                args.data_root,
                args.persona,
                split=args.split,
                medium=args.medium,
                unseal_final=args.unseal_final,
            )
        elif command == "merge-labels":
            args = _merge_parser().parse_args(arguments)
            result = merge_labels(
                args.data_root,
                args.persona,
                args.labels,
                args.output,
                unseal_final=args.unseal_final,
            )
        else:
            args = _extract_parser().parse_args(arguments)
            registry_mode = args.persona is not None or args.id is not None
            file_mode = args.input is not None
            if registry_mode == file_mode:
                raise SkeletonError("choose exactly one of --persona/--id or --input")
            if registry_mode:
                if args.data_root is None or args.persona is None or args.id is None:
                    raise SkeletonError("registry extraction requires --data-root, --persona, and --id")
                result = extract_registry_item(
                    args.data_root,
                    args.persona,
                    args.id,
                    output=args.output,
                    unseal_final=args.unseal_final,
                )
            else:
                if args.output is None:
                    raise SkeletonError("standalone --input requires explicit --output")
                result = extract_file(args.input, args.output)
    except (OSError, UnicodeError, json.JSONDecodeError, SkeletonError, registry.RegistryError) as exc:
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
