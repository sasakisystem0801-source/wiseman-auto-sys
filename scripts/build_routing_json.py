"""HIGH confidence のマッピングを GCS 配置用 JSON に変換する一回限りスクリプト。

draft_facility_mapping.py のロジックを再利用し、HIGH 確度のみを
``mapping_sync.MAPPING_BLOB_PATH`` 互換の JSON として標準出力に出す。

実行:
    uv run python scripts/build_routing_json.py > /tmp/facility-routing-latest.json
    gcloud storage cp /tmp/facility-routing-latest.json \
        gs://wiseman-hub-prod/mappings/facility-routing-latest.json

過去失敗対策:
    Walking Skeleton で「まず 1 回成功」させるため、HIGH 39 件のみで MVP を回す。
    MEDIUM/LOW/UNMATCHED 21 件はユーザー精査後に追加投入する別フェーズ。
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

# scripts/ を Python path に追加して draft_facility_mapping から再利用
sys.path.insert(0, str(Path(__file__).parent))

from draft_facility_mapping import (  # noqa: E402
    FAX_FOLDERS,
    confidence_of,
    extract_homes,
    normalize_core,
    score,
)


def build_high_confidence_mappings() -> dict[str, str]:
    """draft 生成と同じロジックで HIGH 確度のみ {home_name: fax_folder} を返す。"""
    homes = extract_homes()
    fax_pairs = [(f, normalize_core(f)) for f in FAX_FOLDERS]
    result: dict[str, str] = {}
    for home_name, _occ in homes:
        home_core = normalize_core(home_name)
        scored: list[tuple[str, float]] = []
        for fax_name, fax_core in fax_pairs:
            sc, _kind = score(home_core, fax_core)
            if sc > 0:
                scored.append((fax_name, sc))
        scored.sort(key=lambda x: -x[1])
        if not scored:
            continue
        top1 = scored[0][1]
        top2 = scored[1][1] if len(scored) > 1 else 0.0
        if confidence_of(top1, top2) == "high":
            result[home_name] = scored[0][0]
    return result


def main() -> None:
    mappings = build_high_confidence_mappings()
    now = _dt.datetime.now(_dt.UTC).astimezone()
    payload = {
        "version": "1",
        "generated_at": now.isoformat(),
        "mappings": mappings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(
        f"\n# {len(mappings)} HIGH-confidence entries written.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
