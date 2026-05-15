"""OCR 抽出した氏名と input_dir 内の B/C ファイル群を照合する。

設計方針（ADR-010 参照）:
- Protocol `NameMatcher` で将来 FuriganaMatcher 等を追加可能にしておく
- 当面は漢字ベースの `KanjiMatcher` のみ提供
- Levenshtein 距離 0 → auto_matched
- Levenshtein 距離 1-2 → needs_confirmation（人間確認）
- それ以上 → no_match

ファイル名パターン `B_{name}.pdf` から {name} 部分を抽出して比較する。
パターン内の他の文字は正規表現リテラル扱い（`re.escape`）。

B と C 両方を確認するが、片方しか存在しなくても AUTO_MATCHED を返す
（merger 側で欠損を WARN として処理する既存挙動と整合）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from wiseman_hub.utils.text_norm import normalize_lookup_key

_SIMILAR_DISTANCE_THRESHOLD = 2
_MAX_SIMILAR_CANDIDATES = 3


class MatchStatus(StrEnum):
    AUTO_MATCHED = "auto_matched"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NO_MATCH = "no_match"


class SourceKind(StrEnum):
    B = "B"
    C = "C"


@dataclass(frozen=True)
class CandidateFile:
    path: Path
    kind: SourceKind
    distance: int
    extracted_name: str


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    matched_b_path: Path | None
    matched_c_path: Path | None
    similar_candidates: tuple[CandidateFile, ...] = ()

    @property
    def has_any_match(self) -> bool:
        return self.matched_b_path is not None or self.matched_c_path is not None


class NameMatcher(Protocol):
    def match(self, user_name: str) -> MatchResult:
        ...


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """名前の正規化: NFKC + 全空白除去 (``text_norm.normalize_lookup_key`` と同等)。

    介護現場で発生しやすい表記揺れ（「塩津 美喜子」「塩津　美喜子」「塩津美喜子」）を
    同一文字列として扱うため。

    PR-γ v2: ``text_norm.normalize_lookup_key`` に統合 (DRY)。後方互換のため
    本関数名は維持し、内部実装を統合関数に委譲する。
    """
    return normalize_lookup_key(name)


# ---------------------------------------------------------------------------
# Levenshtein distance
# ---------------------------------------------------------------------------


def _levenshtein(a: str, b: str) -> int:
    """外部依存なしの Python 実装（氏名10文字程度・候補数十件想定）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            )
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# KanjiMatcher
# ---------------------------------------------------------------------------


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """`B_{name}.pdf` を `^B_(?P<name>.+)\\.pdf$` に変換する。

    `{name}` 以外の文字は正規表現リテラル（`re.escape`）として扱う。
    `{name}` が含まれないパターンは ValueError。
    """
    placeholder = "{name}"
    if placeholder not in pattern:
        raise ValueError(
            f"source pattern must contain '{{name}}' placeholder, got: {pattern!r}"
        )
    # {name} を一旦センチネルに置換してから re.escape、最後に名前キャプチャに差し替える
    sentinel = "\x00NAME_PLACEHOLDER\x00"
    escaped = re.escape(pattern.replace(placeholder, sentinel))
    regex_source = escaped.replace(re.escape(sentinel), r"(?P<name>.+)")
    return re.compile(f"^{regex_source}$")


class KanjiMatcher:
    """漢字氏名ベースの NameMatcher 実装。"""

    def __init__(
        self,
        input_dir: Path,
        source_b_pattern: str,
        source_c_pattern: str,
        *,
        similar_distance_threshold: int = _SIMILAR_DISTANCE_THRESHOLD,
        max_similar_candidates: int = _MAX_SIMILAR_CANDIDATES,
    ) -> None:
        self._input_dir = Path(input_dir)
        self._b_regex = _pattern_to_regex(source_b_pattern)
        self._c_regex = _pattern_to_regex(source_c_pattern)
        self._similar_threshold = similar_distance_threshold
        self._max_candidates = max_similar_candidates

    def match(self, user_name: str) -> MatchResult:
        if not user_name or not user_name.strip():
            raise ValueError("user_name must be a non-empty string")
        if not self._input_dir.exists():
            raise FileNotFoundError(
                f"input_dir does not exist: {self._input_dir}"
            )
        if not self._input_dir.is_dir():
            raise NotADirectoryError(
                f"input_dir is not a directory: {self._input_dir}"
            )

        target = normalize_name(user_name)

        b_files = self._collect_candidates(self._b_regex, SourceKind.B, target)
        c_files = self._collect_candidates(self._c_regex, SourceKind.C, target)

        exact_b = next((c for c in b_files if c.distance == 0), None)
        exact_c = next((c for c in c_files if c.distance == 0), None)

        if exact_b is not None or exact_c is not None:
            return MatchResult(
                status=MatchStatus.AUTO_MATCHED,
                matched_b_path=exact_b.path if exact_b else None,
                matched_c_path=exact_c.path if exact_c else None,
                similar_candidates=(),
            )

        similar = sorted(
            (c for c in (b_files + c_files) if 0 < c.distance <= self._similar_threshold),
            key=lambda c: (c.distance, c.kind, c.extracted_name),
        )
        top = tuple(similar[: self._max_candidates])

        if top:
            return MatchResult(
                status=MatchStatus.NEEDS_CONFIRMATION,
                matched_b_path=None,
                matched_c_path=None,
                similar_candidates=top,
            )

        return MatchResult(
            status=MatchStatus.NO_MATCH,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=(),
        )

    def _collect_candidates(
        self,
        regex: re.Pattern[str],
        kind: SourceKind,
        target_normalized: str,
    ) -> list[CandidateFile]:
        # 同姓同名ファイル（事故的命名）時の結果を決定論化するため sorted で走査する。
        results: list[CandidateFile] = []
        for path in sorted(self._input_dir.iterdir()):
            if not path.is_file():
                continue
            m = regex.match(path.name)
            if m is None:
                continue
            extracted = m.group("name")
            normalized = normalize_name(extracted)
            distance = _levenshtein(target_normalized, normalized)
            results.append(
                CandidateFile(
                    path=path,
                    kind=kind,
                    distance=distance,
                    extracted_name=extracted,
                )
            )
        return results
