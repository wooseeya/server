# 매물 검증 데스크 — 원격 키 서버

`launcher.py`(고급 설정 탭)가 실행할 때마다 API 키를 받아오는 아주 작은 서버입니다.
이 서버 자체에는 키 값이 들어있지 않고, Render의 환경변수에만 저장됩니다.

## 배포 방법 (Render, 무료 플랜 기준)

### 1. 이 폴더를 GitHub 저장소로 올리기
`key_server.py`, `requirements.txt`, `render.yaml`(선택) 세 파일만 있는
새 저장소를 만들어 올립니다. **키 값은 어디에도 적지 마세요.**

### 2. Render에 배포
**방법 A — Blueprint로 한 번에 (render.yaml 사용)**
1. https://dashboard.render.com → New + → **Blueprint**
2. 방금 올린 저장소 선택 → Render가 `render.yaml`을 읽어 서비스를 자동 구성합니다.
3. 배포 화면에서 환경변수 값을 채워 넣으라고 안내가 뜹니다 (아래 3번 표 참고).

**방법 B — 수동으로**
1. New + → **Web Service** → 저장소 연결
2. Runtime: `Python 3`
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn key_server:app --host 0.0.0.0 --port $PORT`
5. Create Web Service

### 3. 환경변수 등록 (Environment 탭)

| 변수명 | 값 |
|---|---|
| `ACCESS_TOKEN` | 아무 툴로나 생성한 긴 랜덤 문자열 (예: `openssl rand -hex 32`) |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `KAKAO_KEY` | 카카오 REST API 키 |
| `DATA_SERVICE_KEY` | 공공데이터포털 서비스키 |
| `VWORLD_KEY` | VWorld API 키 |
| `VWORLD_DOMAIN` | VWorld 등록 도메인 (없으면 `localhost`) |

저장하면 자동으로 재배포됩니다.

### 4. 확인
배포가 끝나면 `https://<서비스이름>.onrender.com` 형태의 주소가 생깁니다.

```bash
curl -H "Authorization: Bearer <ACCESS_TOKEN>" https://<서비스이름>.onrender.com/keys
```

키 JSON이 그대로 돌아오면 정상입니다. 토큰이 틀리면 `401 Unauthorized`가 됩니다.

### 5. launcher.py에 연결
`launcher.py` 실행 → **고급 설정** 탭 → "원격 키 서버 URL"에
`https://<서비스이름>.onrender.com/keys`, "액세스 토큰"에 `ACCESS_TOKEN` 값을
입력하고 "지금 원격에서 가져오기"로 한 번 테스트해본 뒤 "저장 후 실행"을
누르면 됩니다. 이후로는 실행할 때마다 자동으로 최신 키를 받아옵니다.

## 참고 — 무료 플랜의 슬립(sleep)

Render 무료 플랜은 15분간 요청이 없으면 서버가 잠들고, 다음 요청이 서버를
깨우는 데 최대 수십 초가 걸립니다. `launcher.py`의 `fetch_remote_settings()`는
이를 감안해 타임아웃을 60초로 넉넉히 잡아뒀습니다. 항상 즉시 응답해야 한다면
Render 유료 플랜(월 $7~)으로 올리면 슬립 없이 항상 켜져 있습니다.

## 키가 새어나간 것 같다면

Render 대시보드에서 `ACCESS_TOKEN` 값을 새로 바꾸기만 하면, 옛 토큰이 박혀
있는 모든 배포본(exe)은 다음 실행부터 즉시 `401`로 막힙니다. 실제 API
키(`ANTHROPIC_API_KEY` 등) 자체가 새어나간 것 같다면 각 서비스(Anthropic
콘솔, 카카오 개발자센터 등)에서 그 키를 즉시 재발급/폐기하는 것도 함께
해주세요 — 이 원격 키 서버 구조는 "배포된 exe의 접근"을 끊어줄 뿐, 이미
유출된 키 값 자체를 무효화해주지는 않습니다.
