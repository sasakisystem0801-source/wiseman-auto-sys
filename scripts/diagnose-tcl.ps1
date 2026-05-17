<#
.SYNOPSIS
    本田様 PC で発生する Tcl init.tcl read failure (Issue #316) の診断スクリプト。

.DESCRIPTION
    `uv run pytest` 実行時に intermittent で発生する
    `_tkinter.TclError: Can't find a usable init.tcl` /
    `couldn't read file ...init.tcl: No error` の切り分けを支援する。

    過去事例 (Issue #316) では AV 動的スキャン干渉 (errno=0 で read fail +
    intermittent パターン) が主因として観察されているが、将来別原因 (SMB/UNC
    経路、Python distribution 不整合、ファイルシステム破損等) が判明する
    可能性もあるため、本スクリプトは仮説を断定せず以下を順に確認して
    判断材料を出す:

        1. Python install path と init.tcl 実在 / サイズ確認
        2. [System.IO.File]::ReadAllBytes で init.tcl の read 試行 (5 回)
        3. tk.Tk() 起動試行 (10 回、intermittent 性確認)
        4. Windows Defender 状態と除外設定一覧
        5. 第三者 AV プロセス検出 (Trend Micro / Kaspersky / Norton / McAfee 等)
           注: プロセス名による検出のため candidate レベル。確定には GUI 確認推奨

    実行後、`docs/handoff/1c-exe-redistribution-runbook.md` の
    「🔬 Tcl init.tcl 連発失敗時の対処」セクションに従って対処してください。

.EXAMPLE
    .\scripts\diagnose-tcl.ps1

.NOTES
    対応シェル: Windows PowerShell 5.1+ / PowerShell 7+ (Windows のみ)
    関連 Issue: #316, #276
#>

$ErrorActionPreference = "Continue"  # 診断スクリプトは fail-open で全項目走査

function Write-Section($msg) {
    Write-Host ""
    Write-Host "==== $msg ====" -ForegroundColor Cyan
}

function Write-OK($msg)    { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

# ----------------------------------------------------------------------
# 1. Python install path と init.tcl 実在確認
# ----------------------------------------------------------------------
Write-Section "1. Python / Tcl ファイル実在確認"

$pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    Write-Fail "python が PATH に無い (Microsoft Store stub の可能性)"
    Write-Host "  対処: python.org から MSI で再 install、または `uv python install 3.11`"
} else {
    Write-OK "python.exe: $pythonExe"
    $pythonRoot = Split-Path $pythonExe -Parent
    $initTcl = Join-Path $pythonRoot "tcl\tcl8.6\init.tcl"

    if (-not (Test-Path -LiteralPath $initTcl)) {
        Write-Fail "init.tcl が見つからない: $initTcl"
        Write-Host "  対処: Python 再 install (python.org の MSI installer)"
    } else {
        $item = Get-Item -LiteralPath $initTcl
        Write-OK "init.tcl: $initTcl (Length=$($item.Length) bytes, Mode=$($item.Mode))"
        if ($item.Length -lt 20000) {
            Write-Warn "サイズが想定より小さい (通常 25000+ bytes)、Python 再 install 推奨"
        }
    }
}

# ----------------------------------------------------------------------
# 2. init.tcl read 試行 (5 回)
# ----------------------------------------------------------------------
Write-Section "2. init.tcl read 試行 (5 回連続、intermittent fail 検出)"

if ($pythonExe -and (Test-Path -LiteralPath $initTcl)) {
    $readFailCount = 0
    1..5 | ForEach-Object {
        # PowerShell の catch スコープ内では $_ が ErrorRecord に上書きされるため、
        # ForEach-Object のループ変数を直前で退避してから try に入る (Issue #319 review feedback)。
        $attempt = $_
        try {
            $bytes = [System.IO.File]::ReadAllBytes($initTcl)
            Write-Host ("  attempt {0}: OK ({1} bytes)" -f $attempt, $bytes.Length) -ForegroundColor Gray
        } catch {
            $readFailCount++
            Write-Fail ("attempt {0}: read 失敗 — {1}" -f $attempt, $_.Exception.Message)
        }
        Start-Sleep -Milliseconds 200
    }
    if ($readFailCount -eq 0) {
        Write-OK "5 回連続 read 成功 (この瞬間は file lock なし)"
        Write-Host "  注: tkinter からの read は別経路。次の tk.Tk() 試行で再確認"
    } else {
        Write-Fail "$readFailCount / 5 で read 失敗 — AV 干渉強く疑う"
    }
}

# ----------------------------------------------------------------------
# 3. tk.Tk() 起動試行 (10 回、intermittent 性確認)
# ----------------------------------------------------------------------
Write-Section "3. tk.Tk() 起動試行 (10 回、intermittent 検出)"

if ($pythonExe) {
    $tkScript = @'
import sys
import tkinter
try:
    root = tkinter.Tk()
    root.withdraw()
    root.destroy()
    print("OK")
    sys.exit(0)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
'@
    $tkFailCount = 0
    $tkErrors = @{}
    1..10 | ForEach-Object {
        $result = & $pythonExe -c $tkScript 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host ("  attempt {0}: OK" -f $_) -ForegroundColor Gray
        } else {
            $tkFailCount++
            Write-Fail ("attempt {0}: {1}" -f $_, $result)
            $key = "$result"
            if ($tkErrors.ContainsKey($key)) {
                $tkErrors[$key]++
            } else {
                $tkErrors[$key] = 1
            }
        }
        Start-Sleep -Milliseconds 300
    }

    Write-Host ""
    if ($tkFailCount -eq 0) {
        Write-OK "10 回連続 tk.Tk() 成功 (現時点で問題再現せず)"
        Write-Host "  注: pytest 起動時のみ発生する場合あり (subprocess 起動頻度 + AV scan の組合せ)"
    } elseif ($tkFailCount -lt 10) {
        Write-Fail "$tkFailCount / 10 で tk.Tk() 失敗 — intermittent パターン確認"
        Write-Host "  → 典型的な AV 動的スキャン干渉。runbook の対処手順 1-2 を実施"
    } else {
        Write-Fail "10 / 10 全て tk.Tk() 失敗 — 環境破損レベル"
        Write-Host "  → Python 再 install (対処手順 3) または uv-managed Python 切替 (対処手順 4)"
    }

    if ($tkErrors.Count -gt 0) {
        Write-Host "  エラーパターン集計:"
        $tkErrors.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object {
            Write-Host ("    [{0} 回] {1}" -f $_.Value, $_.Key)
        }
    }
}

# ----------------------------------------------------------------------
# 4. Windows Defender 状態と除外設定
# ----------------------------------------------------------------------
Write-Section "4. Windows Defender 状態 + 除外設定"

try {
    $mp = Get-MpPreference -ErrorAction Stop
    Write-OK "Get-MpPreference 取得成功 (Defender 動作中)"

    $excluded = @($mp.ExclusionPath)
    $excluded = $excluded | Where-Object { $_ }  # null 除去
    if ($excluded.Count -eq 0) {
        Write-Warn "ExclusionPath が空。AppData\Programs\Python\Python311 の除外設定なし"
    } else {
        Write-Host "  現在の除外パス:"
        $excluded | ForEach-Object { Write-Host "    - $_" }
        $hasPython = $excluded | Where-Object { $_ -match "Python|tcl" }
        if ($hasPython) {
            Write-OK "Python / Tcl 関連の除外あり"
        } else {
            Write-Warn "Python / Tcl 関連の除外なし → 対処手順 1 を実施"
        }
    }

    if ($mp.DisableRealtimeMonitoring) {
        Write-OK "Real-time monitoring 無効 (AV 干渉の可能性低い)"
    } else {
        Write-Host "  Real-time monitoring: 有効 (通常設定)"
    }
} catch {
    Write-Warn "Get-MpPreference 失敗: $($_.Exception.Message)"
    Write-Host "  Tamper Protection 有効か、第三者 AV が Defender を無効化している可能性"
    Write-Host "  対処: Windows セキュリティ GUI から除外設定 (対処手順 1)"
}

# ----------------------------------------------------------------------
# 5. 第三者 AV プロセス検出
# ----------------------------------------------------------------------
Write-Section "5. 第三者 AV プロセス検出"

$avPatterns = @{
    "Trend Micro"  = @("tmpfw", "tmlisten", "PccNTMon", "TmListen", "TMBMSRV")
    "Kaspersky"    = @("avp", "kavfs", "ksde")
    "Norton"       = @("NortonSecurity", "nortonsecurity", "ccSvcHst")
    "McAfee"       = @("mcshield", "McUICnt", "mfemms")
    "ESET"         = @("ekrn", "egui")
    "Avast"        = @("AvastUI", "AvastSvc", "afwServ")
    "AVG"          = @("AVGUI", "avgsvc")
    "Bitdefender"  = @("bdagent", "vsserv")
    "Sophos"       = @("SAVService", "SophosUI")
}

$foundAv = @()
foreach ($vendor in $avPatterns.Keys) {
    foreach ($procName in $avPatterns[$vendor]) {
        $proc = Get-Process -Name $procName -ErrorAction SilentlyContinue
        if ($proc) {
            $foundAv += "$vendor ($procName)"
            break  # 1 ベンダー 1 行で十分
        }
    }
}

if ($foundAv.Count -eq 0) {
    Write-OK "既知の第三者 AV プロセスは検出されず (Defender のみと推定)"
} else {
    Write-Warn "第三者 AV 検出 (候補): $($foundAv -join ', ')"
    Write-Host "  注: プロセス名一致のみで判定。同名の非 AV 製品 (Symantec の汎用ホスト等) の"
    Write-Host "      可能性もあるため、コントロールパネルや GUI で AV 製品を確実に特定すること。"
    Write-Host "  対処: 検出された AV ベンダーの GUI から AppData\Programs\Python\Python311 除外 (対処手順 2)"
}

# ----------------------------------------------------------------------
# 結果サマリー + 次のアクション
# ----------------------------------------------------------------------
Write-Section "結果サマリー"

Write-Host "詳細な対処手順:"
Write-Host "  docs/handoff/1c-exe-redistribution-runbook.md の"
Write-Host "  「🔬 Tcl init.tcl 連発失敗時の対処 (Issue #316)」セクション参照"
Write-Host ""
Write-Host "結果を Issue #316 にコメントするときは、本スクリプトの出力全体を貼ってください。"
Write-Host "  gh issue comment 316 --body-file <diagnose-output.txt>"
