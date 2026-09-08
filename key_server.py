"""매물 검증 데스크용 원격 키 서버 (Render 배포용) - 프록시 버전.

이 파일은 launcher.py/main.py가 있는 프로젝트와는 완전히 별개의, 아주 작은
FastAPI 앱이다. 하는 일은 네 가지다:
  - GET  /keys          : 올바른 "중개사 토큰"으로 요청하면 API 키 JSON을 돌려준다.
                           (v0.9부터 main.py는 여기서 실제 키를 받아 저장하지
                           않고, KAKAO_JS_KEY만 골라 쓴다 - 아래 설명 참고.)
  - POST /proxy          : 카카오/공공데이터/VWorld API 호출을 "대신" 해준다.
                           main.py(geocode.py/building_ledger.py/land_ledger.py/
                           molit.py)는 실제 키 없이 여기로 요청을 보내고, 이
                           서버가 진짜 키를 꽂아 넣어 실제 API를 호출한 뒤
                           응답을 그대로 돌려준다 - 그래서 중개사 PC는
                           KAKAO_KEY/DATA_SERVICE_KEY/VWORLD_KEY를 한 번도
                           안 보게 된다.
  - POST /v1/messages    : Claude(Anthropic) API 호출을 "대신" 해준다. main.py의
                           anthropic SDK가 base_url을 이 서버로 바꿔서 그대로
                           호출하면, 여기서 진짜 ANTHROPIC_API_KEY로 바꿔치기해
                           실제 Anthropic API에 넘긴다.
  - GET  /agents         : 관리자 토큰(ADMIN_TOKEN)으로만 등록된 중개사 이름
                           목록을 보여준다(토큰 값 자체는 절대 안 보여줌).

★ 왜 이렇게 바꿨는가: 처음 버전(v0.7 이하)은 /keys가 실제 키 값 자체를
중개사 PC에 내려줬다. launcher.py가 그 값을 오프라인 대비용으로 로컬
key.env/settings.json에 그대로 저장했는데, 그러면 "키 노출 없이 배포"라는
목적과 어긋나게 중개사 PC에 실제 키가 평문으로 남는다. 그래서 실제 키가
꼭 필요한 자리(HTTP 호출)를 이 서버가 대신 수행하는 구조로 바꿨다 - 이제
중개사 PC에는 실제 키가 "잠깐도" 존재하지 않는다.

단, KAKAO_JS_KEY(지도 표시용)는 예외다 - 브라우저가 카카오 서버에 직접
<script src="...sdk.js?appkey=...">로 요청해야 해서, 이 값은 어차피
브라우저 화면 소스에 그대로 노출된다(카카오도 이걸 알고 "도메인 등록
제한"으로 보호하지, 비밀로 취급하지 않는다). 그래서 이 값만은 지금처럼
/keys로 그대로 내려주고, launcher.py도 이 값만 로컬에 저장한다.

★ 중요: 이 파일 자체에는 실제 키 값도, 중개사 토큰도 절대 적지 않는다. 전부
Render 대시보드의 Environment 탭 또는 아래 설명할 GitHub 저장소에 등록해두고,
이 코드는 거기서 읽기만 한다 - 그래야 이 코드를 깃허브에 공개 저장소로
올려도 안전하다.

── 중개사별 토큰을 어디에 저장하는가 (두 곳을 합쳐서 인식한다) ─────────────────
1) AGENT_TOKENS (Render 환경변수) - 소수 인원일 때 간단하게 쓰는 방식.
   {"강남공인중개사": "9f3a1c2b...", "분당부동산": "77b2e4a1..."} 형태의 JSON.
   단점: Render 환경변수 입력칸이 한 줄짜리라 인원이 늘면 편집하다 실수하기
   쉽고(쉼표 하나만 빠져도 파싱 실패로 전원이 한꺼번에 막힘), 바꿀 때마다
   Render가 서비스를 재시작한다.

2) AGENTS_GITHUB_REPO 등 (GitHub 저장소의 agents.json) - 인원이 많아지면 권장.
   중개사 목록을 별도의 비공개 GitHub 저장소(예: listing-verify-agents)에
   agents.json 파일 하나로 관리한다. GitHub 웹 화면에서 파일을 열어 편집하면
   되고(히스토리/되돌리기까지 공짜로 딸려온다), 서버는 이 파일을 30초 캐시를
   두고 계속 다시 읽어오므로 Render 재배포 없이 최대 30초 안에 반영된다.
   필요한 환경변수:
     AGENTS_GITHUB_REPO   = "깃허브계정/listing-verify-agents" (owner/repo)
     AGENTS_GITHUB_PATH   = "agents.json" (기본값, 생략 가능)
     AGENTS_GITHUB_BRANCH = "main" (기본값, 생략 가능)
     AGENTS_GITHUB_TOKEN  = 그 저장소만 읽을 수 있는 Fine-grained PAT
                             (Contents: Read-only 권한만 주면 된다)

두 방식 다 안 쓰거나 설정을 안 했으면 그냥 빈 목록으로 처리되고 서버는
정상적으로 계속 뜬다(레거시 ACCESS_TOKEN만 있어도 그걸로는 동작).

배포 방법은 README.md 참고.

로컬에서 미리 테스트해보려면:
    AGENT_TOKENS='{"테스트중개사":"test123"}' ANTHROPIC_API_KEY=sk-xxx \
        uvicorn key_server:app --reload
    curl -H "Authorization: Bearer test123" http://127.0.0.1:8000/keys
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

app = FastAPI(title="매물 검증 데스크 - 원격 키 서버")

# launcher.py의 SETTING_KEYS와 정확히 같은 이름을 써야 한다 - 이름이 다르면
# launcher.py가 응답을 받고도 값을 못 채워넣는다.
KEY_NAMES = [
    "ANTHROPIC_API_KEY",
    "KAKAO_KEY",
    "KAKAO_JS_KEY",   # 지도 "표시"용 - KAKAO_KEY(REST, 주소변환용)와는 다른 별도 키
    "DATA_SERVICE_KEY",
    "VWORLD_KEY",
    "VWORLD_DOMAIN",
]

# GitHub에서 읽어온 agents.json을 잠깐 기억해두는 캐시. 요청마다 매번 GitHub API를
# 두드리면 (1) 느려지고 (2) GitHub API 호출 한도에 걸릴 수 있어서, 이 시간(초) 동안은
# 새로 읽지 않고 캐시를 그대로 쓴다. 그만큼 GitHub에서 파일을 고친 게 반영되는 데
# 최대 이 시간만큼 지연될 수 있다는 뜻이기도 하다.
_GH_CACHE_TTL_SEC = 30
_gh_cache = {"data": {}, "fetched_at": 0.0}


def _fetch_agent_tokens_from_github() -> dict:
    """AGENTS_GITHUB_REPO 등이 설정돼 있으면 그 저장소의 agents.json을 읽어온다.
    설정이 없으면(아직 GitHub 방식을 안 쓰는 경우) 조용히 빈 dict를 반환한다 -
    이 함수가 실패한다고 서버 전체나 AGENT_TOKENS 쪽 인증까지 막혀서는 안 된다."""
    repo = os.environ.get("AGENTS_GITHUB_REPO", "").strip()          # 예: "myuser/listing-verify-agents"
    token = os.environ.get("AGENTS_GITHUB_TOKEN", "").strip()
    if not repo or not token:
        return {}
    path = os.environ.get("AGENTS_GITHUB_PATH", "agents.json").strip() or "agents.json"
    branch = os.environ.get("AGENTS_GITHUB_BRANCH", "main").strip() or "main"

    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        # 이 Accept 헤더를 쓰면 GitHub이 base64로 감싸지 않고 파일 내용 그대로
        # (raw)를 돌려준다 - 우리가 직접 디코딩할 필요가 없다.
        "Accept": "application/vnd.github.raw+json",
        "User-Agent": "listing-verify-key-server",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return {str(name): str(token) for name, token in data.items() if token}


def _load_agent_tokens() -> dict:
    """AGENT_TOKENS(Render 환경변수, 소규모용)와 GitHub의 agents.json(대규모용)을
    합쳐서 반환한다. 두 곳에 같은 이름이 있으면 GitHub 쪽 값이 우선한다(나중에
    update한 dict가 이긴다). 매 요청마다 새로 읽되, GitHub 쪽만 캐시를 둔다
    (환경변수 읽기는 원래도 즉시 반영되고 비용이 없으므로 캐시가 필요 없다)."""
    tokens: dict = {}

    raw = os.environ.get("AGENT_TOKENS", "")
    if raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                tokens.update({str(name): str(token) for name, token in data.items() if token})
        except Exception:
            pass  # AGENT_TOKENS가 깨져 있어도 GitHub 쪽은 정상 동작하게 넘어간다

    now = time.time()
    if now - _gh_cache["fetched_at"] > _GH_CACHE_TTL_SEC:
        try:
            _gh_cache["data"] = _fetch_agent_tokens_from_github()
            _gh_cache["fetched_at"] = now
        except Exception:
            pass  # 조회 실패(네트워크/권한 등) 시 마지막으로 성공했던 캐시를 그대로 쓴다
    tokens.update(_gh_cache["data"])

    return tokens


def _authenticate(token_or_header: str) -> str:
    """토큰 문자열을 검사해 통과하면 중개사 이름(식별자)을 반환하고, 실패하면
    401을 던진다. "Bearer xxx"(Authorization 헤더) 형태와 값 자체("xxx",
    anthropic SDK가 보내는 x-api-key 헤더처럼 접두어가 없는 형태) 둘 다
    받아들인다. 어떤 중개사인지, 존재하는 이름인지 등은 에러 메시지에 절대
    노출하지 않는다(토큰 추측 공격에 힌트를 주지 않기 위함)."""
    provided = token_or_header[7:] if token_or_header.startswith("Bearer ") else token_or_header
    if not provided:
        raise HTTPException(status_code=401, detail="Unauthorized")

    for name, token in _load_agent_tokens().items():
        if provided == token:
            return name

    # 레거시 폴백: 예전 방식(중개사 구분 없는 단일 토큰)으로 이미 배포된 exe가
    # 있다면 ACCESS_TOKEN 환경변수를 지우기 전까지는 계속 동작한다.
    legacy_token = os.environ.get("ACCESS_TOKEN", "")
    if legacy_token and provided == legacy_token:
        return "(레거시 공용 토큰)"

    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
async def health():
    """Render 헬스체크 및 수동 확인용. 키/토큰은 절대 반환하지 않는다."""
    return {"ok": True, "service": "매물 검증 데스크 키 서버"}


@app.get("/keys")
async def get_keys(authorization: str = Header(default="")):
    agent_name = _authenticate(authorization)
    # Render 로그(대시보드 Logs 탭)에서 "누가 언제 키를 받아갔는지" 확인할 수
    # 있게 남겨둔다 - 이상 사용 감지(예: 새벽에 몰아서 대량 조회 등)에 도움된다.
    print(f"[keys] {datetime.now(timezone.utc).isoformat()} agent={agent_name}", flush=True)
    return {name: os.environ.get(name, "") for name in KEY_NAMES}


@app.get("/agents")
async def list_agents(authorization: str = Header(default=""), refresh: bool = False):
    """등록된 중개사 이름 목록만 보여준다(토큰 값은 절대 포함하지 않음).
    AGENT_TOKENS나 GitHub의 agents.json을 방금 수정한 뒤 제대로 반영됐는지
    확인하는 용도. ADMIN_TOKEN 환경변수를 별도로 등록해야 쓸 수 있다
    (설정 안 했으면 항상 401).

    ?refresh=1을 붙이면 GitHub 캐시(30초)를 기다리지 않고 즉시 다시 읽어온다 -
    방금 agents.json을 고치고 바로 반영됐는지 확인하고 싶을 때 쓴다."""
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not admin_token or provided != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if refresh:
        _gh_cache["fetched_at"] = 0.0
    return {"agents": sorted(_load_agent_tokens().keys())}


# ---------------------------------------------------------------------------
# 일반 REST 프록시 - geocode.py/building_ledger.py/land_ledger.py/molit.py가
# 이 엔드포인트를 통해 카카오/공공데이터/VWorld를 "대신" 호출하게 한다.
# ---------------------------------------------------------------------------

_PROXY_TIMEOUT_SEC = 20.0

# 호스트별로 "실제 키를 요청의 어디에 꽂아 넣을지"를 정의한다. 호출부는 이 값
# 없이(또는 빈 값으로) 요청을 만들어 보내고, 여기서 실제 값으로 덮어쓴다 -
# 그래서 호출부가 보낸 값은 어차피 무시되므로 아무 문자열이나 넣어 보내도 된다.
# 새 외부 API를 추가하려면 이 dict에 호스트 하나만 추가하면 된다(그 외 코드는
# 건드릴 필요 없음).
_PROXY_HOST_RULES = {
    "dapi.kakao.com": {
        "type": "header", "name": "Authorization",
        "env": "KAKAO_KEY", "format": "KakaoAK {value}",
    },
    "apis.data.go.kr": {
        # 건축HUB(건축물대장)와 국토부 실거래가 둘 다 이 호스트를 쓰고, main.py는
        # 둘 다 DATA_SERVICE_KEY 하나로 통일해서 관리한다(main.py가
        # BUILDING_HUB_SERVICE_KEY/MOLIT_SERVICE_KEY로 매핑) - 여기서도 같은
        # 값 하나만 있으면 된다.
        "type": "query", "name": "serviceKey", "env": "DATA_SERVICE_KEY",
    },
    "api.vworld.kr": {
        # VWorld는 key와 domain 둘 다 필요하다 - domain은 VWorld 콘솔에 등록해둔
        # 실제 서비스 도메인(또는 로컬 테스트용 localhost)이어야 한다.
        "type": "query_multi", "fields": [
            ("key", "VWORLD_KEY"), ("domain", "VWORLD_DOMAIN"),
        ],
    },
}


@app.post("/proxy")
async def proxy(request: Request, authorization: str = Header(default="")):
    """geocode.py 등이 "이 URL로, 이 파라미터로 대신 호출해줘"라고 보내는
    요청을 실제 API로 중계한다.

    요청 본문(JSON): {"url": "...", "method": "GET", "params": {...}, "headers": {...}}
    url의 호스트가 _PROXY_HOST_RULES에 없으면 403으로 거부한다(이 서버가
    아무 주소나 대신 호출해주는 열린 중계기가 되는 것을 막기 위함)."""
    agent_name = _authenticate(authorization)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="요청 본문이 올바른 JSON이 아닙니다.")

    url = body.get("url", "")
    method = (body.get("method") or "GET").upper()
    params = dict(body.get("params") or {})
    headers = dict(body.get("headers") or {})
    json_body = body.get("json")

    host = urllib.parse.urlparse(url).hostname or ""
    rule = _PROXY_HOST_RULES.get(host)
    if not rule:
        raise HTTPException(status_code=403, detail=f"허용되지 않은 대상 호스트입니다: {host}")

    if rule["type"] == "header":
        real_value = os.environ.get(rule["env"], "")
        if not real_value:
            raise HTTPException(status_code=502, detail=f"서버에 {rule['env']}가 설정되어 있지 않습니다.")
        headers[rule["name"]] = rule["format"].format(value=real_value)
    elif rule["type"] == "query":
        real_value = os.environ.get(rule["env"], "")
        if not real_value:
            raise HTTPException(status_code=502, detail=f"서버에 {rule['env']}가 설정되어 있지 않습니다.")
        params[rule["name"]] = real_value
    elif rule["type"] == "query_multi":
        for field_name, env_name in rule["fields"]:
            real_value = os.environ.get(env_name, "")
            if real_value:
                params[field_name] = real_value

    try:
        async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT_SEC) as client:
            resp = await client.request(method, url, params=params, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"대상 API 호출 실패: {e}")

    print(f"[proxy] {datetime.now(timezone.utc).isoformat()} agent={agent_name} "
          f"host={host} status={resp.status_code}", flush=True)
    # 대상 API가 응답한 상태코드/본문을 그대로 돌려준다 - 그래야 호출부
    # (geocode.py 등)의 resp.raise_for_status()/resp.json() 파싱 로직을 하나도
    # 안 바꾸고 그대로 쓸 수 있다.
    return Response(content=resp.content, status_code=resp.status_code,
                     media_type=resp.headers.get("content-type"))


# ---------------------------------------------------------------------------
# Claude(Anthropic) API passthrough - main.py의 anthropic SDK가 base_url만
# 이 서버로 바꾸면 코드 변경 없이 그대로 동작하도록, 실제 Anthropic API와
# 똑같은 경로(/v1/messages)를 흉내낸다.
# ---------------------------------------------------------------------------

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@app.post("/v1/messages")
async def anthropic_messages(request: Request, x_api_key: str = Header(default="", alias="x-api-key")):
    """anthropic 파이썬 SDK는 인증을 Authorization이 아니라 x-api-key 헤더로
    보낸다. 그 자리에 "중개사 토큰"을 대신 넣어서 여기서 인증하고, 진짜
    ANTHROPIC_API_KEY로 바꿔서 실제 Anthropic API에 그대로 넘겨준다.

    main.py가 스트리밍(stream=True)을 쓰지 않는다는 전제로 만들었다 - 나중에
    스트리밍을 쓰게 되면 이 함수도 응답을 스트리밍으로 그대로 중계하도록
    다시 손봐야 한다(지금은 응답을 한 번에 다 받은 뒤 통째로 돌려준다)."""
    agent_name = _authenticate(x_api_key)

    body = await request.body()
    real_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not real_key:
        raise HTTPException(status_code=502, detail="서버에 ANTHROPIC_API_KEY가 설정되어 있지 않습니다.")

    forward_headers = {
        "x-api-key": real_key,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(_ANTHROPIC_URL, content=body, headers=forward_headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Anthropic API 호출 실패: {e}")

    print(f"[anthropic-proxy] {datetime.now(timezone.utc).isoformat()} agent={agent_name} "
          f"status={resp.status_code}", flush=True)
    return Response(content=resp.content, status_code=resp.status_code,
                     media_type=resp.headers.get("content-type"))
