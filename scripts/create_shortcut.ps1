<#
.SYNOPSIS
    Wiseman PDF ツールのデスクトップショートカットを作成する（タスク 14C / ADR-011）。

.DESCRIPTION
    配布 ZIP を展開したディレクトリから `wiseman_hub.exe` と `assets/icon.ico` を
    解決し、ユーザーの Desktop にショートカット `Wiseman PDF ツール.lnk` を配置する。
    管理者権限は不要（ユーザーごとの Desktop に作成）。

    スクリプト自身の配置（`$PSScriptRoot`）を基準にパスを解決するため、
    任意のディレクトリから実行しても安定して動作する。

.PARAMETER ExePath
    wiseman_hub.exe のパス。省略時は `$PSScriptRoot\..\wiseman_hub.exe` を使用。

.PARAMETER IconPath
    アイコン（.ico）のパス。省略時は `$PSScriptRoot\..\assets\icon.ico` を使用。
    見つからない場合は exe 埋め込みアイコンにフォールバック。

.PARAMETER ShortcutName
    ショートカット名（拡張子なし）。省略時は "Wiseman PDF ツール"。

.EXAMPLE
    .\create_shortcut.ps1
    既定パスで Desktop にショートカットを作成。

.EXAMPLE
    .\create_shortcut.ps1 -ExePath "C:\wiseman-hub\wiseman_hub.exe"
    exe パスを明示指定。

.NOTES
    対応シェル:
      - Windows PowerShell 5.1+（Windows 10/11 標準）
      - PowerShell 7+（Windows のみ、WScript.Shell COM 依存）
    Linux / macOS の pwsh では `New-Object -ComObject` が機能しないため非対応。

    実行ポリシー制限時は以下を一時的に適用（現在の PS セッションのみ）:
        Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

    ファイルエンコーディング: UTF-8 BOM 付き。PS 5.1 で日本語 ShortcutName が
    CP932 誤解釈されないよう BOM を残すこと。
#>

[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$IconPath,
    [string]$ShortcutName = "Wiseman PDF ツール"
)

$ErrorActionPreference = "Stop"

# $PSScriptRoot はスクリプトファイルが配置されたディレクトリの絶対パス。
# CWD に依存しないため、ダブルクリック起動や別ディレクトリからの `. .\create_shortcut.ps1`
# でもパスが壊れない。
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    # dot-sourcing や ISE 経由で $PSScriptRoot が空になるケースの fallback
    if ($MyInvocation.MyCommand.Path) {
        $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
}
if (-not $ScriptDir) {
    Write-Host "エラー: スクリプトの配置ディレクトリを特定できません。" -ForegroundColor Red
    Write-Host "  `iex` 等でストリーム経由実行された可能性があります。"
    Write-Host "  ファイルとしてディスクに保存してから `.\create_shortcut.ps1` で実行してください。"
    exit 1
}

# 配布 ZIP 展開直後の想定レイアウト:
#   wiseman-hub/
#   ├── wiseman_hub.exe
#   ├── config/default.toml
#   ├── assets/icon.ico
#   └── scripts/create_shortcut.ps1   ← このスクリプト
$ParentDir = Join-Path $ScriptDir ".."
$DistRoot = (Resolve-Path -LiteralPath $ParentDir -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path)
if (-not $DistRoot) {
    Write-Host "エラー: 配布ルートディレクトリ ($ParentDir) が解決できません。" -ForegroundColor Red
    Write-Host "  配布 ZIP の展開が不完全な可能性があります。再展開してください。"
    exit 1
}

if (-not $ExePath) {
    $ExePath = Join-Path $DistRoot "wiseman_hub.exe"
}
if (-not $IconPath) {
    $IconPath = Join-Path $DistRoot "assets\icon.ico"
}

Write-Host "=== Wiseman PDF ツール ショートカット作成 ===" -ForegroundColor Green
Write-Host "配布ルート: $DistRoot"
Write-Host "exe パス : $ExePath"
Write-Host "アイコン : $IconPath"

if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    Write-Host ""
    Write-Host "エラー: wiseman_hub.exe が見つかりません。" -ForegroundColor Red
    Write-Host "  期待パス: $ExePath"
    Write-Host "  配布 ZIP を展開後、scripts/ ディレクトリの 1 つ上に exe を配置してください。"
    Write-Host "  または -ExePath で明示指定してください。"
    exit 1
}

$DesktopDir = [Environment]::GetFolderPath("Desktop")
if (-not $DesktopDir) {
    Write-Host "エラー: Desktop ディレクトリを特定できません。" -ForegroundColor Red
    Write-Host "  Known Folder 設定が壊れている可能性があります。OneDrive Desktop 同期設定を確認してください。"
    exit 1
}

$ShortcutPath = Join-Path $DesktopDir "$ShortcutName.lnk"

$WshShell = $null
$Shortcut = $null
try {
    try {
        $WshShell = New-Object -ComObject WScript.Shell
    } catch {
        # Windows Script Host が GPO 等で無効化されている / ConstrainedLanguage モード等
        Write-Host "エラー: WScript.Shell COM オブジェクトを作成できません。" -ForegroundColor Red
        Write-Host "  原因候補:"
        Write-Host "    - Windows Script Host (WSH) が GPO で無効化されている"
        Write-Host "    - PowerShell ConstrainedLanguage モード（WDAC / AppLocker）"
        Write-Host "    - $($_.Exception.Message)"
        Write-Host "  §4「手動でのショートカット作成」を参照してください。"
        exit 2
    }

    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $ExePath
    # WorkingDirectory を exe 配置ディレクトリにすることで、
    # exe と同ディレクトリの config/ を参照する frozen ビルドの挙動と整合。
    $Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
    $Shortcut.Description = "Wiseman PDF 統合ツール（介護記録処理）"

    if (Test-Path -LiteralPath $IconPath -PathType Leaf) {
        # WScript.Shell は "path,index" 形式で icon を受ける（index=0 が先頭）
        $Shortcut.IconLocation = "$IconPath,0"
    } else {
        Write-Host "警告: icon.ico が見つかりません。exe 埋め込みアイコンを使用します。" -ForegroundColor Yellow
        Write-Host "  期待パス: $IconPath"
        $Shortcut.IconLocation = "$ExePath,0"
    }

    try {
        $Shortcut.Save()
    } catch [System.UnauthorizedAccessException], [System.Runtime.InteropServices.COMException] {
        Write-Host ""
        Write-Host "エラー: ショートカットの保存に失敗しました。" -ForegroundColor Red
        Write-Host "  保存先: $ShortcutPath"
        Write-Host "  詳細: $($_.Exception.Message)"
        Write-Host ""
        Write-Host "  原因候補:"
        Write-Host "    - OneDrive Desktop 同期が一時停止中 → OneDrive を再開するか同期無効化"
        Write-Host "    - アンチウイルスの ASR ルールが .lnk 生成をブロック"
        Write-Host "    - Desktop への書込 ACL 不足"
        Write-Host "  §7.1『アクセスが拒否されました』の対処を確認してください。"
        exit 3
    }
} finally {
    # Save() が例外で抜けても COM を必ず解放する（長時間プロセスでのリーク防止）
    if ($Shortcut) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($Shortcut)
    }
    if ($WshShell) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($WshShell)
    }
}

Write-Host ""
Write-Host "=== 完了 ===" -ForegroundColor Green
Write-Host "ショートカット: $ShortcutPath" -ForegroundColor Cyan
Write-Host "Desktop からダブルクリックで起動できます。"
