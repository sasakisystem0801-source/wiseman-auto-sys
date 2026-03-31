# Windows 통합 테스트 실행 가이드

이 문서는 Windows 실기에서 PywinautoEngine 통합 테스트를 실행하고 디버깅하는 방법을 설명합니다.

## 사전 요구사항

- Windows 10 / 11
- Python 3.11+ (uv 설치됨)
- MSBuild (Visual Studio 또는 Build Tools)
- .NET Framework 4.8.1 이상

## 테스트 실행

### 1단계: 저장소 업데이트

```powershell
cd C:\path\to\wiseman_auto_sys
git pull origin main
uv sync --extra dev
```

### 2단계: 모의 앱 프로세스 정리 (필수)

```powershell
Get-Process WisemanMock -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
```

### 3단계: 테스트 실행

```powershell
# 모든 통합 테스트 실행
uv run pytest tests/integration -v -m integration --timeout=120

# 특정 테스트만 실행
uv run pytest tests/integration/test_login.py -v --timeout=120
uv run pytest tests/integration/test_navigate_menu.py -v --timeout=120
uv run pytest tests/integration/test_read_grid.py -v --timeout=120
uv run pytest tests/integration/test_export_csv.py -v --timeout=120
uv run pytest tests/integration/test_close_window.py -v --timeout=120
uv run pytest tests/integration/test_full_pipeline.py -v --timeout=120
```

## 테스트 순서

권장 실행 순서 (의존성 기반):

1. **test_login.py** — 기본: 앱 시작, 로그인
2. **test_navigate_menu.py** — 메뉴 상호작용
3. **test_read_grid.py** — 데이터 그리드 읽기
4. **test_export_csv.py** — CSV 내보내기
5. **test_close_window.py** — 창 닫기, 정리
6. **test_full_pipeline.py** — E2E 파이프라인

## 자주 발생하는 실패 패턴과 해결 방법

### 패턴 1: `launch_and_login` 실패

**증상:**
```
ElementNotFoundError: ログインウィンドウが見つかりません
```

**원인:**
- 모의 앱이 올바르게 시작되지 않음
- 창 제목이 예상과 다름

**해결 방법:**
```powershell
# 모의 앱 수동 시작 및 UI 검사
Inspect.exe  # Windows에 기본 제공
# WisemanMock.exe 창 제목과 컨트롤 확인
```

### 패턴 2: `navigate_menu` 실패

**증상:**
```
MDI 자식 창이 검출되지 않음
또는
menu_select 실패, MenuItem 클릭 폴백 실행
```

**원인:**
- MenuStrip이 UIA에서 제대로 노출되지 않음
- MenuItem 타이틀이 예상과 다름

**해결 방법:**

```python
# tests/integration/test_navigate_menu.py에 추가로 디버깅 로그 활성화
import logging
logging.basicConfig(level=logging.DEBUG)

# 또는 Inspect.exe로 MainForm의 MenuStrip 구조 확인:
# - "ケア記録" MenuItem의 정확한 제목/control_type
# - "集計表" 항목의 위치 확인
```

### 패턴 3: `read_grid_data` 실패

**증상:**
```
그리드 컨트롤을 찾을 수 없음
또는
헤더/데이터 행을 읽을 수 없음
```

**원인:**
- DataGridView가 "Table"이 아닌 다른 control_type으로 노출됨
- auto_id가 "dgvCareRecord"가 아님

**해결 방법:**

```powershell
# 1. UI 카탈로그 생성
python scripts/dump_ui.py --output data/ui_catalogs/debug_carerecord.json --text

# 2. debug_carerecord.json을 열고 "Table" 또는 "DataGrid" 검색
# → "control_type"과 "automation_id" 확인

# 3. 필요하면 pywinauto_engine.py의 read_grid_data() 업데이트:
#    control_type을 찾은 것으로 변경
#    auto_id를 실제 ID로 변경
```

### 패턴 4: `export_csv` 실패

**증상:**
```
SaveFileDialog가 나타나지 않음
또는
CSV 파일이 생성되지 않음
```

**원인:**
- btnPrint 클릭이 작동하지 않음
- SaveFileDialog의 컨트롤 구조가 예상과 다름

**해결 방법:**

```powershell
# 1. btnPrint 클릭 이후의 화면 캡처
# 수동으로 모의 앱을 실행하고 메뉴 > 인쇄 클릭
# 대화 상자가 나타나는지 확인

# 2. 대화 상자의 컨트롤 구조 확인
Inspect.exe  # 활성화된 SaveFileDialog 검사
# ↓ "파일 이름" 입력 필드의 control_type/auto_id 확인
# ↓ "저장(&S)" 버튼의 정확한 제목 확인

# 3. pywinauto_engine.py 업데이트 필요시:
#    FileNameControlHost → 실제 auto_id로 변경
#    ".*保存.*" → 실제 버튼 제목으로 변경
```

### 패턴 5: `close_wiseman` 실패

**증상:**
```
프로세스가 타임아웃됨
또는
확인 대화상자가 검출되지 않음
```

**원인:**
- btnExit 클릭이 작동하지 않음
- 확인 대화상자의 제목/컨트롤이 예상과 다름

**해결 방법:**

```powershell
# 수동 확인:
# 1. 모의 앱 > [종료] 버튼 클릭
# 2. "확인" 대화상자가 나타나고, "[예]" "[아니오]" 버튼이 표시되는지 확인
# 3. 제목과 버튼 텍스트가 정확한지 Inspect.exe로 확인
```

## 현재 알려진 제약 사항

### GitHub Actions CI (windows-latest)
- 데스크톱 세션 제약으로 인해 일부 테스트 실패 가능
- 권장: 로컬 Windows 실기 또는 TeamViewer를 통한 수동 테스트

### 윈도우 프레임워크 호환성
- .NET Framework 4.8.1 필수
- VS Build Tools 또는 Visual Studio Community 설치 필수

## 디버깅 팁

### 상세 로그 활성화

```powershell
$env:PYWINAUTO_LOG_LEVEL = "DEBUG"
uv run pytest tests/integration -v -s --timeout=120  # -s: stdout 표시
```

### 개별 단계별 테스트

```python
# 임시 테스트 스크립트: test_debug.py
from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine
from tests.integration.conftest import MOCK_APP_EXE

engine = PywinautoEngine()
try:
    # 1단계: 로그인
    engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")
    print("✓ Login OK")

    # 2단계: 메뉴
    engine.navigate_menu(["ケア記録", "集計表"])
    print("✓ Menu OK")

    # 3단계: 그리드 읽기
    data = engine.read_grid_data()
    print(f"✓ Grid OK: {len(data)} rows")

finally:
    engine.close_wiseman()
```

실행:
```powershell
uv run python test_debug.py
```

### UI 카탈로그 생성 및 분석

```powershell
# 1. 모의 앱 시작 (수동)
# 2. UI 카탈로그 생성
python scripts/dump_ui.py --text

# 3. 생성된 파일 확인
# data/ui_catalogs/YYYYMMDD_HHMMSS_*.json
# data/ui_catalogs/YYYYMMDD_HHMMSS_*.txt

# JSON 파일을 편집기에서 열고 필요한 컨트롤 찾기
```

## 테스트 결과 보고

테스트 실행 후 다음 정보를 포함하여 보고하세요:

1. **전체 결과**
   ```
   7 passed
   또는
   2 passed, 5 failed
   ```

2. **실패한 테스트와 에러 메시지**
   ```
   tests/integration/test_navigate_menu.py::TestNavigateMenu::test_navigate_to_care_record FAILED
   ElementNotFoundError: ログインウィンドウが見つかりません
   ```

3. **Windows 환경 정보**
   ```powershell
   [System.Environment]::OSVersion
   [System.Version](Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release).Release
   ```

4. **MSBuild 버전**
   ```powershell
   msbuild /version
   ```

## 다음 단계

### 모든 7개 테스트 통과 후:
1. Issue #3 진행: 실제 Wiseman 앱에서 UI 카탈로그 획득
2. Issue #6 진행: E2E 파이프라인 구현

### GitHub Actions CI 안정화 (선택):
- `xvfb-run` (Linux) 또는 VNC (Windows) 사용 검토
- 또는 통합 테스트를 로컬 테스트로 분류하고 CI에서 스킵

## 참고

- **pywinauto 문서**: https://pywinauto.readthedocs.io/
- **UIAutomation (UIA)**: Windows 자동화 표준. Inspect.exe로 확인 가능
- **WinForms MDI**: 다중 문서 인터페이스. MDI 자식 창은 MDIClient 내부의 Window 요소
