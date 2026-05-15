<#
.SYNOPSIS
    Wiseman Auto System の Windows 実機向け配布スクリプト（runbook 1c の自動化版）。

.DESCRIPTION
    `docs/handoff/1c-exe-redistribution-runbook.md` の Phase 0〜3 を 1 コマンドで
    実行する。安全装置（バックアップ / warning 検査 / Launcher プロセス検出 /
    auto-rollback / 件数アサーション）はすべて維持し、業務責任者でも実行可能な
    対話フローにまとめる。

    位置付け（ADR-016 Phase 7 切替前の暫定運用）:
        - 完全自動更新 (launcher polling) が実装されるまでの開発者負担軽減
        - Phase 7 切替後は本スクリプトも disaster recovery 専用となる

.PARAMETER ExpectedHead
    `git pull` 後の HEAD commit short hash の期待値（任意）。指定時は不一致で停止。

.PARAMETER SkipTests
    Phase 0-4 の `uv run pytest` をスキップ。最終手段（緊急 hotfix 等）。

.PARAMETER SkipBuild
    Phase 1 の `pyinstaller` をスキップ。既存の `dist\wiseman_hub.exe` を流用。
    デバッグ用、本番配布では使わない。

.PARAMETER RollbackOnly
    Phase 2 をスキップして直近バックアップから復元のみ実施。配布後に問題が
    発覚した時の緊急 rollback 経路。

.PARAMETER NoPrompt
    Phase 2 (exe 上書き) の対話確認をスキップ。CI / 無人実行向け。
    対話無しは事故リスクが上がるので、通常運用では指定しない。

.EXAMPLE
    .\scripts\deploy-windows.ps1
    通常配布（対話あり、全 Phase 実行）

.EXAMPLE
    .\scripts\deploy-windows.ps1 -ExpectedHead e079d41
    HEAD 検証付きの安全配布

.EXAMPLE
    .\scripts\deploy-windows.ps1 -RollbackOnly
    緊急 rollback

.NOTES
    対応シェル:
        - Windows PowerShell 5.1+ (Windows 10/11 標準)
        - PowerShell 7+ (Windows)
        - Linux / macOS pwsh は非対応:
            * cmd /c が Windows 限定 (PS 5.1 NativeCommandError 回避用、複数箇所で使用)
            * Get-Process -Name による Windows プロセス名解決依存
            * Tera-station NAS UNC パス前提

    実行ポリシー制限時:
        Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

    エンコーディング: UTF-8 BOM 付き（BOM 無し UTF-8 は PS 5.1 で CP932 と誤検出
    されるため、BOM で UTF-8 を明示する。BOM を削除する場合は事前に必ず
    Set-Content -Encoding UTF8 で再保存して BOM を復元すること）。
#>

[CmdletBinding()]
param(
    [string]$ExpectedHead,
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$RollbackOnly,
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

# ----------------------------------------------------------------------
# 定数
# ----------------------------------------------------------------------

$REPO_DIR = "$HOME\Projects\wiseman-auto-sys"
$DIST_DIR = "$HOME\wiseman-hub"
$EXE_NAME = "wiseman_hub.exe"
$DIST_EXE = Join-Path $DIST_DIR $EXE_NAME
$BUILD_EXE = "dist\$EXE_NAME"
$BUILD_LOG = "build.log"

# pyinstaller warning の無害 allow-list
# (macOS build でも出る既知の無害 warning。プロジェクト由来 hidden import 不足
#  だけを stop シグナルとして扱う)
$BENIGN_WARNINGS = @(
    "pycparser.lextab",
    "pycparser.yacctab",
    "jinja2",
    "user32",
    "msvcrt"
)

# ----------------------------------------------------------------------
# ヘルパー
# ----------------------------------------------------------------------

function Write-Phase {
    param([string]$Title)
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Message)
    Write-Host "  → $Message" -ForegroundColor Yellow
}

function Write-OK {
    param([string]$Message)
    Write-Host "  ✓ $Message" -ForegroundColor Green
}

function Write-Err {
    param([string]$Message)
    Write-Host "  ✗ $Message" -ForegroundColor Red
}

function Stop-WithError {
    param(
        [string]$Message,
        [int]$ExitCode = 1,
        [switch]$BeforeDeploy
    )
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host "  停止: $Message" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Red
    if ($BeforeDeploy) {
        Write-Host "  Phase 2 上書き前のため、本田様 PC の現行 exe は無傷です。"
        Write-Host "  rollback は不要（まだ Phase 2 配布前）。"
    } else {
        Write-Host "  Phase 2 以降での停止です。配布先 exe の状態を確認してください:"
        Write-Host "    Get-Item `"$DIST_EXE`" | Format-List Name, Length, LastWriteTime"
        Write-Host "  必要なら rollback: .\scripts\deploy-windows.ps1 -RollbackOnly"
    }
    exit $ExitCode
}

function Confirm-Or-Abort {
    param([string]$Prompt)
    if ($NoPrompt) {
        Write-Step "$Prompt → -NoPrompt 指定で自動承認"
        return
    }
    Write-Host ""
    $reply = Read-Host "$Prompt [y/N]"
    if ($reply -notmatch "^[Yy]") {
        Stop-WithError "ユーザーが処理を中断しました"
    }
}

function Get-LatestBackup {
    $backups = @(Get-ChildItem "$DIST_EXE.bak-*" -ErrorAction SilentlyContinue)
    $bak = $backups | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    return $bak
}

# 本セッションで作成したバックアップパスを保持し、auto-rollback で誤って外部 touch
# された別 .bak-* を選ばないようにする（Codex review Important #4）。
$Script:CurrentBackupPath = $null

# ----------------------------------------------------------------------
# rollback (緊急用)
# ----------------------------------------------------------------------

function Invoke-Rollback {
    param([string]$BackupPath)

    Write-Phase "Rollback: バックアップから復元"

    if ($BackupPath) {
        $bak = Get-Item -LiteralPath $BackupPath -ErrorAction SilentlyContinue
        if ($null -eq $bak) {
            Stop-WithError "指定バックアップが見つかりません: $BackupPath"
        }
    } else {
        $bak = Get-LatestBackup
        if ($null -eq $bak) {
            Stop-WithError "バックアップが見つかりません ($DIST_EXE.bak-*)"
        }
    }
    Write-Step "復元元: $($bak.Name) ($([math]::Round($bak.Length / 1MB, 1)) MB)"

    # Launcher 起動中なら止めてもらう
    $launcher = Get-Process -Name ($EXE_NAME -replace "\.exe$", "") -ErrorAction SilentlyContinue
    if ($launcher) {
        Stop-WithError "Launcher が起動中です ($($launcher.Count) プロセス)。Launcher を閉じてから rollback を再実行してください。"
    }

    Copy-Item -Force -LiteralPath $bak.FullName -Destination $DIST_EXE
    Write-OK "復元完了: $DIST_EXE"

    $restored = Get-Item -LiteralPath $DIST_EXE
    Write-Host "    LastWriteTime: $($restored.LastWriteTime)"
    Write-Host "    Size: $([math]::Round($restored.Length / 1MB, 1)) MB"
    Write-Host ""
    Write-OK "Rollback 完了。Launcher を起動して旧版動作を確認してください: Start-Process `"$DIST_EXE`""
}

if ($RollbackOnly) {
    Invoke-Rollback
    exit 0
}

# ----------------------------------------------------------------------
# Phase 0-1: リポジトリ最新化
# ----------------------------------------------------------------------

Write-Phase "Phase 0-1: リポジトリ最新化"

if (-not (Test-Path $REPO_DIR)) {
    Stop-WithError "リポジトリディレクトリが存在しません: $REPO_DIR"
}

Set-Location $REPO_DIR
Write-Step "git checkout main"
# PS 5.1 では `git 2>&1 | Out-Null` で stderr が NativeCommandError 扱いになり
# 失敗詳細を握り潰すため cmd /c 経由でリダイレクト (Codex review Important #2)。
$checkoutOutput = cmd /c "git checkout main 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host $checkoutOutput
    Stop-WithError "git checkout main 失敗 (working tree dirty の可能性)" -BeforeDeploy
}

Write-Step "git pull --ff-only"
$pullOutput = cmd /c "git pull --ff-only 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host $pullOutput
    Stop-WithError "git pull 失敗" -BeforeDeploy
}

$head = (cmd /c "git rev-parse --short HEAD 2>&1").Trim()
if ($LASTEXITCODE -ne 0 -or -not $head) {
    Stop-WithError "git rev-parse 失敗 ($head)" -BeforeDeploy
}
Write-OK "HEAD: $head"

if ($ExpectedHead -and $head -ne $ExpectedHead) {
    Stop-WithError "HEAD 不一致: expected=$ExpectedHead, actual=$head" -BeforeDeploy
}

Write-Host ""
Write-Host "  直近 5 commit:"
$gitLog = cmd /c "git log --oneline -5"
$gitLog | ForEach-Object { Write-Host "    $_" }

# ----------------------------------------------------------------------
# Phase 0-2: 現行 exe バックアップ
# ----------------------------------------------------------------------

Write-Phase "Phase 0-2: 現行 exe バックアップ（rollback 用、必須）"

if (-not (Test-Path -LiteralPath $DIST_DIR)) {
    Stop-WithError "配布ディレクトリが存在しません: $DIST_DIR (初回配布は手動 runbook 経由で実施)" -BeforeDeploy
}

# fail-closed: 現行 exe が無いと rollback 経路が無くなるため停止 (Codex review Important #3)。
# 初回配布は手動 runbook 経由 (PowerShell から `Copy-Item` 等) で実施する。
if (-not (Test-Path -LiteralPath $DIST_EXE -PathType Leaf)) {
    Stop-WithError "現行 exe が存在しないため rollback 用バックアップを作成できません: $DIST_EXE (初回配布は手動 runbook 経由)" -BeforeDeploy
}

# 件数アサーション: before/after でバックアップ数が +1 になることを確認
$beforeCount = @(Get-ChildItem "$DIST_EXE.bak-*" -ErrorAction SilentlyContinue).Count

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bakPath = "$DIST_EXE.bak-$stamp"
Copy-Item -LiteralPath $DIST_EXE -Destination $bakPath
Write-OK "バックアップ作成: $bakPath"

$afterCount = @(Get-ChildItem "$DIST_EXE.bak-*" -ErrorAction SilentlyContinue).Count
if ($afterCount -ne ($beforeCount + 1)) {
    Stop-WithError "バックアップ件数不一致: before=$beforeCount, after=$afterCount" -BeforeDeploy
}

# サイズ照合
$bakSize = (Get-Item -LiteralPath $bakPath).Length
$exeSize = (Get-Item -LiteralPath $DIST_EXE).Length
if ($bakSize -ne $exeSize) {
    Stop-WithError "バックアップサイズ不一致: bak=$bakSize, exe=$exeSize" -BeforeDeploy
}

# Phase 2 の auto-rollback で誤って外部 touch された別 .bak-* を選ばないよう
# 本セッション作成バックアップのパスを保持。
$Script:CurrentBackupPath = $bakPath

# 古いバックアップ数を表示（cleanup 判断材料）
Write-Host "    バックアップ総数: $afterCount (3 日経過分は手動で Remove-Item 可能)"

# ----------------------------------------------------------------------
# Phase 0-3: 依存同期
# ----------------------------------------------------------------------

Write-Phase "Phase 0-3: 依存同期 (uv sync --extra dev)"

Write-Step "uv sync --extra dev (dev extras 含む、pyinstaller / pytest / ruff / mypy 必須)"
# pyinstaller と同様、PS 5.1 NativeCommandError 回避で cmd /c 経由 (Codex C2 と一貫性)。
cmd /c "uv sync --extra dev 2>&1"
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "uv sync 失敗 (.venv 破損なら Remove-Item .venv -Recurse -Force 後再実行)" -BeforeDeploy
}
Write-OK "依存同期完了"

# ----------------------------------------------------------------------
# Phase 0-4: テスト実行
# ----------------------------------------------------------------------

if ($SkipTests) {
    Write-Phase "Phase 0-4: テストスキップ (-SkipTests 指定)"
    Write-Step "WARNING: 本番配布で -SkipTests を使うのは緊急 hotfix のみ。通常運用では指定しない。"
} else {
    Write-Phase "Phase 0-4: テスト実行 (uv run pytest -q -m 'not integration')"
    Write-Step "integration 除外 (VS Build Tools 不要、WisemanMock.exe ビルド回避)"

    # cmd /c 経由で stderr 統合 (Codex C2 と一貫性)。pytest 出力は stdout/stderr 混在で
    # PS 5.1 ネイティブ実行だと意図しない停止が発生しうる。
    # Issue #316 対応: TclError 連発が出た場合に diagnose-tcl.ps1 への誘導を出すため
    # 出力を捕捉する (テンポラリファイル経由、PS 5.1 でも安定動作)。
    $pytestLog = New-TemporaryFile
    try {
        cmd /c "uv run pytest -q -m `"not integration`" 2>&1" | Tee-Object -FilePath $pytestLog.FullName
        if ($LASTEXITCODE -ne 0) {
            $logContent = Get-Content -LiteralPath $pytestLog.FullName -Raw -ErrorAction SilentlyContinue
            if ($logContent -match "TclError|init\.tcl|tcl_findLibrary") {
                Write-Host ""
                Write-Host "⚠️  Tcl 関連エラー検出 (Issue #316)" -ForegroundColor Yellow
                Write-Host "    AV 動的スキャン干渉の可能性が高い。診断:" -ForegroundColor Yellow
                Write-Host "      .\scripts\diagnose-tcl.ps1" -ForegroundColor Yellow
                Write-Host "    対処手順: docs\handoff\1c-exe-redistribution-runbook.md" -ForegroundColor Yellow
                Write-Host "             の 「🔬 Tcl init.tcl 連発失敗時の対処」セクション" -ForegroundColor Yellow
                Write-Host "    暫定回避: .\scripts\deploy-windows.ps1 -SkipTests" -ForegroundColor Yellow
                Write-Host '             (CI が PASS の前提でのみ使用、main ブランチで [gh run list] を要確認)' -ForegroundColor Yellow
                Write-Host ""
            }
            Stop-WithError "pytest 失敗 → Phase 1 (build) に進まず原因を共有" -BeforeDeploy
        }
        Write-OK "テスト PASS"
    } finally {
        Remove-Item -LiteralPath $pytestLog.FullName -ErrorAction SilentlyContinue
    }
}

# ----------------------------------------------------------------------
# Phase 1: clean build
# ----------------------------------------------------------------------

if ($SkipBuild) {
    Write-Phase "Phase 1: build スキップ (-SkipBuild 指定)"
    Write-Step "WARNING: 既存の $BUILD_EXE を流用します（デバッグ用）"
    if (-not (Test-Path -LiteralPath $BUILD_EXE)) {
        Stop-WithError "build スキップ指定だが $BUILD_EXE が存在しません" -BeforeDeploy
    }
} else {
    Write-Phase "Phase 1: clean build (pyinstaller wiseman_hub.spec)"

    Write-Step "uv run pyinstaller wiseman_hub.spec --clean --noconfirm"
    # PS 5.1 + native command の `2>&1` は stderr を NativeCommandError 扱いにする
    # ことがあり、pyinstaller の正常ビルド中の stderr で途中停止する。cmd /c 経由
    # にして 1 つのストリームに統合してから Tee する (Codex review Important #2)。
    cmd /c "uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1" |
        Tee-Object -FilePath $BUILD_LOG |
        Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "pyinstaller 失敗 → $BUILD_LOG を共有" -BeforeDeploy
    }

    Write-Step "warning 検査 (プロジェクト由来 hidden import 不足の検出)"
    # Select-String 単発で取得し、後続で手動フィルタ（パイプチェーンは PS で壊れやすい）
    $warnings = Select-String -Path $BUILD_LOG -Pattern "Hidden import.*not found" -ErrorAction SilentlyContinue
    $bad = @()
    foreach ($w in $warnings) {
        $line = $w.Line
        $isBenign = $false
        foreach ($pattern in $BENIGN_WARNINGS) {
            if ($line -match [regex]::Escape($pattern)) {
                $isBenign = $true
                break
            }
        }
        if (-not $isBenign) {
            $bad += $line
        }
    }
    if ($bad.Count -gt 0) {
        Write-Err "プロジェクト由来の hidden import 警告を検出 ($($bad.Count) 件):"
        $bad | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        Stop-WithError "spec の hiddenimports 不足 → $BUILD_LOG を共有して原因調査" -BeforeDeploy
    }
    Write-OK "warning 無し（プロジェクト由来）"
}

Write-Step "build 成果物確認"
if (-not (Test-Path -LiteralPath $BUILD_EXE)) {
    Stop-WithError "build 成果物が存在しません: $BUILD_EXE" -BeforeDeploy
}
$built = Get-Item $BUILD_EXE
Write-OK "$BUILD_EXE ($([math]::Round($built.Length / 1MB, 1)) MB, $($built.LastWriteTime))"

# ----------------------------------------------------------------------
# Phase 2: 配布 (実機 exe 上書き)
# ----------------------------------------------------------------------

Write-Phase "Phase 2: 配布 (Copy-Item -Force)"

# Launcher プロセス検出 (起動中なら file lock で Copy-Item 失敗するため事前停止依頼)
$procName = $EXE_NAME -replace "\.exe$", ""
$launcher = Get-Process -Name $procName -ErrorAction SilentlyContinue
if ($launcher) {
    Write-Err "Launcher が起動中です ($($launcher.Count) プロセス)"
    Write-Host "    Launcher を閉じてから本スクリプトを再実行してください。" -ForegroundColor Yellow
    Write-Host "    或いは:  Stop-Process -Name $procName -Force"
    Stop-WithError "Launcher 起動中で file lock のリスク" -BeforeDeploy
}

Confirm-Or-Abort "Phase 2 で $DIST_EXE を上書きします。続行しますか？"

try {
    Copy-Item -Force -LiteralPath $BUILD_EXE -Destination $DIST_EXE
} catch {
    $copyErr = $_.Exception.Message
    Write-Err "Copy-Item 失敗: $copyErr"
    Write-Step "auto-rollback 実行中 (本セッション作成バックアップ: $Script:CurrentBackupPath)..."
    # auto-rollback 自体が失敗するケース (NAS 切断 / 権限不足) を捕捉。
    # 二段失敗時は配布先 exe が中途半端な状態で残るため、手動復旧手順を明示。
    try {
        Invoke-Rollback -BackupPath $Script:CurrentBackupPath
    } catch {
        $rollbackErr = $_.Exception.Message
        Write-Host ""
        Write-Host "================================================================" -ForegroundColor Red
        Write-Host "  CRITICAL: 配布失敗かつ auto-rollback も失敗" -ForegroundColor Red
        Write-Host "================================================================" -ForegroundColor Red
        Write-Host "  配布先 exe ($DIST_EXE) が中途半端な状態の可能性があります。"
        Write-Host ""
        Write-Host "  手動復旧手順 (PowerShell で実行):" -ForegroundColor Yellow
        Write-Host "    Copy-Item -Force `"$Script:CurrentBackupPath`" `"$DIST_EXE`""
        Write-Host "    Get-Item `"$DIST_EXE`" | Format-List Name, Length, LastWriteTime"
        Write-Host ""
        Write-Host "  原因候補:" -ForegroundColor Yellow
        Write-Host "    - Copy エラー: $copyErr"
        Write-Host "    - Rollback エラー: $rollbackErr"
        exit 1
    }
    Stop-WithError "配布失敗 → rollback 完了済 (Copy エラー: $copyErr)"
}

$deployed = Get-Item $DIST_EXE
Write-OK "配布完了: $DIST_EXE"
Write-Host "    LastWriteTime: $($deployed.LastWriteTime)"
Write-Host "    Size: $([math]::Round($deployed.Length / 1MB, 1)) MB"

# 件数アサーション: 配布後の exe サイズが build と一致
if ($deployed.Length -ne $built.Length) {
    Write-Err "配布後サイズ不一致 (build=$($built.Length), deployed=$($deployed.Length))"
    Write-Step "auto-rollback 実行中 (本セッション作成バックアップ: $Script:CurrentBackupPath)..."
    try {
        Invoke-Rollback -BackupPath $Script:CurrentBackupPath
    } catch {
        $rollbackErr = $_.Exception.Message
        Write-Host ""
        Write-Host "================================================================" -ForegroundColor Red
        Write-Host "  CRITICAL: サイズ不一致かつ auto-rollback も失敗" -ForegroundColor Red
        Write-Host "================================================================" -ForegroundColor Red
        Write-Host "  手動復旧手順:" -ForegroundColor Yellow
        Write-Host "    Copy-Item -Force `"$Script:CurrentBackupPath`" `"$DIST_EXE`""
        Write-Host "    Rollback エラー: $rollbackErr"
        exit 1
    }
    Stop-WithError "サイズ不一致 → rollback 完了済"
}

# ----------------------------------------------------------------------
# Phase 3: Launcher 起動 + 動作確認チェックリスト
# ----------------------------------------------------------------------

Write-Phase "Phase 3: Launcher 起動"

Write-Step "Start-Process $DIST_EXE"
Start-Process $DIST_EXE

# プロセス起動確認（最大 10 秒待機）
$started = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    $launcher = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($launcher) {
        $started = $true
        break
    }
}
if (-not $started) {
    Write-Err "Launcher プロセスが起動しません (10 秒経過)"
    Write-Host "    Windows Defender 隔離 / SmartScreen ブロックの可能性。"
    Write-Host "    手動で $DIST_EXE をダブルクリックして確認してください。" -ForegroundColor Yellow
    Write-Host "    起動しない場合は rollback: .\scripts\deploy-windows.ps1 -RollbackOnly" -ForegroundColor Yellow
    exit 2
}
Write-OK "Launcher プロセス起動確認 ($($launcher.Count) プロセス)"

# ----------------------------------------------------------------------
# Phase 4: 動作確認チェックリスト（人手判定）
# ----------------------------------------------------------------------

Write-Phase "Phase 4: 動作確認チェックリスト（人手判定）"

Write-Host ""
Write-Host "  Launcher ウィンドウを目視確認してください:" -ForegroundColor Yellow
Write-Host ""
Write-Host "    [ ] 1. Launcher 「Wiseman PDF ツール」が起動 (コンソール窓なし)"
Write-Host "    [ ] 2. ボタン 5 個表示:"
Write-Host "           - A: ex_ ファイル変換 + 振り分け"
Write-Host "           - B: 運動機能向上計画書 自動配置"
Write-Host "           - C: 経過報告書 自動配置"
Write-Host "           - 事業所フォルダ一括結合"
Write-Host "           - 設定"
Write-Host "    [ ] 3. 各ボタンクリックで ImportError / ModuleNotFoundError が出ない"
Write-Host "    [ ] 4. 機能追加 PR がある場合は対応する UI 変化を確認"
Write-Host "           (今回の例: B の R<年> フォルダ走査 / A の '(未設定)' Label)"
Write-Host ""
Write-Host "  失敗時:" -ForegroundColor Yellow
Write-Host "    rollback: .\scripts\deploy-windows.ps1 -RollbackOnly"
Write-Host ""
Write-Host "  3 日以上動作問題なければ古いバックアップ削除可:" -ForegroundColor DarkGray
Write-Host "    # CLAUDE.md MUST: 件数アサーション必須、ワイルドカード一行詰め"
Write-Host "    `$bk = @(Get-ChildItem `"$DIST_EXE.bak-*`" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3)"
Write-Host "    if (`$bk.Count -gt 0) { `$bk | ForEach-Object { Write-Host `$_.Name }; Remove-Item -LiteralPath `$bk.FullName }"
Write-Host "    # 配布先はローカル ($DIST_DIR) で NAS パスではないが、コピペ時は配布先を再確認"
Write-Host ""

Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Phase 0-3 自動化完了。Phase 4 はチェックリストで判定してください。" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
