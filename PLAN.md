# 5sec_video — 화면 영역 녹화 도구

## 1. 목적
Win+Shift+S 캡처 도구처럼 화면의 **영역을 선택**하고, 그 영역을 **녹화**하여 `.mp4` 파일로 저장하는 데스크톱 도구.

## 2. 주요 기능 (MVP)
1. **영역 선택 오버레이**
   - 실행 시 전체 화면을 어둡게 덮는 반투명 오버레이 표시
   - 마우스 드래그로 사각형 영역 지정
   - ESC 키로 취소

2. **녹화 컨트롤**
   - 영역 선택 후 작은 컨트롤 바(또는 플로팅 버튼) 표시
   - **녹화 버튼** 클릭 → 녹화 시작, 버튼이 **중지 버튼**으로 변경
   - **중지 버튼** 클릭 → 녹화 종료 후 `.mp4` 저장
   - 녹화 중 경과 시간 표시

3. **저장 설정**
   - 저장 폴더 경로 지정 (기본값: `./recordings/`)
   - 파일명 템플릿 지정 (ComfyUI VideoCombine 노드 스타일)
     - 예: `clip_%Y%m%d_%H%M%S` → `clip_20260415_143052.mp4`
     - 토큰: `%Y %m %d %H %M %S`, 자동 증가 인덱스 `%counter%`
   - 설정은 `config.json`에 저장하여 다음 실행 시 복원

## 3. 기술 스택 (추천)

| 영역 | 라이브러리 | 이유 |
|---|---|---|
| GUI / 오버레이 | **PySide6** (Qt for Python) | 반투명 풀스크린 오버레이, 항상 위 표시, 프레임리스 윈도우 등 데스크톱 오버레이 UI에 최적. tkinter보다 멀티모니터/HiDPI 지원이 안정적 |
| 화면 캡처 | **mss** | 순수 파이썬, 매우 빠른 다중 모니터 캡처 (60fps 가능) |
| 비디오 인코딩 | **opencv-python** (`cv2.VideoWriter`, mp4v/H.264) | 설치 간단. 더 좋은 화질·압축이 필요하면 **ffmpeg-python**으로 교체 가능 |
| 수치 처리 | **numpy** | mss 캡처 → cv2 변환 |

> 대안: 인코딩 품질이 문제가 되면 시스템 `ffmpeg`을 호출하는 방식으로 전환. 처음에는 의존성 적은 opencv로 시작.

## 4. 폴더 구조 (계획)
```
5sec_video/
├── PLAN.md              # 본 문서
├── README.md
├── requirements.txt
├── config.json          # 저장 경로/파일명 템플릿
├── main.py              # 진입점
├── src/
│   ├── __init__.py
│   ├── overlay.py       # 영역 선택 오버레이
│   ├── controller.py    # 녹화 컨트롤 바 (녹화/중지 버튼)
│   ├── recorder.py      # mss + cv2 캡처/인코딩 루프 (별도 스레드)
│   ├── config.py        # config.json 로드/저장, 파일명 템플릿 처리
│   └── settings_dialog.py # 저장 경로/파일명 설정 UI
└── recordings/          # 기본 저장 폴더
```

## 5. 개발 단계
- [ ] **Step 1**: 프로젝트 스캐폴드 + `requirements.txt` + 가상환경 안내
- [ ] **Step 2**: `recorder.py` — 고정 좌표 영역을 받아 mp4로 저장하는 최소 기능 (CLI 테스트)
- [ ] **Step 3**: `overlay.py` — 드래그로 영역 선택하는 풀스크린 오버레이
- [ ] **Step 4**: `controller.py` — 녹화/중지 토글 버튼 + 경과 시간
- [ ] **Step 5**: `config.py` + `settings_dialog.py` — 저장 경로 & 파일명 템플릿
- [ ] **Step 6**: `main.py` 통합 + 단축키(선택)
- [ ] **Step 7**: 코드 리뷰 / 정리 / README 작성

## 6. 사용할 Claude Code 플러그인
개발 단계별로 다음 도구들을 활용:
- **security-guidance** — 파일 저장 경로 처리, 사용자 입력 검증 시
- **feature-dev** — 각 Step의 기능 구현 시
- **code-review** — Step 완료 후 변경 코드 리뷰
- **ralph-loop** — 반복 개선 루프가 필요한 경우
- **frontend-design** — 오버레이/컨트롤 바 UI 디자인 검토
- **codex-peer-review** (커뮤니티) — 주요 Step 마무리 시 2차 리뷰

## 7. 결정 사항
- [x] **프레임레이트**: **10 / 30 / 60 fps** 중 선택 (설정 UI 또는 컨트롤 바에 노출)
- [x] **커서 포함**: **NO** — 녹화 영상에 마우스 커서를 그리지 않음
- [x] **오디오**: **MVP에서 제외** (영상만). 추후 확장 시 `sounddevice` + ffmpeg muxing 검토
- [x] **실행 방식**: **시스템 트레이 대기**
  - 트레이 아이콘 클릭 → 영역 선택 모드 진입
  - 이미 영역이 지정된 상태에서 트레이 아이콘 다시 클릭 → 기존 영역 초기화 후 재지정
  - 트레이 메뉴: `영역 지정` / `설정` / `종료`
