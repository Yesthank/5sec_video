# 5sec_video

화면의 특정 영역을 선택해서 짧은 영상을 `.mp4`로 저장하는 윈도우 데스크톱 도구.
Win+Shift+S 캡처 도구처럼 영역을 드래그로 지정하고, 녹화 버튼을 누르면 그 영역만 녹화됩니다.

> 현재 상태: **MVP 완료**. 전체 계획과 결정 사항은 [PLAN.md](PLAN.md) 참고.

## 주요 기능 (목표)

- 시스템 트레이에서 대기 → 아이콘 클릭 시 영역 선택 모드 진입
- 마우스 드래그로 녹화할 화면 영역 지정 (재클릭 시 영역 초기화 후 재지정)
- 녹화 / 중지 토글 버튼 + 경과 시간 표시
- **10 / 30 / 60 fps** 선택 가능
- 마우스 커서는 녹화 영상에 포함되지 않음
- 저장 경로와 파일명 템플릿 지정 가능 (ComfyUI VideoCombine 노드 스타일)
  - 예: `clip_%Y%m%d_%H%M%S` → `clip_20260415_143052.mp4`
- 오디오는 MVP에서 제외 (영상만)

## 요구사항

- **OS**: Windows 10 / 11
- **Python**: 3.10 이상 권장

## 설치 방법

```bash
# 1. 저장소 클론 또는 폴더 복사
cd 5sec_video

# 2. 가상환경 생성 및 활성화
python -m venv .venv
.venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt
```

### 사용 라이브러리

| 패키지 | 용도 |
|---|---|
| `PySide6` | 영역 선택 오버레이 / 컨트롤 바 / 트레이 아이콘 / 설정 다이얼로그 |
| `mss` | 빠른 화면 캡처 (멀티 모니터 지원) |
| `opencv-python` | mp4 인코딩 (`cv2.VideoWriter`, `mp4v` 코덱) |
| `numpy` | 캡처된 프레임 변환 |

## .exe 빌드 (PyInstaller)

소스 없이 다른 컴퓨터에서 실행 가능한 단일 실행 파일을 만들 수 있습니다.

```bash
# 1. PyInstaller 설치 (가상환경 활성화 상태에서)
pip install pyinstaller

# 2. 빌드
build.bat
# 또는 직접:
pyinstaller --clean --noconfirm 5sec_video.spec
```

빌드 결과: **`dist/5sec_video.exe`** (단일 파일, ~90MB, 콘솔 없음)

`5sec_video.exe`만 복사하면 다른 윈도우 PC에서 파이썬 설치 없이 실행됩니다. 첫 실행 시 같은 폴더에 `config.json` 과 `recordings/` 가 자동으로 생성됩니다.

> 빌드 설정 파일: [5sec_video.spec](5sec_video.spec) — `--noconsole`(트레이 앱), 사용하지 않는 PySide6 모듈 제외로 크기 최적화

## 사용 방법

### 일반 사용 (트레이 앱)

```bash
python main.py
# 또는 빌드한 경우:
dist\5sec_video.exe
```

1. 시스템 트레이에 빨간 원 아이콘이 표시됩니다 (윈도우 작업표시줄 우측 알림 영역)
2. 트레이 아이콘 **클릭** → 화면이 어두워지면 마우스 드래그로 녹화할 영역 지정
   - 영역을 다시 잡고 싶으면 트레이 아이콘을 한 번 더 클릭하면 초기화됩니다
3. 컨트롤 바가 영역 위쪽에 표시됩니다
   - **● Rec** 클릭 → 녹화 시작 (버튼이 ■ Stop으로 변경, 경과 시간 카운트)
   - **■ Stop** 클릭 → mp4로 저장 (트레이 알림에 파일명 표시)
   - FPS 콤보로 10/30/60 선택 가능 (녹화 중에는 잠금)
   - 컨트롤 바는 빈 영역을 드래그해서 옮길 수 있습니다 (녹화 영역 밖으로 빼두세요)
   - **✕** 클릭 → 종료
4. 트레이 아이콘 **우클릭** → 메뉴
   - **영역 지정** — 새 영역 지정 시작
   - **설정...** — 저장 폴더 / 파일명 템플릿 / 기본 FPS 변경
   - **종료** — 앱 종료

### 모듈 단위 테스트

각 모듈은 독립적으로 실행해 동작을 확인할 수 있습니다.

### Step 5 — settings 다이얼로그 단독 테스트

```bash
python -m src.settings_dialog
```

저장 폴더 / 파일명 템플릿 / 기본 FPS를 설정하고 OK를 누르면 `config.json`에 저장됩니다.
파일명 템플릿 토큰: `%Y %m %d %H %M %S`, `%counter%` (4자리 자동 증가). 입력하면 미리보기가 실시간으로 갱신됩니다.

### Step 4 — controller 단독 테스트 (overlay + recorder 통합)

영역을 드래그로 선택하면 컨트롤 바가 떠서 실제 녹화/중지가 가능합니다.

```bash
python -m src.controller
```

- 영역 드래그 → 컨트롤 바 표시
- `● Rec` 클릭 → 녹화 시작, 버튼이 `■ Stop`으로 변경
- `■ Stop` 클릭 → mp4 저장
- FPS 콤보로 10/30/60 선택 (녹화 중에는 비활성화)
- 컨트롤 바는 빈 영역을 드래그해서 이동 가능
- `✕` 클릭 → 종료

### Step 3 — overlay 단독 테스트

풀스크린 오버레이를 띄우고 드래그로 영역을 선택합니다. 선택한 영역의 좌표가 콘솔에 출력됩니다.

```bash
python -m src.overlay
```

- 좌클릭 + 드래그: 영역 지정
- ESC 또는 우클릭: 취소

### Step 2 — recorder 단독 테스트

지정한 좌표/크기 영역을 N초간 녹화해서 mp4로 저장합니다.

```bash
# 가상환경 활성화 후
python -m src.recorder --x 100 --y 100 --w 640 --h 360 --fps 30 --seconds 3
```

옵션:
- `--x, --y` — 캡처 영역의 좌상단 좌표
- `--w, --h` — 캡처 영역의 폭과 높이 (홀수면 자동으로 1픽셀 잘라냄)
- `--fps` — 10, 30, 60 중 선택
- `--seconds` — 녹화 길이(초)
- `--out` — 출력 mp4 경로 (기본값: `recordings/test_YYYYMMDD_HHMMSS.mp4`)

## 폴더 구조

```
5sec_video/
├── PLAN.md                  # 개발 계획 / 결정 사항
├── README.md                # 본 문서
├── requirements.txt
├── config.json              # save_dir, filename_template, fps 기본값
├── 5sec_video.spec          # PyInstaller 빌드 설정
├── build.bat                # 윈도우 빌드 스크립트
├── main.py                  # 트레이 + 오버레이 + 컨트롤 + 녹화 통합 진입점
├── recordings/              # 기본 저장 폴더
└── src/
    ├── overlay.py           # 풀스크린 영역 선택 오버레이
    ├── controller.py        # 녹화/중지 컨트롤 바
    ├── recorder.py          # mss + cv2 화면 캡처 / mp4 인코딩
    ├── config.py            # config.json 로드/저장 + 파일명 템플릿 처리
    └── settings_dialog.py   # 저장 경로/파일명/FPS 설정 UI
```

## 개발 진행 상황

- [x] Step 1 — 프로젝트 스캐폴드 + requirements.txt
- [x] Step 2 — `recorder.py` 영역 캡처 → mp4 저장
- [x] Step 3 — `overlay.py` 드래그 영역 선택 오버레이
- [x] Step 4 — `controller.py` 녹화/중지 컨트롤 바
- [x] Step 5 — `config.py` + `settings_dialog.py` 저장 설정
- [x] Step 6 — `main.py` 트레이 통합
- [x] Step 7 — 코드 리뷰 + 정리
