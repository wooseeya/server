"""매물 검증 데스크용 원격 키 서버 (Render 배포용) - 프록시 버전.

이 파일은 launcher.py/main.py가 있는 프로젝트와는 완전히 별개의, 아주 작은
FastAPI 앱이다. 하는 일은 다섯 가지다:
  - GET  /keys          : 올바른 "중개사 토큰"으로 요청하면 KAKAO_JS_KEY(지도 표시용,
                           어차피 브라우저에 노출되는 공개 키) "하나만" 돌려준다.
                           ★ v1.1부터: 예전에는 ANTHROPIC_API_KEY 등 실제 키까지 전부
                           내려줘서, 토큰만 있으면 curl로 직접 호출해 모든 키를 꺼낼 수
                           있었다 - 이제는 공개해도 되는 값만 돌려준다.
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
  - GET  /token-info     : 지금 쓰는 토큰의 만료일/남은 일수를 알려준다. 이미
                           만료된 토큰이어도(그 토큰 자체가 한 번이라도 등록된
                           적 있다면) 조회는 허용한다 - 그래야 만료 후에도
                           launcher.py가 "언제까지였는지"를 사용자에게 보여줄
                           수 있다. /proxy, /v1/messages, /keys는 만료된 토큰을
                           그대로 거부한다(v0.11부터).
  - GET  /agents         : 관리자 토큰(ADMIN_TOKEN)으로만 등록된 중개사 이름/
                           만료일 목록을 보여준다(토큰 값 자체는 절대 안 보여줌).

★ v0.11부터: 중개사별 토큰에 만료일(expires)을 선택적으로 붙일 수 있다.
AGENT_TOKENS/agents.json의 값은 지금까지처럼 토큰 문자열 하나만 써도 되고
(그 경우 무기한), 아래처럼 객체로 써서 만료일을 지정할 수도 있다:
    {
      "강남공인중개사": {"token": "9f3a1c2b...", "expires": "2026-12-31"},
      "분당부동산": "77b2e4a1..."   // 문자열 그대로 쓰면 무기한
    }
expires는 "YYYY-MM-DD" 형식이며, 그날 자정(UTC)이 지나면 만료로 처리한다.
형식이 잘못됐으면(오타 등) 안전하게 "무기한"으로 취급한다 - 관리자 실수로
전체 중개사가 갑자기 차단되는 사고를 막기 위함이다.

★ v1.1 보안 보강 - 새로 쓸 수 있는 환경변수 (전부 선택, 안 쓰면 기본값):
    ANTHROPIC_ALLOWED_MODELS  허용할 모델 이름 목록(쉼표 구분). 비우면 모델 제한 없음.
                              예: "claude-sonnet-4-5,claude-haiku-4-5"
                              (처음엔 비워두고 Logs의 [anthropic-proxy] model= 값을
                              확인한 뒤, 실제 쓰는 모델만 적어 넣는 것을 권장)
    ANTHROPIC_MAX_TOKENS_CAP  요청 하나당 max_tokens 상한. 기본 8192, 0이면 제한 없음.
                              넘는 요청은 거부하지 않고 이 값으로 낮춰서 보낸다.
    ANTHROPIC_DAILY_LIMIT     중개사 1명당 하루(KST) Claude 호출 횟수. 기본 500, 0=무제한.
    PROXY_DAILY_LIMIT         중개사 1명당 하루(KST) /proxy 호출 횟수. 기본 5000, 0=무제한.
  ※ 횟수 제한은 서버 메모리에만 저장된다 - Render가 재시작/슬립되면 0으로 초기화된다.
    "절대 한도"가 필요하면 Anthropic 콘솔의 월 사용 한도를 반드시 함께 걸어둘 것.

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

import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))  # 만료일(expires) 판정은 한국 시간 기준으로 한다 -
# UTC 기준으로 하면 한국 날짜로는 이미 만료일 다음날이 됐어도 UTC로는 아직 자정
# 전이라(최대 9시간) 만료 처리가 늦게 걸리는 문제가 있었다(실제 문의로 확인됨).

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

app = FastAPI(title="매물 검증 데스크 - 원격 키 서버")

# /keys로 내려줘도 되는 값의 목록. launcher.py의 SETTING_KEYS와 같은 이름을 써야 한다.
# ★ 여기에는 "브라우저 화면에 어차피 노출되는 값"만 넣는다. 실제 서비스 키
#   (ANTHROPIC_API_KEY/KAKAO_KEY/DATA_SERVICE_KEY/VWORLD_KEY)를 여기에 다시 넣으면
#   토큰을 가진 누구나 curl로 그 키를 꺼내 갈 수 있으므로 절대 추가하지 말 것.
PUBLIC_KEY_NAMES = [
    "KAKAO_JS_KEY",   # 지도 "표시"용 - KAKAO_KEY(REST, 주소변환용)와는 다른 별도 키
]

# GitHub에서 읽어온 agents.json을 잠깐 기억해두는 캐시. 요청마다 매번 GitHub API를
# 두드리면 (1) 느려지고 (2) GitHub API 호출 한도에 걸릴 수 있어서, 이 시간(초) 동안은
# 새로 읽지 않고 캐시를 그대로 쓴다. 그만큼 GitHub에서 파일을 고친 게 반영되는 데
# 최대 이 시간만큼 지연될 수 있다는 뜻이기도 하다.
_GH_CACHE_TTL_SEC = 30
_gh_cache = {"data": {}, "fetched_at": 0.0, "last_error": None, "last_success_at": None}


def _fetch_agent_tokens_from_github() -> dict:
    """AGENTS_GITHUB_REPO 등이 설정돼 있으면 그 저장소의 agents.json을 읽어온다.
    설정이 없으면(아직 GitHub 방식을 안 쓰는 경우) 조용히 빈 dict를 반환한다 -
    이 함수가 실패한다고 서버 전체나 AGENT_TOKENS 쪽 인증까지 막혀서는 안 된다."""
    repo = os.environ.get("AGENTS_GITHUB_REPO", "").strip()          # 예: "myuser/listing-verify-agents"
    token = os.environ.get("AGENTS_GITHUB_TOKEN", "").strip()
    if not repo or not token:
        missing = []
        if not repo:
            missing.append("AGENTS_GITHUB_REPO")
        if not token:
            missing.append("AGENTS_GITHUB_TOKEN")
        print(f"[AGENT_TOKENS/GitHub] 아직 설정 안 됨 - 다음 환경변수가 비어 있어 GitHub 조회를 "
              f"건너뜁니다: {', '.join(missing)}", flush=True)
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
    return {str(name): entry for name, entry in data.items() if entry}


def _normalize_entries(raw: dict) -> dict:
    """AGENT_TOKENS/agents.json 원본(값이 토큰 문자열이거나 {"token","expires"}
    객체일 수 있음)을 공통 스키마 {"token": str, "expires": str|None}로 정리한다.
    문자열 그대로 쓴 기존 항목은 expires=None(무기한)으로 취급해 하위호환된다."""
    out: dict = {}
    for name, entry in raw.items():
        if isinstance(entry, str):
            if entry:
                out[str(name)] = {"token": entry, "expires": None}
        elif isinstance(entry, dict):
            token = str(entry.get("token") or "")
            if token:
                out[str(name)] = {"token": token, "expires": entry.get("expires") or None}
    return out


def _is_expired(expires: str | None) -> bool:
    """expires("YYYY-MM-DD")가 오늘(한국시간 KST) 이전이면 True. expires가 없거나
    형식이 잘못됐으면(관리자 오타 등) 안전하게 False(무기한 취급) - 형식 오류
    하나로 전체 인증이 막히는 사고를 막기 위함이다.

    ⚠ 판정 기준은 KST(UTC+9)다 - UTC로 판정하면 한국 날짜로는 이미 만료일
    다음날이 됐어도 UTC 자정 전(한국시간 오전 9시 전)까지는 만료 처리가 안
    되는 최대 9시간의 지연이 생겨서, 실제로 "만료일을 지났는데 왜 아직 되냐"는
    문의가 있었다."""
    if not expires:
        return False
    try:
        exp_date = datetime.strptime(expires, "%Y-%m-%d").date()
    except ValueError:
        print(f"[AGENT_TOKENS] 경고: expires 형식이 잘못됨({expires!r}) - 무기한으로 취급합니다.", flush=True)
        return False
    return datetime.now(KST).date() > exp_date


def _load_agent_tokens() -> dict:
    """AGENT_TOKENS(Render 환경변수, 소규모용)와 GitHub의 agents.json(대규모용)을
    합쳐서 반환한다. 두 곳에 같은 이름이 있으면 GitHub 쪽 값이 우선한다(나중에
    update한 dict가 이긴다). 매 요청마다 새로 읽되, GitHub 쪽만 캐시를 둔다
    (환경변수 읽기는 원래도 즉시 반영되고 비용이 없으므로 캐시가 필요 없다).
    반환값은 {"중개사이름": {"token": str, "expires": str|None}} 형태로 정규화돼
    있다 - 호출부(_authenticate, /agents, /token-info)는 값이 문자열이던 시절과
    객체인 지금을 구분할 필요가 없다."""
    raw: dict = {}

    env_raw = os.environ.get("AGENT_TOKENS", "")
    if env_raw.strip():
        try:
            data = json.loads(env_raw)
            if isinstance(data, dict):
                raw.update({str(name): entry for name, entry in data.items() if entry})
            else:
                print(f"[AGENT_TOKENS] 경고: JSON은 파싱됐지만 객체({{...}}) 형태가 아닙니다 "
                      f"(실제 타입: {type(data).__name__}) - 이 값은 무시됩니다.", flush=True)
        except Exception as e:
            # AGENT_TOKENS가 깨져 있어도 GitHub 쪽은 정상 동작하게 넘어가되, Render
            # 대시보드 Logs 탭에서 바로 원인을 볼 수 있게 남긴다. 흔한 원인: 작은따옴표
            # 사용(JSON은 큰따옴표만 허용), 쉼표 누락/중복, 앞뒤에 잘못 붙은 따옴표.
            print(f"[AGENT_TOKENS] 파싱 실패 - 이 환경변수의 모든 토큰이 무시됩니다: {e}", flush=True)

    now = time.time()
    if now - _gh_cache["fetched_at"] > _GH_CACHE_TTL_SEC:
        try:
            _gh_cache["data"] = _fetch_agent_tokens_from_github()
            _gh_cache["fetched_at"] = now
            _gh_cache["last_error"] = None
            _gh_cache["last_success_at"] = now
        except Exception as e:
            # 조회 실패(네트워크/권한/경로·브랜치 오타 등) 시 마지막으로 성공했던
            # 캐시를 그대로 쓰되, Render 대시보드 Logs 탭에서 원인을 바로 볼 수
            # 있게 남긴다. 흔한 원인: PAT 권한 부족/만료, repo·path·branch 오타.
            # ⚠ fetched_at을 갱신 안 해서(실패했으니) 다음 요청에서도 바로 다시
            # 시도하게 되는데, 이러면 실패가 계속될 때 "언제 마지막으로 성공했는지"
            # 를 로그만 보고는 알기 어렵다 - last_error/last_success_at을 따로
            # 남겨서 /agents(관리자 전용)로 바로 확인할 수 있게 한다. 실제로
            # "만료일을 설정했는데도 계속 통과된다"는 문의가 있었는데, 원인이
            # 바로 이 조회가 계속 조용히 실패해서 만료일 추가 전의 옛날 캐시를
            # 계속 쓰고 있었던 경우였다.
            _gh_cache["last_error"] = str(e)
            print(f"[AGENT_TOKENS/GitHub] agents.json 조회 실패: {e}", flush=True)
    raw.update(_gh_cache["data"])

    return _normalize_entries(raw)


def _tokens_equal(a: str, b: str) -> bool:
    """토큰 비교를 "일치하는 순간 바로 끝나는" == 대신 일정한 시간이 걸리는
    hmac.compare_digest로 한다(응답 시간 차이로 토큰을 한 글자씩 추측하는 공격 방지).
    str을 그대로 넣으면 한글 등 비ASCII 문자에서 TypeError가 나므로 bytes로 바꿔 비교한다."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _env_int(name: str, default: int) -> int:
    """정수 환경변수 읽기. 비었거나 숫자가 아니면(오타 등) 기본값을 쓰고 로그를 남긴다."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[설정] 경고: {name}={raw!r}는 정수가 아니어서 기본값 {default}을 씁니다.", flush=True)
        return default


def _client_ip(request: Request | None) -> str:
    """로그용 접속 IP. Render 같은 프록시 뒤에서는 X-Forwarded-For에 값이 여러 개일 수
    있고 그 앞쪽은 클라이언트가 위조할 수 있으므로, 어느 항목을 믿을지 단정하지 않고
    헤더 전체를 (잘라서) 그대로 남긴다 - 로그를 볼 때 참고용으로만 쓴다."""
    if request is None:
        return "-"
    xff = request.headers.get("x-forwarded-for", "").strip()
    if xff:
        return xff[:200]
    return request.client.host if request.client else "-"


# 중개사별 일일 호출 횟수 {(중개사이름, 구분): (날짜KST, 횟수)}. 서버 메모리에만 있어서
# 재시작/슬립 시 초기화된다(위 docstring 참고). await 없이 동작하므로 동시 요청에도 안전하다.
_usage: dict = {}


def _check_quota(agent_name: str, bucket: str, limit: int) -> None:
    """limit이 0 이하면 무제한. 오늘(KST) 이미 limit회 불렀으면 429를 던진다."""
    if limit <= 0:
        return
    today = datetime.now(KST).strftime("%Y-%m-%d")
    day, count = _usage.get((agent_name, bucket), (today, 0))
    if day != today:
        day, count = today, 0
    if count >= limit:
        print(f"[quota] agent={agent_name} bucket={bucket} 일일 한도({limit}) 초과", flush=True)
        raise HTTPException(status_code=429, detail="오늘 사용 한도를 초과했습니다. 내일 다시 시도하거나 담당자에게 문의하세요.")
    _usage[(agent_name, bucket)] = (day, count + 1)


def _find_entry_by_token(provided: str):
    """제공된 토큰 문자열과 일치하는 항목을 찾는다. (이름, {"token","expires"}) |
    None(등록된 적 없는 토큰). 일치 여부와 상관없이 전체를 끝까지 비교한다."""
    found = None
    for name, entry in _load_agent_tokens().items():
        if _tokens_equal(provided, entry["token"]) and found is None:
            found = (name, entry)
    return found


def _authenticate(token_or_header: str, request: Request | None = None) -> str:
    """토큰 문자열을 검사해 통과하면 중개사 이름(식별자)을 반환하고, 실패하면
    401을 던진다. "Bearer xxx"(Authorization 헤더) 형태와 값 자체("xxx",
    anthropic SDK가 보내는 x-api-key 헤더처럼 접두어가 없는 형태) 둘 다
    받아들인다. 어떤 중개사인지, 존재하는 이름인지 등은 에러 메시지에 절대
    노출하지 않는다(토큰 추측 공격에 힌트를 주지 않기 위함) - 단, 만료 여부는
    본인이 이미 알고 있는 자기 토큰에 대한 정보이므로 예외적으로 안내한다."""
    provided = token_or_header[7:] if token_or_header.startswith("Bearer ") else token_or_header
    if not provided:
        raise HTTPException(status_code=401, detail="Unauthorized")

    found = _find_entry_by_token(provided)
    if found:
        name, entry = found
        if _is_expired(entry["expires"]):
            print(f"[auth-fail] {datetime.now(timezone.utc).isoformat()} reason=expired "
                  f"agent={name} ip={_client_ip(request)}", flush=True)
            raise HTTPException(status_code=401, detail="토큰이 만료되었습니다. 담당자에게 갱신을 요청하세요.")
        return name

    # 레거시 폴백: 예전 방식(중개사 구분 없는 단일 토큰)으로 이미 배포된 exe가
    # 있다면 ACCESS_TOKEN 환경변수를 지우기 전까지는 계속 동작한다. (만료 개념 없음)
    # ⚠ 이 토큰은 만료도, 중개사별 폐기도 안 된다 - 더 이상 쓰는 exe가 없으면 Render에서
    #   ACCESS_TOKEN 환경변수를 삭제할 것. 쓰이는 동안은 로그에 경고를 남긴다.
    legacy_token = os.environ.get("ACCESS_TOKEN", "")
    if legacy_token and _tokens_equal(provided, legacy_token):
        print(f"[auth] 경고: 레거시 공용 토큰으로 접근함 (만료/개별 폐기 불가) "
              f"ip={_client_ip(request)}", flush=True)
        return "(레거시 공용 토큰)"

    # 토큰 값 자체는 절대 로그에 남기지 않는다. 실패 기록은 무차별 대입 시도를 눈으로
    # 확인하는 용도이며, 자동 차단은 하지 않는다(프록시 뒤에서는 IP를 정확히 특정할 수
    # 없어서, 공격자가 일부러 실패를 쌓아 정상 중개사까지 막는 사고가 날 수 있다).
    print(f"[auth-fail] {datetime.now(timezone.utc).isoformat()} reason=invalid "
          f"ip={_client_ip(request)}", flush=True)
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
async def health():
    """Render 헬스체크 및 수동 확인용. 키/토큰은 절대 반환하지 않는다."""
    return {"ok": True, "service": "매물 검증 데스크 키 서버"}


@app.get("/keys")
async def get_keys(request: Request, authorization: str = Header(default="")):
    agent_name = _authenticate(authorization, request)
    # Render 로그(대시보드 Logs 탭)에서 "누가 언제 키를 받아갔는지" 확인할 수
    # 있게 남겨둔다 - 이상 사용 감지(예: 새벽에 몰아서 대량 조회 등)에 도움된다.
    print(f"[keys] {datetime.now(timezone.utc).isoformat()} agent={agent_name}", flush=True)
    # ★ 공개해도 되는 값(PUBLIC_KEY_NAMES)만 돌려준다. 실제 서비스 키는 절대 내려주지 않는다.
    return {name: os.environ.get(name, "") for name in PUBLIC_KEY_NAMES}


@app.get("/token-info")
async def token_info(authorization: str = Header(default="")):
    """지금 쓰고 있는 토큰의 만료일/남은 일수를 알려준다. launcher.py가 실행할
    때마다 조용히 호출해서, 만료가 임박했거나 이미 지났으면 중개사 화면에 안내를
    띄우는 데 쓴다. /proxy, /v1/messages, /keys와 달리 이미 만료된 토큰이어도
    (그 토큰 자체가 한 번이라도 등록된 적 있다면) 조회는 허용한다 - 그래야 만료된
    뒤에도 중개사가 "언제까지였는지"를 스스로 확인하고 담당자에게 갱신을 요청할
    수 있다. 등록된 적 자체가 없는 토큰(오타 등)은 다른 엔드포인트와 동일하게
    401로 거부한다.

    응답: {"agent": str, "expires": "YYYY-MM-DD"|None, "days_left": int|None,
           "expired": bool}
    expires가 None이면 무기한 토큰이라는 뜻이고, 이때 days_left도 None이다."""
    provided = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if not provided:
        raise HTTPException(status_code=401, detail="Unauthorized")

    found = _find_entry_by_token(provided)
    if found:
        name, entry = found
        expires = entry["expires"]
        if not expires:
            return {"agent": name, "expires": None, "days_left": None, "expired": False}
        try:
            exp_date = datetime.strptime(expires, "%Y-%m-%d").date()
        except ValueError:
            return {"agent": name, "expires": expires, "days_left": None, "expired": False}
        days_left = (exp_date - datetime.now(KST).date()).days
        return {"agent": name, "expires": expires, "days_left": days_left, "expired": days_left < 0}

    legacy_token = os.environ.get("ACCESS_TOKEN", "")
    if legacy_token and _tokens_equal(provided, legacy_token):
        return {"agent": "(레거시 공용 토큰)", "expires": None, "days_left": None, "expired": False}

    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/agents")
async def list_agents(authorization: str = Header(default=""), refresh: bool = False):
    """등록된 중개사 이름과 만료일 목록을 보여준다(토큰 값은 절대 포함하지 않음).
    AGENT_TOKENS나 GitHub의 agents.json을 방금 수정한 뒤 제대로 반영됐는지
    확인하는 용도. ADMIN_TOKEN 환경변수를 별도로 등록해야 쓸 수 있다
    (설정 안 했으면 항상 401).

    ?refresh=1을 붙이면 GitHub 캐시(30초)를 기다리지 않고 즉시 다시 읽어온다 -
    방금 agents.json을 고치고 바로 반영됐는지 확인하고 싶을 때 쓴다."""
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    provided = authorization[7:] if authorization.startswith("Bearer ") else ""
    if not admin_token or not _tokens_equal(provided, admin_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if refresh:
        _gh_cache["fetched_at"] = 0.0
    agents = sorted(_load_agent_tokens().items())  # _load_agent_tokens()를 먼저 호출해야
    # 위 refresh 처리로 리셋된 fetched_at을 보고 실제로 다시 조회를 시도하고,
    # 그 결과(성공/실패)가 last_error/last_success_at에 반영된 "다음"이다 -
    # 순서를 바꾸면 방금 시도한 조회 결과가 아니라 그 이전 상태를 보여주게 된다.
    return {
        "agents": [
            {"name": name, "expires": entry["expires"], "expired": _is_expired(entry["expires"])}
            for name, entry in agents
        ],
        # GitHub agents.json 조회 자체가 잘 되고 있는지 - "만료일을 설정했는데도
        # 계속 통과된다"는 문의의 원인이 대부분 여기(조회가 조용히 계속 실패해서
        # 옛날 캐시를 쓰고 있음)였어서, 관리자가 바로 확인할 수 있게 노출한다.
        "github_fetch": {
            "last_success_at": (
                datetime.fromtimestamp(_gh_cache["last_success_at"], KST).isoformat()
                if _gh_cache["last_success_at"] else None
            ),
            "last_error": _gh_cache["last_error"],  # None이면 마지막 시도가 성공했다는 뜻
        },
    }


# ---------------------------------------------------------------------------
# 일반 REST 프록시 - geocode.py/building_ledger.py/land_ledger.py/molit.py가
# 이 엔드포인트를 통해 카카오/공공데이터/VWorld를 "대신" 호출하게 한다.
# ---------------------------------------------------------------------------

_PROXY_TIMEOUT_SEC = 20.0

# api.vworld.kr은 (2026-09 확인) 최신 Linux(OpenSSL 3.x) 환경의 기본 보안수준
# (SECLEVEL=2)에서 거부되는 구형 TLS 암호(SEED 계열 등)로만 응답하려는 것으로
# 보인다 - 그 결과 TLS 핸드셰이크 단계에서 그대로 연결이 끊겨 httpx가
# "Server disconnected without sending a response"(RemoteProtocolError)를
# 낸다. Windows(로컬 배포판, 다른 TLS 스택 사용)에서는 재현되지 않고 Render 같은
# Linux 서버에서만 재현되는 게 이 증상의 특징이다. 이 호스트로 나가는 호출에
# 한해서만 보안수준을 1로 낮춰 구형 암호도 허용한다(다른 호스트 호출에는 영향
# 없음 - httpx.AsyncClient를 호출부마다 새로 만들기 때문에 완전히 격리된다).
_VWORLD_HOST = "api.vworld.kr"


def _ssl_context_for_host(host: str) -> ssl.SSLContext | None:
    if host != _VWORLD_HOST:
        return None
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


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
        # ※ NCP_RELAY_URL이 설정돼 있으면 이 규칙까지 오지 않고 위에서 한국
        # 중계 서버로 위임되므로, 그 경우엔 VWORLD_KEY/VWORLD_DOMAIN을 Render에
        # 둘 필요가 없다(중계 서버 쪽 환경변수로만 있으면 됨).
        "type": "query_multi", "fields": [
            ("key", "VWORLD_KEY"), ("domain", "VWORLD_DOMAIN"),
        ],
    },
}


# 클라이언트가 보낸 headers 중 그대로 전달하면 안 되는 것들. Authorization은 서버가
# 필요한 곳(카카오)에서 직접 다시 채우므로 클라이언트 값은 어느 경우에도 버린다.
_BLOCKED_REQUEST_HEADERS = {
    "host", "content-length", "transfer-encoding", "connection", "te", "upgrade",
    "expect", "cookie", "authorization", "proxy-authorization", "forwarded",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip",
}
_ALLOWED_PROXY_METHODS = {"GET", "POST"}


def _validate_proxy_url(url) -> "httpx.URL":
    """대상 URL이 허용된 호스트(https)인지 엄격히 검사하고, 실제 요청에 쓸 httpx.URL을
    돌려준다. 통과하지 못하면 400/403을 던진다.

    검사는 "실제로 요청을 보내는 라이브러리(httpx)"가 해석한 결과를 기준으로 한다.
    (예전에는 urllib로 검사하고 httpx로 요청해서, 두 라이브러리가 해석을 다르게 하는
    특수한 URL이 있으면 검사를 통과하고 다른 곳으로 요청이 나갈 여지가 있었다.)
      - https만 허용 (http면 실제 키가 암호화 없이 나간다)
      - 주소에 '@', '\\', 공백/제어문자가 있으면 거부 (사용자정보·파서 혼동 속임수 차단)
      - 포트 지정 거부 (기본 443만)
      - 호스트가 _PROXY_HOST_RULES에 "정확히" 있어야 함
      - urllib의 해석과 httpx의 해석이 서로 다르면 거부 (이중 확인)"""
    if not isinstance(url, str) or not url or len(url) > 2000:
        raise HTTPException(status_code=400, detail="url이 올바르지 않습니다.")
    if "@" in url or "\\" in url or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise HTTPException(status_code=403, detail="허용되지 않은 URL 형식입니다.")
    try:
        u = httpx.URL(url)
    except Exception:
        raise HTTPException(status_code=400, detail="url을 해석할 수 없습니다.")
    if u.scheme != "https" or u.userinfo or u.port is not None:
        raise HTTPException(status_code=403, detail="https 기본 포트의 주소만 허용됩니다.")
    host = u.host or ""
    if host not in _PROXY_HOST_RULES:
        raise HTTPException(status_code=403, detail=f"허용되지 않은 대상 호스트입니다: {host}")
    if (urllib.parse.urlparse(url).hostname or "") != host:
        raise HTTPException(status_code=403, detail="URL 해석이 일치하지 않아 거부합니다.")
    return u


@app.post("/proxy")
async def proxy(request: Request, authorization: str = Header(default="")):
    """geocode.py 등이 "이 URL로, 이 파라미터로 대신 호출해줘"라고 보내는
    요청을 실제 API로 중계한다.

    요청 본문(JSON): {"url": "...", "method": "GET", "params": {...}, "headers": {...}}
    url의 호스트가 _PROXY_HOST_RULES에 없으면 403으로 거부한다(이 서버가
    아무 주소나 대신 호출해주는 열린 중계기가 되는 것을 막기 위함)."""
    agent_name = _authenticate(authorization, request)
    _check_quota(agent_name, "proxy", _env_int("PROXY_DAILY_LIMIT", 5000))

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="요청 본문이 올바른 JSON이 아닙니다.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="요청 본문은 JSON 객체여야 합니다.")

    method = str(body.get("method") or "GET").upper()
    if method not in _ALLOWED_PROXY_METHODS:
        raise HTTPException(status_code=405, detail=f"허용되지 않은 메서드입니다: {method}")
    raw_params = body.get("params") or {}
    raw_headers = body.get("headers") or {}
    if not isinstance(raw_params, dict) or not isinstance(raw_headers, dict):
        raise HTTPException(status_code=400, detail="params/headers는 객체여야 합니다.")
    params = dict(raw_params)
    headers = {str(k): str(v) for k, v in raw_headers.items()
               if str(k).lower() not in _BLOCKED_REQUEST_HEADERS}
    json_body = body.get("json")

    target = _validate_proxy_url(body.get("url", ""))
    url = str(target)
    host = target.host
    rule = _PROXY_HOST_RULES[host]

    # ── VWorld 전용: 한국 리전 중계 서버로 위임 (설정돼 있으면) ─────────────────
    # api.vworld.kr이 해외 IP를 차단하는 것으로 보여, NCP_RELAY_URL이 설정돼
    # 있으면 여기서 직접 호출하지 않고 한국 VM(vworld_relay.py)에 그대로
    # 넘긴다 - VWORLD_KEY/VWORLD_DOMAIN도 이제 Render가 아니라 그 VM에만
    # 있으면 된다(아래 query_multi 분기는 그래서 여기 도달하지 않는다).
    # NCP_RELAY_URL이 비어 있으면(아직 중계 서버를 안 만든 경우) 기존처럼
    # Render가 직접 호출을 시도한다(_ssl_context_for_host의 SECLEVEL 완화만
    # 적용된 채로) - 두 방법 중 뭐가 실제로 먹히는지 순서대로 시험해볼 수 있다.
    if host == _VWORLD_HOST:
        relay_url = os.environ.get("NCP_RELAY_URL", "").strip()
        relay_token = os.environ.get("NCP_RELAY_TOKEN", "")
        if relay_url:
            try:
                async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT_SEC) as client:
                    resp = await client.post(
                        f"{relay_url.rstrip('/')}/relay",
                        json={"url": url, "method": method, "params": params, "headers": headers},
                        headers={"Authorization": f"Bearer {relay_token}"},
                    )
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=f"한국 중계 서버(NCP_RELAY_URL) 호출 실패: {e}")

            print(f"[proxy] {datetime.now(timezone.utc).isoformat()} agent={agent_name} "
                  f"host={host} via=relay status={resp.status_code}", flush=True)
            return Response(
                content=resp.content, status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/octet-stream"),
            )

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
        missing = []
        for field_name, env_name in rule["fields"]:
            real_value = os.environ.get(env_name, "")
            if real_value:
                params[field_name] = real_value
            else:
                missing.append(env_name)
        if missing:
            # 예전엔 여기서 없는 값은 그냥 건너뛰고 조용히 넘어갔다 - 그러면
            # VWorld처럼 key/domain 둘 다 필요한 API는, Render에 VWORLD_KEY나
            # VWORLD_DOMAIN 중 하나만 빠져도 "키 없이" 또는 "호출부가 보낸(로컬
            # 기본값) domain으로" 그대로 VWorld에 요청이 나가버렸다. VWorld는
            # 이 경우 502가 아니라 자체 인증 오류를 담은 200 응답을 주는 경우가
            # 많아서, 결과적으로 "서버 설정이 빠졌다"는 사실 자체가 어디에도
            # 드러나지 않고 그냥 "정보 없음"으로만 보이는 문제가 있었다. 이제
            # Render 쪽 환경변수가 실제로 빠졌으면 여기서 바로 502로 명확히
            # 알린다.
            raise HTTPException(
                status_code=502,
                detail=f"서버에 {', '.join(missing)}가 설정되어 있지 않습니다.",
            )

    verify_option = _ssl_context_for_host(host) or True
    try:
        async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT_SEC, verify=verify_option) as client:
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
    agent_name = _authenticate(x_api_key, request)
    _check_quota(agent_name, "anthropic", _env_int("ANTHROPIC_DAILY_LIMIT", 500))

    body = await request.body()
    real_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not real_key:
        raise HTTPException(status_code=502, detail="서버에 ANTHROPIC_API_KEY가 설정되어 있지 않습니다.")

    # ── 비용 보호: 모델/출력 길이 제한 ───────────────────────────────────────────
    # 토큰만 있으면 exe 없이도 이 주소를 직접 호출할 수 있으므로, 서버가 "어떤 모델을
    # 얼마나 길게" 쓸 수 있는지를 정해둔다.
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="요청 본문이 올바른 JSON이 아닙니다.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="요청 본문은 JSON 객체여야 합니다.")

    model = str(payload.get("model") or "")
    allowed_models = [m.strip() for m in os.environ.get("ANTHROPIC_ALLOWED_MODELS", "").split(",") if m.strip()]
    if allowed_models and model not in allowed_models:
        print(f"[anthropic-proxy] 거부: 허용되지 않은 모델 agent={agent_name} model={model!r}", flush=True)
        raise HTTPException(status_code=403, detail=f"허용되지 않은 모델입니다: {model}")

    max_cap = _env_int("ANTHROPIC_MAX_TOKENS_CAP", 8192)
    requested = payload.get("max_tokens")
    if max_cap > 0 and isinstance(requested, (int, float)) and not isinstance(requested, bool) and requested > max_cap:
        print(f"[anthropic-proxy] max_tokens {requested} -> {max_cap}로 낮춤 agent={agent_name}", flush=True)
        payload["max_tokens"] = max_cap
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

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
          f"model={model} status={resp.status_code}", flush=True)
    return Response(content=resp.content, status_code=resp.status_code,
                     media_type=resp.headers.get("content-type"))
