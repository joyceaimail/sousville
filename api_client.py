"""舒肥底家 API client — Streamlit 端對 sufeidijia-api 後端的封裝。

設計原則：
- Token 儲存：優先 ``st.session_state``（in-memory），fallback 讀 / 寫
  ``.auth_cache.json``（讓使用者重整頁不掉登入）
- 401 自動 refresh access token；refresh 失敗才丟 ``Unauthenticated``
- 純讀的公開 endpoint（``/constants/all`` / ``/health/calc``）配 ``@st.cache_data``
  快取避免重複打 API；使用者私有資料不快取

用法：
    from api_client import api, get_constants

    constants = get_constants()             # 公開、含快取
    me = api.get("/users/me/profile")       # 自動帶 JWT
    api.patch("/users/me/profile", json={"weight_kg": 70})

API_BASE_URL：透過 ``API_BASE_URL`` 環境變數或 Streamlit secrets 設定。
預設 ``https://api.joyceaimail.org``（線上 sufeidijia-api 服務）。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st

logger = logging.getLogger(__name__)


# ─── Config ─────────────────────────────────────────────────────


def _get_secret(env_key: str, default: str = "") -> str:
    """跟 app.py 一樣的雙來源讀取：環境變數優先，再來 ``st.secrets``。"""
    val = os.environ.get(env_key, "")
    if val:
        return val
    try:
        return st.secrets.get(env_key, default)  # type: ignore[no-any-return]
    except Exception:
        return default


API_BASE_URL: str = _get_secret(
    "API_BASE_URL",
    default="https://api.joyceaimail.org",
).rstrip("/")

_TIMEOUT_SEC: float = 15.0
_AUTH_CACHE_FILE: Path = Path(__file__).parent / ".auth_cache.json"


# ─── Exceptions ─────────────────────────────────────────────────


class APIError(Exception):
    """API 呼叫失敗的基底（含 status_code 與後端 detail 訊息）。"""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{status_code}] {detail}")


class Unauthenticated(APIError):
    """JWT 無效 / 過期 / refresh 失敗。呼叫端應該導去登入頁。"""

    def __init__(self, detail: str = "尚未登入或登入已過期") -> None:
        super().__init__(401, detail)


# ─── Token storage ──────────────────────────────────────────────


_SESSION_KEY_ACCESS = "_api_access_token"
_SESSION_KEY_REFRESH = "_api_refresh_token"


def _load_disk_cache() -> dict[str, Any]:
    if _AUTH_CACHE_FILE.exists():
        try:
            return json.loads(_AUTH_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_disk_cache(data: dict[str, Any]) -> None:
    try:
        _AUTH_CACHE_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Failed to write %s", _AUTH_CACHE_FILE)


def get_tokens() -> tuple[str | None, str | None]:
    """回傳 ``(access_token, refresh_token)``。session > disk > (None, None)。"""
    access = st.session_state.get(_SESSION_KEY_ACCESS)
    refresh = st.session_state.get(_SESSION_KEY_REFRESH)
    if access:
        return access, refresh

    disk = _load_disk_cache()
    access = disk.get("api_access_token")
    refresh = disk.get("api_refresh_token")
    if access:
        # 同步進 session 加速後續取用
        st.session_state[_SESSION_KEY_ACCESS] = access
        st.session_state[_SESSION_KEY_REFRESH] = refresh
        return access, refresh

    return None, None


def set_tokens(access_token: str, refresh_token: str | None = None) -> None:
    """登入成功後存入。session 跟 disk 都寫，重整頁不會掉登入。"""
    st.session_state[_SESSION_KEY_ACCESS] = access_token
    if refresh_token is not None:
        st.session_state[_SESSION_KEY_REFRESH] = refresh_token

    disk = _load_disk_cache()
    disk["api_access_token"] = access_token
    if refresh_token is not None:
        disk["api_refresh_token"] = refresh_token
    _save_disk_cache(disk)


def clear_tokens() -> None:
    """登出。從 session、disk 同時清乾淨。"""
    for key in (_SESSION_KEY_ACCESS, _SESSION_KEY_REFRESH):
        st.session_state.pop(key, None)

    disk = _load_disk_cache()
    disk.pop("api_access_token", None)
    disk.pop("api_refresh_token", None)
    _save_disk_cache(disk)


# ─── Low-level request ─────────────────────────────────────────


def _build_headers(auth: bool) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if auth:
        access, _ = get_tokens()
        if access:
            headers["Authorization"] = f"Bearer {access}"
    return headers


def _try_refresh() -> bool:
    """試著用 refresh token 換新 access token。成功回 True。"""
    _, refresh = get_tokens()
    if not refresh:
        return False
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/v1/auth/refresh",
            json={"refresh_token": refresh},
            timeout=_TIMEOUT_SEC,
        )
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    data = response.json()
    new_access = data.get("access_token")
    if not new_access:
        return False
    set_tokens(new_access, refresh)
    return True


def _parse_error(response: requests.Response) -> str:
    """從 4xx/5xx 回應抽出可讀訊息。"""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"

    if isinstance(body, dict):
        # 後端統一格式 {"error": {"code": ..., "message": ...}}
        if "error" in body and isinstance(body["error"], dict):
            return str(body["error"].get("message") or body["error"])
        # FastAPI 預設 {"detail": "..."} 或 {"detail": [{...}]}
        if "detail" in body:
            return str(body["detail"])
    return str(body)[:200]


class _APIRequester:
    """所有 endpoint 共用的 request helper。實例化後用 ``api`` 暴露。"""

    def request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json: Any = None,
        params: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        retry_on_401: bool = True,
    ) -> Any:
        url = f"{API_BASE_URL}{path}"
        try:
            response = requests.request(
                method,
                url,
                headers=_build_headers(auth),
                json=json,
                params=params,
                files=files,
                data=data,
                timeout=_TIMEOUT_SEC,
            )
        except requests.RequestException as exc:
            raise APIError(0, f"網路錯誤：{exc}") from exc

        # 401 → 試一次 refresh，再不行才 Unauthenticated
        if response.status_code == 401 and auth and retry_on_401:
            if _try_refresh():
                return self.request(
                    method, path,
                    auth=auth, json=json, params=params, files=files, data=data,
                    retry_on_401=False,
                )
            clear_tokens()
            raise Unauthenticated()

        if response.status_code >= 400:
            raise APIError(response.status_code, _parse_error(response))

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(self, path: str, *, params: dict[str, Any] | None = None, auth: bool = True) -> Any:
        return self.request("GET", path, auth=auth, params=params)

    def post(
        self, path: str, *,
        json: Any = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        return self.request("POST", path, auth=auth, json=json, files=files, data=data)

    def patch(self, path: str, *, json: Any = None, auth: bool = True) -> Any:
        return self.request("PATCH", path, auth=auth, json=json)

    def delete(self, path: str, *, auth: bool = True) -> Any:
        return self.request("DELETE", path, auth=auth)


api = _APIRequester()


# ─── Auth wrappers ──────────────────────────────────────────────


def login_with_line_code(code: str) -> dict[str, Any]:
    """LINE OAuth 第二步：拿 ``code`` 換 JWT。成功會自動把 token 存進 session+disk。"""
    data = api.post(
        "/api/v1/auth/line-login",
        auth=False,
        json={"code": code},
    )
    if isinstance(data, dict):
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        if access:
            set_tokens(access, refresh)
    return data


def is_authenticated() -> bool:
    access, _ = get_tokens()
    return access is not None


# ─── Cached read-only helpers ───────────────────────────────────


@st.cache_data(ttl=3600)  # 常數一小時刷一次
def get_constants() -> dict[str, Any]:
    """``/constants/all`` — 餐盒 / MET / 份量 / 等級門檻 / 倍率。公開，無 auth。"""
    return api.get("/api/v1/constants/all", auth=False)


@st.cache_data(ttl=300)  # 章節 5 分鐘刷一次（使用者通關後想看新狀態）
def get_chapters_cached() -> dict[str, Any]:
    """``/game/chapters`` — 需要 JWT；快取以使用者 session 為單位。"""
    return api.get("/api/v1/game/chapters")


def health_calc(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str,
) -> dict[str, Any]:
    """``/health/calc`` — 純算式，公開無 auth。不快取（每組輸入都不同）。"""
    return api.post(
        "/api/v1/health/calc",
        auth=False,
        json={
            "weight_kg": weight_kg,
            "height_cm": height_cm,
            "age": age,
            "gender": gender,
            "activity_level": activity_level,
            "goal": goal,
        },
    )
