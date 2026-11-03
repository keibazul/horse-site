"""한국마사회 공공데이터 API 공통 호출기 (표준 라이브러리만 사용).

API 키는 환경변수 KRA_API_KEY 에서 읽는다 (GitHub 저장소 Secret).
data.go.kr 의 '일반 인증키(Encoding)' 를 그대로 넣으면 된다. Decoding 키를 넣었다면
자동으로 한 번 변환해서 다시 시도한다.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://apis.data.go.kr/B551015"
UA = {"User-Agent": "Mozilla/5.0 (horse-site updater)"}


class ApiError(RuntimeError):
    pass


def _key_variants() -> list[str]:
    raw = os.environ.get("KRA_API_KEY", "").strip().strip('"').strip("'")
    if not raw:
        raise ApiError("KRA_API_KEY 환경변수가 비어 있습니다 (저장소 Settings → Secrets → Actions).")
    out = [raw]
    re_enc = urllib.parse.quote(urllib.parse.unquote(raw), safe="")
    if re_enc not in out:
        out.append(re_enc)
    return out


_good_key: str | None = None


def get(path: str, params: dict, retries: int = 3, timeout: int = 40) -> dict:
    """path 예: 'API26_2/entrySheet_2'. JSON 응답 dict 를 돌려준다."""
    global _good_key
    q = urllib.parse.urlencode({**params, "_type": "json"})
    keys = [_good_key] if _good_key else _key_variants()
    last = None
    for key in keys:
        url = f"{BASE}/{path}?{q}&serviceKey={key}"
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    body = r.read().decode("utf-8", "replace")
                if body.lstrip().startswith("<"):
                    # XML 오류 응답 (키 문제 등)
                    if "SERVICE_KEY_IS_NOT_REGISTERED" in body:
                        last = ApiError("등록되지 않은 키")
                        break
                    if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in body:
                        raise ApiError("하루 호출 한도 초과")
                    last = ApiError(body[:200])
                    time.sleep(2 * (attempt + 1))
                    continue
                data = json.loads(body)
                hdr = data.get("response", {}).get("header", {})
                if hdr.get("resultCode") not in ("00", None):
                    raise ApiError(f"{hdr.get('resultCode')} {hdr.get('resultMsg')}")
                _good_key = key
                return data
            except urllib.error.HTTPError as e:
                msg = e.read(400).decode("utf-8", "replace")
                if "NOT_REGISTERED" in msg:
                    last = ApiError("등록되지 않은 키")
                    break
                if "LIMITED" in msg:
                    raise ApiError("하루 호출 한도 초과")
                last = ApiError(f"HTTP {e.code}: {msg[:150]}")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last = ApiError(f"{type(e).__name__}: {e}")
            time.sleep(2 * (attempt + 1))
    raise last or ApiError("알 수 없는 오류")


def items(data: dict) -> list[dict]:
    body = data.get("response", {}).get("body", {}) or {}
    it = body.get("items")
    if not it:
        return []
    it = it.get("item", []) if isinstance(it, dict) else it
    if isinstance(it, dict):
        it = [it]
    return list(it)


def total_count(data: dict) -> int:
    try:
        return int(data["response"]["body"].get("totalCount") or 0)
    except Exception:
        return 0


def get_all(path: str, params: dict, rows: int = 500) -> list[dict]:
    """여러 쪽으로 나뉜 결과를 모두 받는다."""
    out: list[dict] = []
    page = 1
    while True:
        d = get(path, {**params, "pageNo": page, "numOfRows": rows})
        got = items(d)
        out.extend(got)
        tot = total_count(d)
        if not got or len(out) >= tot or len(got) < rows:
            return out
        page += 1
        time.sleep(0.3)
