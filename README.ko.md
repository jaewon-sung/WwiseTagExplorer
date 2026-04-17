# WwiseTagExplorer

태그 기반 Wwise 리소스 탐색기. WAAPI를 통해 활성화된 Wwise 프로젝트에 자동으로 연결하고, 오브젝트 이름에 포함된 네이밍 컨벤션 태그를 기반으로 오디오 에셋을 단계별로 탐색할 수 있습니다.

![screenshot placeholder](assets/screenshot.png)

---

## 요구사항

- [Audiokinetic Wwise](https://www.audiokinetic.com/products/wwise/) (WAAPI 활성화 필요)
- [sk-wwise-mcp](https://github.com/snapshotpl/sk-wwise-mcp) — `~/sk-wwise-mcp` 경로에 설치

### Wwise에서 WAAPI 활성화
**Wwise → Project Settings → User Settings → Enable Wwise Authoring API**

---

## 설치

[최신 릴리즈](https://github.com/jaewon-sung/WwiseTagExplorer/releases/latest)에서 `WwiseTagExplorer.exe`를 다운로드하여 원하는 위치에 놓으면 됩니다. Python 설치 불필요.

---

## 사용법

1. Wwise를 실행하고 프로젝트를 불러옵니다
2. `WwiseTagExplorer.exe` 실행
3. 앱이 자동으로 활성 프로젝트에 연결됩니다

---

## 기능

### Work Unit 필터링
- Work Unit을 선택해 범위를 좁히거나, **All**을 선택해 전체를 탐색
- ☆/★ 버튼으로 즐겨찾기 등록 — 다음 실행 시 자동으로 선택됨

### 태그 기반 필터링
오브젝트 이름을 `_` 기준으로 분리해 태그로 사용합니다.  
예: `pc_weapon_bow_shot_01` → `pc`, `weapon`, `bow`, `shot`

태그를 클릭할 때마다 결과가 한 단계씩 좁혀집니다. 다음 조건 중 하나에 해당하면 새 태그 레벨이 더 이상 추가되지 않습니다:
- 남은 결과가 모두 같은 상위 폴더에 있을 때
- 결과가 1개 이하로 줄었을 때
- 다음 레벨의 어떤 태그를 선택해도 결과가 변하지 않을 때

### Results 뷰
- 매칭된 오브젝트와 Wwise 경로를 표시
- 행 클릭 시 Wwise Project Explorer에서 해당 오브젝트를 포커스
- 컬럼 구분선을 드래그해 Name / Path 열 너비 조절 가능

### 태그 정렬
- **빈도순** — 태그 버튼을 빈도 높은 순으로 정렬 (기본값)
- **A-Z** — 태그 버튼을 알파벳 순으로 정렬
- **Clear** — 태그 선택 전체 초기화

---

## 소스에서 실행

```bash
pip install -r requirements.txt
python main.py
```

---

## 빌드

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name WwiseTagExplorer --add-data "assets/icons;assets/icons" main.py
```

결과물: `dist/WwiseTagExplorer.exe`
