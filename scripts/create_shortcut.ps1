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
    PowerShell 5.1+（Windows 10/11 標準）で動作確認。
    実行ポリシー制限時は以下を一時的に適用:
        Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
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
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}

# 配布 ZIP 展開直後の想定レイアウト:
#   wiseman-hub/
#   ├── wiseman_hub.exe
#   ├── config/default.toml
#   ├── assets/icon.ico
#   └── scripts/create_shortcut.ps1   ← このスクリプト
$DistRoot = Resolve-Path (Join-Path $ScriptDir "..") | Select-Object -ExpandProperty Path

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
    exit 1
}

$ShortcutPath = Join-Path $DesktopDir "$ShortcutName.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
# WorkingDirectory を exe 配置ディレクトリにすることで、
# Python 側の config パス解決（__main__._default_config_path の frozen 分岐）と整合。
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

$Shortcut.Save()

# COM オブジェクト解放（長時間プロセスでないため厳密には不要だが、明示的に）
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($Shortcut) | Out-Null
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($WshShell) | Out-Null

Write-Host ""
Write-Host "=== 完了 ===" -ForegroundColor Green
Write-Host "ショートカット: $ShortcutPath" -ForegroundColor Cyan
Write-Host "Desktop からダブルクリックで起動できます。"
