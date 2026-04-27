"""PDF分割・条件付き再結合モジュール。

利用実績PDF（1利用者=1ページ）から利用者名をOCRで抽出し、
利用者ごとに別PDF（B, C）を指定順で結合、末尾に共通PDF（D）を追加する。

詳細はADR-008およびdocs/prd.md参照。

PR3 で ex_extractor (Wiseman .ex_ ファイル PDF 抽出 + 事業所フォルダ振り分け)
を追加。詳細は ADR-014 参照。
"""

from wiseman_hub.pdf.ex_extractor import (
    ExtractionErrorCode,
    ExtractionItem,
    ExtractionResult,
    ExtractionStatus,
    FakeSfxAdapter,
    SfxAdapter,
    SfxExtractionFailed,
    UnsupportedSfxPlatformError,
    WindowsSfxAdapter,
    extract_directory,
    extract_one,
)

__all__ = [
    "ExtractionErrorCode",
    "ExtractionItem",
    "ExtractionResult",
    "ExtractionStatus",
    "FakeSfxAdapter",
    "SfxAdapter",
    "SfxExtractionFailed",
    "UnsupportedSfxPlatformError",
    "WindowsSfxAdapter",
    "extract_directory",
    "extract_one",
]
