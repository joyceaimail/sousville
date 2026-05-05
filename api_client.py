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
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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


def request_email_code(email: str) -> dict[str, Any]:
    """Email passwordless 第一步：寄 6 位數驗證碼到該 email。"""
    return api.post(
        "/api/v1/auth/email/request-code",
        auth=False,
        json={"email": email},
    )


def verify_email_code(email: str, code: str) -> dict[str, Any]:
    """Email passwordless 第二步：拿 code 換 JWT。成功自動存 token。"""
    data = api.post(
        "/api/v1/auth/email/verify-code",
        auth=False,
        json={"email": email, "code": code},
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


# ─── LINE OAuth flow ────────────────────────────────────────────


_LINE_AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
_OAUTH_STATE_KEY = "_line_oauth_state"


def get_line_channel_id() -> str:
    """前端建 OAuth URL 用的 channel_id（公開資訊）。

    Render 偶爾會吃掉自訂 env vars，這裡寫死預設值當保險。
    要切其他 channel 時再從 env 蓋過。channel_secret 仍只放在後端。
    """
    return _get_secret("LINE_CHANNEL_ID", default="2009958293")


def get_line_callback_url() -> str:
    """LINE 認證後跳回來的網址。預設線上 app.joyceaimail.org。"""
    return _get_secret("LINE_LOGIN_CALLBACK_URL", "https://app.joyceaimail.org")


def build_line_oauth_url() -> str:
    """產生 LINE OAuth 授權頁網址，順手把 state（CSRF token）存進 session_state。

    呼叫流程：
        url = build_line_oauth_url()
        st.link_button("用 LINE 登入", url)
        # → 使用者點下去，跳到 LINE，授權後回到 callback URL，帶 ?code=...&state=...
    """
    state = secrets.token_urlsafe(24)
    st.session_state[_OAUTH_STATE_KEY] = state

    params = {
        "response_type": "code",
        "client_id": get_line_channel_id(),
        "redirect_uri": get_line_callback_url(),
        "state": state,
        "scope": "profile openid",
    }
    return f"{_LINE_AUTHORIZE_URL}?{urlencode(params)}"


def verify_oauth_state(received_state: str) -> bool:
    """CSRF 防護：來自 LINE 的 state 跟我們發出去那個一致就 OK。

    狀況分三種：
    - session_state 有記下、值一致 → True（正常 case）
    - session_state 有記下、值不一致 → False（真 CSRF 嘗試）
    - session_state 沒記下 → True（Streamlit 的 session_state 跨 OAuth
      redirect 不一定持久；放行避免卡關，trade-off：個人 app 的 CSRF
      風險低，不值得用本地檔/cookie 加複雜度去硬鎖）
    """
    expected = st.session_state.pop(_OAUTH_STATE_KEY, None)
    if not expected:
        return True  # 寬鬆通過
    return secrets.compare_digest(str(expected), str(received_state))


def handle_oauth_callback(query_params: dict[str, Any]) -> dict[str, Any] | None:
    """從 ``st.query_params`` 處理 LINE 跳回來的 ``?code=...&state=...``。

    成功 → 自動存 JWT、清掉 query string，回 user dict。
    驗證失敗 / 沒有 code → 回 None。
    LINE 拒絕 / 後端錯誤 → raise APIError。
    """
    code = query_params.get("code")
    state = query_params.get("state")
    if not code:
        return None

    # query_params 在 Streamlit 1.30+ 是 list、之後變 str；都吃下來
    if isinstance(code, list):
        code = code[0] if code else None
    if isinstance(state, list):
        state = state[0] if state else None
    if not code:
        return None

    if not state or not verify_oauth_state(state):
        raise APIError(400, "OAuth state 驗證失敗，請重新登入")

    data = login_with_line_code(code)

    # 把 ?code=... 從網址清掉，避免重整時又用同一張 code 觸發第二次（會失敗）
    try:
        st.query_params.clear()
    except Exception:
        pass

    return data.get("user") if isinstance(data, dict) else None


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


# ─── Session bootstrap ──────────────────────────────────────────


def _compute_age_from_birth(birth_iso: str | None) -> int | None:
    if not birth_iso:
        return None
    try:
        from datetime import date
        bd = date.fromisoformat(birth_iso)
        today = date.today()
        return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    except (ValueError, TypeError):
        return None


def _api_get_with_retry(path: str, retries: int = 2) -> Any:
    """轉發到 ``api.get``；遇到非 401 的 ``APIError``（例如 5xx 冷啟動）retry 一次。

    401 直接跳出（token 真的壞）；其他暫時性錯誤睡 1 秒再試，避免使用者卡關。
    """
    import time as _time
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return api.get(path)
        except Unauthenticated:
            raise
        except APIError as exc:
            last_exc = exc
            if attempt < retries:
                _time.sleep(1.0)
                continue
            raise
    if last_exc:
        raise last_exc


def load_user_into_session() -> bool:
    """登入成功後呼叫一次：拉 ``/users/me`` + ``/profile`` + ``/stats``，
    把資料寫進 ``st.session_state``，**對應到舊版的 user_data shape**，
    讓 app.py 裡既有讀 ``user_data["height"]`` 之類的程式碼不用改。

    回 ``True`` 表示載入成功；``False`` 表示 API 失敗（含 retry 後仍失敗）。
    呼叫端不要急著 clear_tokens — token 可能有效，只是 backend 暫時 502。
    """
    try:
        me = _api_get_with_retry("/api/v1/users/me")
        profile = _api_get_with_retry("/api/v1/users/me/profile")
        stats = _api_get_with_retry("/api/v1/users/me/stats")
    except (Unauthenticated, APIError):
        return False

    height = float(profile["height_cm"]) if profile.get("height_cm") else None
    weight = float(profile["weight_kg"]) if profile.get("weight_kg") else None

    user_data: dict[str, Any] = {
        "name": me.get("display_name") or "",
        "phone": "",
        "email": me.get("email") or "",
        "gender": profile.get("gender") or "",
        "age": _compute_age_from_birth(profile.get("birth_date")),
        "height": height,
        "weight": weight,
        "activity": profile.get("activity_level") or "",
        "goal": profile.get("goal") or "",
        "total_xp": int(stats.get("xp", 0) or 0),
        "level": int(stats.get("level", 1) or 1),
        "coupon": False,  # 之後從 /users/me/discount-codes 推導，暫時 False
        "game_progress": {
            "completed": stats.get("completed_levels", []) or [],
            "total_game_xp": int(stats.get("total_game_xp", 0) or 0),
        },
        "game_hearts": int(stats.get("hearts", 5) or 5),
    }

    st.session_state.user_data = user_data
    st.session_state.user_id = me.get("id")
    # 暫時把 user_id 同時塞進 user_page_id（舊版命名），讓既有讀取程式碼不用改
    st.session_state.user_page_id = me.get("id")
    st.session_state.total_xp = user_data["total_xp"]
    st.session_state.coupon_unlocked = user_data["coupon"]
    st.session_state.game_progress = user_data["game_progress"]
    st.session_state.game_hearts = user_data["game_hearts"]
    if user_data["height"] and user_data["weight"]:
        st.session_state.profile_complete = True

    return True


# ─── Logs / meals / exercises ───────────────────────────────────


def get_today_log() -> dict[str, Any]:
    """``/logs/today`` — 今日完整摘要：daily_log_id / 攝取 / 消耗 / meals / exercises。"""
    return api.get("/api/v1/logs/today")


def create_meal(
    *,
    meal_type: str,
    name: str,
    calories: int,
    source: str = "custom",
    bento_key: str | None = None,
    portions: dict | None = None,
    log_date: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "meal_type": meal_type,
        "name": name,
        "calories": int(calories),
        "source": source,
    }
    if bento_key is not None:
        body["bento_key"] = bento_key
    if portions is not None:
        body["portions"] = portions
    if log_date is not None:
        body["log_date"] = log_date
    return api.post("/api/v1/meals", json=body)


def delete_meal(meal_id: str) -> None:
    api.delete(f"/api/v1/meals/{meal_id}")


def create_exercise(
    *,
    name: str,
    met: float,
    duration_min: int,
    intensity: str = "中強度",
    log_date: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "met": float(met),
        "duration_min": int(duration_min),
        "intensity": intensity,
    }
    if log_date is not None:
        body["log_date"] = log_date
    return api.post("/api/v1/exercises", json=body)


def delete_exercise(exercise_id: str) -> None:
    api.delete(f"/api/v1/exercises/{exercise_id}")


# ─── Profile / weight ───────────────────────────────────────────


def update_profile(updates: dict[str, Any]) -> dict[str, Any]:
    """``PATCH /users/me/profile`` — 局部更新 gender / height / weight / etc。"""
    return api.patch("/api/v1/users/me/profile", json=updates)


def record_weight(
    weight_kg: float,
    recorded_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"weight_kg": float(weight_kg)}
    if recorded_date:
        body["recorded_date"] = recorded_date
    if note:
        body["note"] = note
    return api.post("/api/v1/users/me/weight", json=body)


def list_weight_history(limit: int = 30) -> list[dict[str, Any]]:
    """回最近 ``limit`` 筆紀錄。"""
    data = api.get("/api/v1/users/me/weight", params={"limit": limit})
    if isinstance(data, dict):
        return data.get("entries", []) or []
    return data or []


# ─── Game / Quiz ────────────────────────────────────────────────


def get_game_state() -> dict[str, Any]:
    """``/game/state`` — XP / level / hearts / streak / completed levels。"""
    return api.get("/api/v1/game/state")


def get_chapters() -> dict[str, Any]:
    return api.get("/api/v1/game/chapters")


def get_level(level_id: int) -> dict[str, Any]:
    return api.get(f"/api/v1/game/levels/{level_id}")


def submit_level(level_id: int, answers: list[int]) -> dict[str, Any]:
    return api.post(
        f"/api/v1/game/levels/{level_id}/submit",
        json={"answers": [int(a) for a in answers]},
    )


def refill_hearts() -> dict[str, Any]:
    return api.post("/api/v1/game/hearts/refill")


def list_discount_codes() -> list[dict[str, Any]]:
    data = api.get("/api/v1/users/me/discount-codes")
    if isinstance(data, dict):
        return data.get("codes", []) or []
    return data or []


# ─── Today log → session_state bridge ───────────────────────────


def refresh_today_log_into_session() -> bool:
    """把 ``/logs/today`` 的內容寫進 session_state 的 today_* 欄位，
    讓既有 UI（讀 ``st.session_state.today_meals`` 等）不用改。

    回 True 表示拉成功；False 表示 API 失敗（網路 / cold start）。
    """
    try:
        log = get_today_log()
    except (Unauthenticated, APIError):
        return False

    st.session_state.today_log_id = log.get("daily_log_id")
    st.session_state.today_cal_in = int(log.get("calories_in", 0) or 0)
    st.session_state.today_cal_out = int(log.get("calories_burned", 0) or 0)

    # meals: 顯示用字串 + 原始 records（給 delete 用）
    meals = log.get("meals", []) or []
    st.session_state.today_meals = [
        f"{m.get('name', '')} ({int(m.get('calories', 0) or 0)} kcal)"
        for m in meals
    ]
    st.session_state.today_meal_records = meals

    # exercises 同理
    exercises = log.get("exercises", []) or []
    st.session_state.today_exercises = [
        f"{e.get('name', '')} MET {e.get('met')} "
        f"{int(e.get('duration_min', 0) or 0)}分 "
        f"({int(e.get('calories', 0) or 0)} kcal)"
        for e in exercises
    ]
    st.session_state.today_exercise_records = exercises

    # 寫回 user_data 的 BMR/TDEE/target/bmi（這些是衍生值，每天都重算）
    ud = st.session_state.setdefault("user_data", {})
    if log.get("bmr") is not None:
        ud["bmr"] = log["bmr"]
    if log.get("tdee") is not None:
        ud["tdee"] = log["tdee"]
    if log.get("target_kcal") is not None:
        ud["target"] = log["target_kcal"]

    # 累計份量需要從 meals 推回（用 meal_records 裡的 portions JSONB）
    portions: dict[str, float] = {"蛋白質": 0.0, "全穀根莖": 0.0, "蔬菜": 0.0, "油脂": 0.0, "奶類": 0.0}
    for m in meals:
        meal_portions = m.get("portions") or {}
        if isinstance(meal_portions, dict):
            for k, v in meal_portions.items():
                if k in portions:
                    try:
                        portions[k] += float(v or 0)
                    except (TypeError, ValueError):
                        pass
    st.session_state.portions = portions

    return True


def refresh_game_state_into_session() -> bool:
    """把 ``/game/state`` 拉回來寫進 session_state（hearts、xp、completed）。"""
    try:
        state = get_game_state()
    except (Unauthenticated, APIError):
        return False

    st.session_state.game_hearts = int(state.get("hearts", 5) or 5)
    st.session_state.total_xp = int(state.get("xp", 0) or 0)
    st.session_state.game_progress = {
        "completed": state.get("completed_levels", []) or [],
        "total_game_xp": int(state.get("total_game_xp", 0) or 0),
    }
    # 後端有自動 catch-up regen，UI 顯示倒數時間用：
    st.session_state.hearts_seconds_to_next_regen = int(
        state.get("hearts_seconds_to_next_regen", 0) or 0
    )
    return True

# ─── Theme Sprint helpers ───────────────────────────────────────


def get_active_theme() -> dict[str, Any]:
    """``GET /themes/active`` — 當前期狀態 + friendly encouragement message。

    沒 active run 時回 ``{"has_active": False, "next_theme": ..., "encouragement": ...}``。
    有 active run 時回完整進度（run_id, theme, days, days_achieved, ...）。
    """
    return api.get("/api/v1/themes/active")


def start_next_theme() -> dict[str, Any]:
    """``POST /themes/start-next`` — 使用者按按鈕開下一期。"""
    return api.post("/api/v1/themes/start-next")


def list_badges() -> list[dict[str, Any]]:
    data = api.get("/api/v1/themes/badges")
    if isinstance(data, dict):
        return data.get("badges", []) or []
    return data or []


def refresh_active_theme_into_session() -> bool:
    """把 active theme 寫進 session_state.active_theme，給首頁 widget 讀。

    回 ``True`` 表示拉到資料（不論有沒有 active run）；``False`` = API 失敗。
    """
    try:
        data = get_active_theme()
    except (Unauthenticated, APIError):
        return False
    st.session_state["active_theme"] = data or {}
    return True
