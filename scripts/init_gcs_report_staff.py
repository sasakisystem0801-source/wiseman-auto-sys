"""5 担当者の suggest_patterns 初回 GCS 投入スクリプト（PR-β v1）。

実機 NAS 実態 (`\\\\Tera-station\\share\\PT 宮下` 等) に基づく初期データを
``mapping_sync.REPORT_STAFF_BLOB_PATH`` 互換の JSON として標準出力に書き出す。

実行（Mac 開発機 or Windows 機）:

    # JSON を生成
    uv run python scripts/init_gcs_report_staff.py > /tmp/report-staff-latest.json

    # GCS にアップロード（gcloud CLI 経由）
    gcloud storage cp /tmp/report-staff-latest.json \
        gs://wiseman-hub-prod/mappings/report-staff-latest.json

    # 確認
    gcloud storage cat gs://wiseman-hub-prod/mappings/report-staff-latest.json | jq '.'

その後、業務責任者は設定ダイアログ →「GCP から担当者を取得」→ 保存 で投入完了。

データ根拠:
- NAS フォルダ名: `Get-ChildItem \\\\Tera-station\\share\\` で確認済（OT 小林だけ
  空白なし、PT 全員空白あり）
- suggest_patterns: docs/handoff/staff-path-cache-runbook.md Phase 0 サンプル
- スプレッドシート「担当者」列の表記: 姓のみ（sheets.py:100 のコメント）
"""

from __future__ import annotations

import datetime as _dt
import json


def build_initial_report_staff() -> dict[str, dict[str, list[str] | str]]:
    """初期データ（5 担当者、suggest_patterns 各 1 行）を返す。"""
    return {
        "宮下": {
            "base_dir": "\\\\Tera-station\\share\\PT 宮下",
            "suggest_patterns": [
                "リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx",
            ],
        },
        "小島": {
            "base_dir": "\\\\Tera-station\\share\\PT 小島",
            "suggest_patterns": [
                "リハ経過報告書(新)/経過報告書*令和{era}年{month}月*.xlsx",
            ],
        },
        "平瀬": {
            "base_dir": "\\\\Tera-station\\share\\PT 平瀬",
            "suggest_patterns": [
                "リハ経過報告書/令和{era}年/新経過報告書 {month}月*.xlsx",
            ],
        },
        "木塚": {
            "base_dir": "\\\\Tera-station\\share\\PT 木塚",
            "suggest_patterns": [
                "経過報告書/令和*{era}*年度*/経過報告書*木塚*{month}月*.xlsx",
            ],
        },
        "小林": {
            "base_dir": "\\\\Tera-station\\share\\OT小林",
            "suggest_patterns": ["経過報告書/R{era}/*{month}月*.xlsx"],
        },
    }


def main() -> None:
    staff = build_initial_report_staff()
    now = _dt.datetime.now(_dt.UTC).astimezone()
    payload = {
        "version": "1",
        "generated_at": now.isoformat(),
        "staff": staff,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
