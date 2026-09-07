"""매물 검증 데스크용 원격 키 서버 (Render 배포용) - 중개사별 토큰 버전.

이 파일은 launcher.py/main.py가 있는 프로젝트와는 완전히 별개의, 아주 작은
FastAPI 앱이다. 하는 일은 두 가지다:
  - GET /keys   : 올바른 "중개사 토큰"으로 요청하면 API 키 JSON을 돌려준다.
  - GET /agents : 관리자 토큰(ADMIN_TOKEN)으로만 등록된 중개사 이름 목록을 보여준다
                  (토큰 값 자체는 절대 보여주지 않는다 - 등록 여부 확인용).

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
import urllib.request
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="매물 검증 데스크 - 원격 키 서버")

# launcher.py의 SETTING_KEYS와 정확히 같은 이름을 써야 한다 - 이름이 다르면
# launcher.py가 응답을 받고도 값을 못 채워넣는다.
#
# ★ KAKAO_JS_KEY: 카카오맵 "지도 표시"(JavaScript SDK)용 키로, 주소→좌표 변환에
# 쓰는 REST API 키(KAKAO_KEY)와는 카카오 개발자센터에서 별도로 발급받는 다른
# 키다. 이 목록에 빠져 있으면 로컬에 배포된 main.py가 KAKAO_JS_KEY를 못 받아서
# KAKAO_KEY(REST 키)로 폴백하게 되고, 그 REST 키로 지도 SDK를 불러오면 카카오가
# "appKeyType is REST_API_KEY. but expected JAVASCRIPT_KEY" 401 에러로 거부한다
# (지도만 안 뜨고 건축물/토지 정보 같은 REST 기반 기능은 멀쩡한 이유가 이것).
KEY_NAMES = [
    "ANTHROPIC_API_KEY",
    "KAKAO_KEY",
    "KAKAO_JS_KEY",
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


def _authenticate(authorization: str) -> str:
    """Authorization 헤더를 검사해 통과하면 중개사 이름(식별자)을 반환하고,
    실패하면 401을 던진다. 어떤 중개사인지, 존재하는 이름인지 등은 에러
    메시지에 절대 노출하지 않는다(토큰 추측 공격에 힌트를 주지 않기 위함)."""
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
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
