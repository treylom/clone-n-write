#!/usr/bin/env python3
"""Diagnose draft structure against measured L2 bands and an optional skeleton.

This is a non-gating diagnostic. It uses only explicit inputs and Python's
standard library, writes a deterministic JSON sidecar, prints Korean
``대역 + 왜 + 코칭`` diagnostics, and always exits zero. Ending-style metrics
belong to ``check_endings.py`` and are deliberately absent from this axis.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

try:  # Script execution
    import skeleton_extract
    import structure_profiler
except ImportError:  # Namespace-package import
    from . import skeleton_extract, structure_profiler  # type: ignore


SCHEMA_VERSION = "structscore-v1"
PROOF_CLASS = "deterministic"
VERDICT = "diagnostic"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FRONTMATTER_CAPTURE_RE = re.compile(
    r"\A\ufeff?---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S
)

# An allowlist keeps future style additions to structure_profiler from silently
# crossing the non-compensatory style/structure boundary.
STRUCTURAL_ROOTS = {
    "chars",
    "lines",
    "paragraphs",
    "sentences_per_paragraph",
    "single_sentence_para_ratio",
    "sentence_len",
    "list_usage",
    "question_ratio",
    "opener_len",
    "closer_len",
    "symbol_per10k",
    "bold_rate",
    "blank_line_count",
}

FEATURE_LABELS = {
    "chars": "전체 글자 수",
    "lines": "물리 줄 수",
    "paragraphs": "문단 수",
    "sentences_per_paragraph": "문단당 문장 수",
    "single_sentence_para_ratio": "한 문장 문단 비율",
    "sentence_len.mean": "문장 길이 평균",
    "sentence_len.cv": "문장 길이 리듬 변동",
    "sentence_len.p10": "짧은 문장 길이",
    "sentence_len.p90": "긴 문장 길이",
    "list_usage": "목록 사용 비율",
    "list_format": "목록 형식",
    "question_ratio": "질문 배치 비율",
    "opener_len": "첫 줄 길이",
    "closer_len": "마지막 줄 길이",
    "symbol_per10k.arrow": "화살표 배치",
    "symbol_per10k.ellipsis": "말줄임표 배치",
    "symbol_per10k.single_quote": "작은따옴표 배치",
    "symbol_per10k.kk": "ㅋㅋ 배치",
    "symbol_per10k.hh": "ㅎㅎ 배치",
    "symbol_per10k.parentheses": "괄호 배치",
    "bold_rate": "굵게 표시 배치",
    "blank_line_count": "빈 줄 수",
}

COACHING = {
    "chars": "핵심 블록을 덜거나 보강해 전체 호흡을 대역 안으로 맞추세요.",
    "lines": "줄바꿈 수를 조절해 시각적 호흡을 맞추세요.",
    "paragraphs": "문단을 합치거나 나눠 전개 단위를 맞추세요.",
    "sentences_per_paragraph": "문단 안 문장 묶음의 밀도를 조절하세요.",
    "single_sentence_para_ratio": "한 문장 문단의 빈도를 조절해 리듬을 맞추세요.",
    "sentence_len": "짧고 긴 문장의 배치를 조절하되 어미 문체는 별도 게이트에서 보세요.",
    "list_usage": "목록을 줄이거나 필요한 정보 묶음에만 추가하세요.",
    "list_format": "앵커 코퍼스에서 실제 쓰인 목록 표기로 통일하세요.",
    "question_ratio": "질문을 훅·전환처럼 기능이 있는 위치에만 두세요.",
    "opener_len": "첫 줄을 압축하거나 한 근거를 보태 훅 길이를 맞추세요.",
    "closer_len": "마지막 줄의 결론 강도와 길이를 조절하세요.",
    "symbol_per10k": "기호를 장식이 아니라 전환·강조 기능이 있는 곳에만 배치하세요.",
    "bold_rate": "굵게 표시는 핵심 한두 곳으로 줄이거나 필요한 표지를 보강하세요.",
    "blank_line_count": "빈 줄을 문단 경계에 맞춰 늘리거나 줄이세요.",
}


class ScoreError(ValueError):
    """Raised when explicit scorer inputs cannot be verified."""


class DiagnosticParser(argparse.ArgumentParser):
    """Turn argparse usage errors into diagnostic data instead of exit 2."""

    def error(self, message: str) -> None:
        raise ScoreError(message)


def _safe_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScoreError(f"{label} must be a non-blank name")
    normalized = value.strip()
    if normalized in (".", "..") or Path(normalized).name != normalized or "\x00" in normalized:
        raise ScoreError(f"{label} must be one path component")
    return normalized


def _frontmatter_fields(text: str) -> Dict[str, str]:
    normalized = structure_profiler.normalize_newlines(text)
    match = FRONTMATTER_CAPTURE_RE.match(normalized)
    if not match:
        return {}
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        parsed = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if parsed:
            fields[parsed.group(1)] = parsed.group(2).strip().strip("\"'")
    return fields


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ScoreError(f"cannot read {label} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ScoreError(f"invalid {label} JSON {path}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"{label} must be a JSON object: {path}")
    return value


def _write_json(value: Mapping[str, Any], output: Union[str, os.PathLike[str]]) -> Path:
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


def _feature_value(features: Mapping[str, Any], dotted: str) -> float:
    value: Any = features
    for component in dotted.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise ScoreError(f"draft feature missing: {dotted}")
        value = value[component]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ScoreError(f"draft feature is not numeric: {dotted}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ScoreError(f"draft feature is not finite: {dotted}")
    return numeric


def _iter_bands(
    node: Mapping[str, Any], prefix: Tuple[str, ...] = ()
) -> Iterable[Tuple[str, float, float]]:
    band = node.get("band")
    if band is not None:
        if (
            len(prefix) >= 1
            and prefix[0] in STRUCTURAL_ROOTS
            and isinstance(band, list)
            and len(band) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in band)
        ):
            low, high = float(band[0]), float(band[1])
            if not math.isfinite(low) or not math.isfinite(high) or low > high:
                raise ScoreError(f"invalid band for {'.'.join(prefix)}")
            yield ".".join(prefix), low, high
        return
    for key, child in node.items():
        if not prefix and key not in STRUCTURAL_ROOTS:
            continue
        if key == "list_format":
            continue
        if isinstance(child, Mapping):
            yield from _iter_bands(child, prefix + (str(key),))


def _normalized_outside_distance(value: float, low: float, high: float) -> float:
    if low <= value <= high:
        return 0.0
    outside = low - value if value < low else value - high
    scale = max(high - low, abs(low), abs(high), 1.0)
    return outside / scale


def _number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _coach_for(feature: str) -> str:
    root = feature.split(".", 1)[0]
    return COACHING.get(root, "블록 배치를 조정해 train 대역 안으로 맞추세요.")


def _numeric_diagnostic(feature: str, value: float, low: float, high: float) -> str:
    label = FEATURE_LABELS.get(feature, feature)
    inside = low <= value <= high
    if inside:
        return (
            f"[대역 안] {label} {_number(value)} (대역 {_number(low)}–{_number(high)})"
            f" — 왜: train 구조 분포 안에 있습니다. — 코칭: 현재 구조적 호흡을 유지하세요."
        )
    direction = "낮음" if value < low else "높음"
    return (
        f"[대역 밖·{direction}] {label} {_number(value)} (대역 {_number(low)}–{_number(high)})"
        f" — 왜: train 구조 분포의 {'하한' if value < low else '상한'}을 벗어났습니다."
        f" — 코칭: {_coach_for(feature)}"
    )


def _select_band_cell(pack: Mapping[str, Any], genre: Optional[str]) -> Tuple[Mapping[str, Any], str, Optional[str]]:
    if genre:
        genres = pack.get("genres")
        if isinstance(genres, Mapping) and isinstance(genres.get(genre), Mapping):
            return genres[genre], f"genre:{genre}", None
        return pack, "medium", f"genre={genre!r} 밴드가 없어 medium 전체 대역을 사용했습니다."
    return pack, "medium", None


def compare_bands(
    body: str,
    pack: Mapping[str, Any],
    genre: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare structural leaves and categorical list format to one pack cell."""

    cell, scope, fallback_note = _select_band_cell(pack, genre)
    pack_features = cell.get("features")
    if not isinstance(pack_features, Mapping):
        raise ScoreError("structure pack has no features object")
    measured = structure_profiler.document_metrics(body)
    draft_features = measured["features"]
    in_band: Dict[str, bool] = {}
    details: Dict[str, Any] = {}
    diagnostics: List[str] = []
    distances: List[float] = []
    for feature, low, high in _iter_bands(pack_features):
        value = _feature_value(draft_features, feature)
        # Profiler packs serialize feature summaries at six decimals. Compare
        # at that same precision so a source-identical draft cannot miss an
        # exact-width band only because its in-memory float has more digits.
        comparable_value = round(value, 6)
        inside = low <= comparable_value <= high
        in_band[feature] = inside
        distance = _normalized_outside_distance(comparable_value, low, high)
        distances.append(distance)
        details[feature] = {
            "value": value,
            "band": [low, high],
            "distance": round(distance, 6),
        }
        diagnostics.append(_numeric_diagnostic(feature, value, low, high))

    list_summary = pack_features.get("list_format")
    observed_format = str(measured["list_format"])
    allowed_formats: List[str] = []
    if isinstance(list_summary, Mapping):
        distribution = list_summary.get("distribution")
        if isinstance(distribution, Mapping):
            allowed_formats = sorted(
                str(name)
                for name, proportion in distribution.items()
                if isinstance(proportion, (int, float)) and float(proportion) > 0.0
            )
        if not allowed_formats and isinstance(list_summary.get("dominant"), str):
            allowed_formats = [str(list_summary["dominant"])]
    list_inside = observed_format in allowed_formats if allowed_formats else False
    in_band["list_format"] = list_inside
    details["list_format"] = {
        "value": observed_format,
        "allowed": allowed_formats,
        "distance": 0.0 if list_inside else 1.0,
    }
    distances.append(0.0 if list_inside else 1.0)
    if list_inside:
        diagnostics.append(
            f"[대역 안] 목록 형식 {observed_format} (관측 형식 {', '.join(allowed_formats)})"
            " — 왜: train 코퍼스에서 실제 관측된 형식입니다. — 코칭: 같은 표기를 유지하세요."
        )
    else:
        diagnostics.append(
            f"[대역 밖] 목록 형식 {observed_format} (관측 형식 {', '.join(allowed_formats) or '없음'})"
            " — 왜: train 코퍼스에서 관측되지 않은 목록 표기입니다."
            f" — 코칭: {COACHING['list_format']}"
        )

    total = len(in_band)
    ratio = sum(in_band.values()) / total if total else 0.0
    l2 = math.sqrt(sum(distance * distance for distance in distances) / len(distances)) if distances else 0.0
    return {
        "metrics": measured,
        "in_band": in_band,
        "in_band_ratio": round(ratio, 6),
        "l2_distance": round(l2, 6),
        "band_details": details,
        "band_scope": scope,
        "fallback_note": fallback_note,
        "diagnostics": diagnostics,
    }


def _lcs_length(left: Sequence[str], right: Sequence[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_value in left:
        current = [0]
        for index, right_value in enumerate(right, 1):
            if left_value == right_value:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def skeleton_adherence(body: str, expected: Mapping[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """Score slot order, block count, ±30% lengths, and list format equally."""

    expected_blocks = expected.get("blocks")
    if not isinstance(expected_blocks, list) or not expected_blocks:
        raise ScoreError("skeleton has no non-empty blocks array")
    if not all(isinstance(block, Mapping) for block in expected_blocks):
        raise ScoreError("skeleton blocks must be objects")
    draft = skeleton_extract.extract_skeleton(body)
    draft_blocks = draft["blocks"]
    expected_slots = [str(block.get("slot", "")) for block in expected_blocks]
    draft_slots = [str(block.get("slot", "")) for block in draft_blocks]
    lcs = _lcs_length(expected_slots, draft_slots)
    slot_score = lcs / max(len(expected_slots), len(draft_slots), 1)

    block_delta = len(draft_blocks) - len(expected_blocks)
    block_count_score = max(
        0.0,
        1.0 - abs(block_delta) / max(len(expected_blocks), len(draft_blocks), 1),
    )
    length_rows: List[Dict[str, Any]] = []
    within = 0
    denominator = max(len(expected_blocks), len(draft_blocks), 1)
    for index, expected_block in enumerate(expected_blocks):
        expected_chars = expected_block.get("chars")
        if not isinstance(expected_chars, (int, float)) or isinstance(expected_chars, bool):
            raise ScoreError(f"skeleton block {index} chars is not numeric")
        actual_chars = draft_blocks[index]["chars"] if index < len(draft_blocks) else None
        low, high = float(expected_chars) * 0.70, float(expected_chars) * 1.30
        is_within = actual_chars is not None and low <= float(actual_chars) <= high
        within += int(is_within)
        length_rows.append(
            {
                "idx": index,
                "expected": float(expected_chars),
                "actual": actual_chars,
                "band": [round(low, 6), round(high, 6)],
                "within_30pct": is_within,
            }
        )
    length_score = within / denominator

    expected_format = str(expected.get("list_format", "none"))
    actual_format = str(draft.get("list_format", "none"))
    list_score = 1.0 if expected_format == actual_format else 0.0
    adherence = (slot_score + block_count_score + length_score + list_score) / 4.0
    details = {
        "slot_sequence_expected": expected_slots,
        "slot_sequence_actual": draft_slots,
        "slot_lcs": lcs,
        "slot_score": round(slot_score, 6),
        "block_count_delta": block_delta,
        "block_count_score": round(block_count_score, 6),
        "block_lengths": length_rows,
        "block_length_score": round(length_score, 6),
        "list_format_expected": expected_format,
        "list_format_actual": actual_format,
        "list_format_match": bool(list_score),
    }
    return round(adherence, 6), details


def _resolve_skeleton(
    data_root: Path,
    persona: str,
    specification: str,
) -> Tuple[str, Path, Dict[str, Any], bytes]:
    candidate = Path(specification)
    explicit_path = candidate.is_file() or len(candidate.parts) > 1
    if explicit_path:
        path = candidate
        identifier = path.stem
    else:
        identifier = candidate.stem if candidate.suffix == ".json" else specification
        identifier = _safe_component(identifier, "skeleton id")
        path = data_root / _safe_component(persona, "persona") / "skeletons" / f"{identifier}.json"
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ScoreError(f"cannot read skeleton {path}: {exc}") from exc
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScoreError(f"invalid skeleton JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScoreError(f"skeleton must be an object: {path}")
    return identifier, path, value, payload


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ScoreError(f"cannot hash outline {path}: {exc}") from exc


def verify_manifest(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    skeleton_id: Optional[str],
    skeleton_payload: Optional[bytes],
    draft_frontmatter: Mapping[str, str],
) -> Tuple[bool, Dict[str, Any], List[str]]:
    """Verify skeleton bytes and an explicit outline hash claim/path."""

    reasons: List[str] = []
    expected_id = manifest.get("skeleton_id")
    expected_skeleton_hash = manifest.get("skeleton_sha256")
    expected_outline_hash = manifest.get("outline_sha256")
    if not isinstance(expected_id, str) or not expected_id.strip():
        reasons.append("manifest skeleton_id missing")
    elif skeleton_id != expected_id.strip():
        reasons.append(f"skeleton_id expected={expected_id!r} actual={skeleton_id!r}")
    actual_skeleton_hash = (
        hashlib.sha256(skeleton_payload).hexdigest()
        if skeleton_payload is not None
        else None
    )
    if not isinstance(expected_skeleton_hash, str) or not SHA256_RE.fullmatch(expected_skeleton_hash):
        reasons.append("manifest skeleton_sha256 is missing or invalid")
    elif actual_skeleton_hash != expected_skeleton_hash.lower():
        reasons.append(
            f"skeleton_sha256 expected={expected_skeleton_hash.lower()} actual={actual_skeleton_hash}"
        )

    actual_outline_hash: Optional[str] = None
    outline_source: Optional[str] = None
    outline_path_value = manifest.get("outline_path")
    if isinstance(outline_path_value, str) and outline_path_value.strip():
        outline_path = Path(outline_path_value)
        if not outline_path.is_absolute():
            outline_path = manifest_path.parent / outline_path
        actual_outline_hash = _sha256_file(outline_path)
        outline_source = str(outline_path)
    else:
        claim = draft_frontmatter.get("outline_sha256") or draft_frontmatter.get("outline_hash")
        if claim:
            actual_outline_hash = claim.lower()
            outline_source = "draft-frontmatter"
    if not isinstance(expected_outline_hash, str) or not SHA256_RE.fullmatch(expected_outline_hash):
        reasons.append("manifest outline_sha256 is missing or invalid")
    elif actual_outline_hash is None:
        reasons.append("outline_sha256 has no verifiable outline_path/frontmatter evidence")
    elif actual_outline_hash != expected_outline_hash.lower():
        reasons.append(
            f"outline_sha256 expected={expected_outline_hash.lower()} actual={actual_outline_hash}"
        )

    details = {
        "skeleton_id_expected": expected_id,
        "skeleton_id_actual": skeleton_id,
        "skeleton_sha256_expected": expected_skeleton_hash,
        "skeleton_sha256_actual": actual_skeleton_hash,
        "outline_sha256_expected": expected_outline_hash,
        "outline_sha256_actual": actual_outline_hash,
        "outline_evidence": outline_source,
        "reasons": reasons,
    }
    return not reasons, details, reasons


def score_file(
    input_path: Union[str, os.PathLike[str]],
    persona: str,
    medium: str,
    data_root: Union[str, os.PathLike[str]],
    genre: Optional[str] = None,
    skeleton_spec: Optional[str] = None,
    manifest_path: Optional[Union[str, os.PathLike[str]]] = None,
    output_path: Optional[Union[str, os.PathLike[str]]] = None,
) -> Tuple[Dict[str, Any], List[str], Path]:
    """Score one explicit draft and write its JSON diagnostic artifact."""

    source = Path(input_path)
    try:
        raw = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ScoreError(f"cannot read draft {source}: {exc}") from exc
    body = skeleton_extract.strip_frontmatter(raw).strip()
    if not body:
        raise ScoreError("draft contains no non-frontmatter text")
    persona_name = _safe_component(persona, "persona")
    medium_name = _safe_component(medium, "medium")
    root = Path(data_root)
    pack_path = root / persona_name / "packs" / f"structure-{medium_name}.json"
    pack = _read_json(pack_path, "structure pack")
    comparison = compare_bands(body, pack, genre)

    manifest: Optional[Dict[str, Any]] = None
    manifest_file: Optional[Path] = None
    if manifest_path is not None:
        manifest_file = Path(manifest_path)
        manifest = _read_json(manifest_file, "manifest")
        if skeleton_spec is None and isinstance(manifest.get("skeleton_id"), str):
            skeleton_spec = str(manifest["skeleton_id"])

    skeleton_id: Optional[str] = None
    skeleton_path: Optional[Path] = None
    skeleton_value: Optional[Dict[str, Any]] = None
    skeleton_payload: Optional[bytes] = None
    adherence: Optional[float] = None
    adherence_details: Optional[Dict[str, Any]] = None
    if skeleton_spec is not None:
        skeleton_id, skeleton_path, skeleton_value, skeleton_payload = _resolve_skeleton(
            root, persona_name, skeleton_spec
        )
        adherence, adherence_details = skeleton_adherence(body, skeleton_value)

    manifest_ok: Optional[bool] = None
    manifest_details: Optional[Dict[str, Any]] = None
    manifest_diagnostics: List[str] = []
    if manifest is not None and manifest_file is not None:
        manifest_ok, manifest_details, reasons = verify_manifest(
            manifest,
            manifest_file,
            skeleton_id,
            skeleton_payload,
            _frontmatter_fields(raw),
        )
        if manifest_ok:
            manifest_diagnostics.append(
                "MANIFEST_OK — 왜: skeleton id·파일 SHA-256·outline SHA-256 증거가 일치합니다."
                " — 코칭: 승인된 구조 연결을 유지하세요."
            )
        else:
            manifest_diagnostics.append(
                "MANIFEST_MISMATCH — " + "; ".join(reasons)
                + " — 코칭: 승인된 skeleton/outline 파일과 manifest를 다시 봉인하세요."
            )

    diagnostics: List[str] = [
        f"구조 진단 — persona={persona_name}, medium={medium_name}, scope={comparison['band_scope']}"
    ]
    if comparison["fallback_note"]:
        diagnostics.append(
            f"대역 선택 참고 — 왜: {comparison['fallback_note']} — 코칭: 장르 표본이 쌓이면 장르 셀을 다시 생성하세요."
        )
    diagnostics.extend(comparison["diagnostics"])
    if adherence is not None and adherence_details is not None:
        diagnostics.append(
            f"스켈레톤 정합 {adherence:.4f} — 왜: slot LCS={adherence_details['slot_score']:.4f}, "
            f"블록 수 delta={adherence_details['block_count_delta']}, "
            f"분량 ±30%={adherence_details['block_length_score']:.4f}, "
            f"list_format 일치={adherence_details['list_format_match']}."
            " — 코칭: 가장 낮은 구성요소부터 개요와 다시 맞추세요."
        )
    diagnostics.extend(manifest_diagnostics)

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "ok",
        "persona": persona_name,
        "medium": medium_name,
        "genre": genre,
        "pack": str(pack_path),
        "metrics": comparison["metrics"],
        "in_band": comparison["in_band"],
        "in_band_ratio": comparison["in_band_ratio"],
        "l2_distance": comparison["l2_distance"],
        "band_scope": comparison["band_scope"],
        "band_details": comparison["band_details"],
        "skeleton_id": skeleton_id,
        "skeleton_path": str(skeleton_path) if skeleton_path is not None else None,
        "adherence": adherence,
        "adherence_details": adherence_details,
        "manifest_ok": manifest_ok,
        "manifest_details": manifest_details,
        "verdict": VERDICT,
    }
    destination = (
        Path(output_path)
        if output_path is not None
        else Path(str(source) + ".structure.json")
    )
    _write_json(report, destination)
    return report, diagnostics, destination


def _error_report(error: Exception, manifest_requested: bool) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_class": PROOF_CLASS,
        "status": "error",
        "error": str(error),
        "in_band": {},
        "in_band_ratio": 0.0,
        "adherence": None,
        "manifest_ok": False if manifest_requested else None,
        "verdict": VERDICT,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticParser(description="Diagnose draft structure against persona L2 bands.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--persona", required=True)
    parser.add_argument("--medium", required=True)
    parser.add_argument("--genre")
    parser.add_argument("--skeleton")
    parser.add_argument("--manifest")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parsed: Optional[argparse.Namespace] = None
    try:
        parsed = build_parser().parse_args(arguments)
        report, diagnostics, destination = score_file(
            parsed.input,
            parsed.persona,
            parsed.medium,
            parsed.data_root,
            genre=parsed.genre,
            skeleton_spec=parsed.skeleton,
            manifest_path=parsed.manifest,
            output_path=parsed.output,
        )
        for line in diagnostics:
            print(line)
        print(
            f"요약 — in_band_ratio={report['in_band_ratio']:.4f}, "
            f"adherence={report['adherence']}, manifest_ok={report['manifest_ok']}, "
            f"verdict={VERDICT}"
        )
        print(f"JSON — {destination}")
    except Exception as exc:  # The CLI's contract is diagnostic exit 0, including bad inputs.
        manifest_requested = bool(parsed and parsed.manifest)
        report = _error_report(exc, manifest_requested)
        print(f"구조 진단 오류 — 왜: {exc} — 코칭: 명시 입력·데이터 루트·스키마를 확인하세요.")
        print(json.dumps(report, ensure_ascii=False))
        if parsed is not None and getattr(parsed, "input", None):
            destination = (
                Path(parsed.output)
                if getattr(parsed, "output", None)
                else Path(str(parsed.input) + ".structure.json")
            )
            try:
                _write_json(report, destination)
                print(f"JSON — {destination}")
            except Exception as write_error:
                print(f"JSON 기록 실패 — {write_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
