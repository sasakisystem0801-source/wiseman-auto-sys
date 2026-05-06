"""wiseman_hub_launcher: 小さな bootstrapper / updater (ADR-016)。

設計制約（厳守）:
    - **stdlib only**: urllib.request / hashlib / json / pathlib / datetime /
      argparse / logging / dataclasses / hmac / os / tempfile のみ
    - **wiseman_hub.* import 禁止**: 完全独立 package。launcher のバグが本体に
      波及しないよう import graph を最小化
    - **300 行未満（cloc 計測）**: 肥大化したらアーキテクチャ見直しの signal

PR-3 (本 PR) で実装する範囲:
    - manifest fetch + parse + schema 検証 (path traversal 防御)
    - SHA-256 verify (定数時間比較)
    - provenance verify は ProvenanceUnavailable raise (PR-6 で本実装)
    - current.json atomic read/write + 破損時 .corrupt-{ts} 退避
    - --dry-run mode (download/spawn なし)

PR-4 以降で実装する範囲（本 PR では未実装）:
    - versions/X.Y.Z/ ダウンロード
    - wiseman_hub.exe spawn + 起動失敗検知 + 自動 rollback
    - PR-6: provenance 本実装
"""

from __future__ import annotations

__version__ = "0.1.0"
"""launcher 自身のバージョン。本体 wiseman_hub のバージョンとは独立。

更新方針: 年 1-2 回程度（ADR-016 §2 launcher 自身の更新方針 参照）。
"""
