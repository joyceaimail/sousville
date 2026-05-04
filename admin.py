"""舒肥底家 SousVille — 管理後台

架構：
- **讀**：從本機 SQLite 鏡像（``data/sousville.db``）— 由 ``scripts/sync_from_cloud.py``
  每小時透過 launchd 自動拉 Supabase 同步。
- **寫**：write-through — 先打 Supabase（service key bypass RLS），成功後鏡到
  本機 SQLite，避免 split-brain。

啟動：
    streamlit run admin.py

第一次跑：
    cp .env.example .env && 編輯 .env 填 SUPABASE_*  + ADMIN_SECRET
    python scripts/sync_from_cloud.py --full      # 拉全量
    bash scripts/install_sync_schedule.sh         # 裝排程
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path

import streamlit as st

# ── 把專案根加到 sys.path，scripts 才匯得到 ──
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from scripts import local_db, sync_engine  # noqa: E402


# ═══════════════════════════════════════════════════════════
#  常數
# ═══════════════════════════════════════════════════════════

def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, default)  # type: ignore[no-any-return]
    except Exception:
        return default


ADMIN_SECRET = _env("ADMIN_SECRET")
QUIZ_FILE = PROJECT_ROOT / "quiz_bank.json"
LOGO_PATH = PROJECT_ROOT / "assets" / "logo.png"


# ═══════════════════════════════════════════════════════════
#  頁面設定 + CSS
# ═══════════════════════════════════════════════════════════

st.set_page_config(
    page_title="舒肥底家 | 管理後台",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)

st.markdown(
    '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=Quicksand:wght@500;600;700&display=swap" rel="stylesheet">',
    unsafe_allow_html=True,
)

st.markdown("""
<style>
:root {
  --blue: #1B9D9E; --blue-dim: #158586; --blue-deep: #0E6E6F;
  --blue-light: #7ED4D4; --gold: #FFB300;
  --red: #EF5350; --green: #43A047;
  --bg: #F0F7F8; --bg-card: #FFFFFF; --text: #1A3C40;
  --text-dim: #6B9DA0; --border: rgba(27,157,158,0.12);
  --shadow: 0 4px 20px rgba(27,157,158,0.08);
}
[data-testid="stAppViewContainer"] { background: var(--bg); }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #E8F4F4 0%, #FFF 40%) !important;
}
h1,h2,h3,h4 { font-family:'Noto Sans TC',sans-serif !important; color:var(--text) !important; }
.stButton > button[kind="primary"] {
  background:linear-gradient(135deg,var(--blue),var(--blue-deep)) !important;
  border:none !important; border-radius:12px !important;
  font-weight:700 !important; color:#fff !important;
}
.stButton > button[kind="secondary"] {
  border-radius:12px !important; font-weight:600 !important;
  border:1px solid var(--border) !important; color:var(--text) !important;
  background:var(--bg-card) !important;
}
.metric-card {
  background:var(--bg-card); border-radius:16px; padding:24px 28px;
  border:1px solid var(--border); box-shadow:var(--shadow); text-align:center;
}
.metric-card .value { font-size:2rem; font-weight:900; font-family:'Quicksand',sans-serif; }
.metric-card .label { font-size:.85rem; color:var(--text-dim); margin-top:4px; }
.sync-banner {
  background: linear-gradient(135deg, rgba(27,157,158,0.06), rgba(255,179,0,0.04));
  border:1px solid var(--border); border-radius:12px;
  padding:10px 16px; margin-bottom:14px; display:flex;
  justify-content:space-between; align-items:center; font-size:.88rem;
}
.sync-fresh   { color: var(--green); font-weight:700; }
.sync-stale   { color: var(--gold-dim); font-weight:700; }
.sync-error   { color: var(--red); font-weight:700; }
#MainMenu { visibility:hidden; }
footer { visibility:hidden; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Session State
# ═══════════════════════════════════════════════════════════

def init_state() -> None:
    defaults = {
        "admin_auth": False,
        "page": "dashboard",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ═══════════════════════════════════════════════════════════
#  登入（單一 ADMIN_SECRET，避免再開 admin_users 表）
# ═══════════════════════════════════════════════════════════

def page_login() -> None:
    st.markdown("<div style='text-align:center; padding:60px 0 20px;'>", unsafe_allow_html=True)
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=120)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div style='text-align:center; max-width:400px; margin:0 auto;'>
      <h1 style='font-size:1.6rem;'>舒肥底家 管理後台</h1>
      <p style='color:var(--text-dim);'>輸入 ADMIN_SECRET 進入</p>
    </div>
    """, unsafe_allow_html=True)

    if not ADMIN_SECRET:
        st.error(
            "⚠️ ADMIN_SECRET 環境變數沒設。"
            "請在 `.env` 加 `ADMIN_SECRET=...` 後重啟 admin.py。"
        )
        return

    with st.form("login_form"):
        secret = st.text_input("ADMIN_SECRET", type="password")
        ok = st.form_submit_button("登入", use_container_width=True, type="primary")

    if ok:
        if secret != ADMIN_SECRET:
            st.error("金鑰錯誤")
            return
        st.session_state.admin_auth = True
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  Sync status banner（每頁都顯示）+ 手動 Sync 按鈕
# ═══════════════════════════════════════════════════════════

def _format_age(iso_str: str | None) -> str:
    if not iso_str:
        return "（從未）"
    try:
        ts = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(ts.tzinfo) - ts
    except (ValueError, TypeError):
        return iso_str
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs} 秒前"
    if secs < 3600:
        return f"{secs // 60} 分鐘前"
    if secs < 86400:
        return f"{secs // 3600} 小時前"
    return f"{secs // 86400} 天前"


def render_sync_banner() -> None:
    summary = local_db.sync_status_summary()
    last = summary.get("last_run") or {}
    status = last.get("status") or "—"
    finished = last.get("finished_at")
    rows = last.get("rows_pulled", 0) or 0

    cls = {
        "ok":      "sync-fresh",
        "partial": "sync-stale",
        "error":   "sync-error",
    }.get(status, "sync-stale")

    text = f"上次同步：<span class='{cls}'>{status.upper()}</span> · "
    text += f"{_format_age(finished)} · 拉 {rows} 筆"
    if last.get("error_message"):
        text += f" · ⚠️ {last['error_message'][:80]}"

    cols = st.columns([6, 2])
    with cols[0]:
        st.markdown(f"<div class='sync-banner'>{text}</div>", unsafe_allow_html=True)
    with cols[1]:
        if st.button("🔄 立刻同步", use_container_width=True, type="secondary"):
            with st.spinner("同步中…可能需要 20–60 秒"):
                try:
                    result = sync_engine.pull_all()
                    if result["status"] == "ok":
                        st.success(f"✅ 同步完成，拉了 {result['total_rows']} 筆")
                    else:
                        st.warning(
                            f"⚠️ 部分失敗（狀態 {result['status']}）："
                            + ", ".join(f"{t}={e[:60]}" for t, e in result["errors"].items())
                        )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"同步失敗：{exc}")
            st.rerun()


# ═══════════════════════════════════════════════════════════
#  數據總覽
# ═══════════════════════════════════════════════════════════

def page_dashboard() -> None:
    st.markdown("## 數據總覽", unsafe_allow_html=True)
    render_sync_banner()

    # ── KPI 卡片 ──
    user_count = local_db.query_one("SELECT COUNT(*) AS n FROM users")["n"]
    today = str(date.today())
    active_today = local_db.query_one(
        "SELECT COUNT(DISTINCT user_id) AS n FROM daily_logs WHERE log_date = ?",
        (today,),
    )["n"]
    week_ago = str(date.today() - timedelta(days=7))
    new_users = local_db.query_one(
        "SELECT COUNT(*) AS n FROM users WHERE created_at >= ?", (week_ago,),
    )["n"]
    discount_count = local_db.query_one(
        "SELECT COUNT(*) AS n FROM user_discount_codes WHERE used_at IS NULL"
    )["n"]

    c1, c2, c3, c4 = st.columns(4)
    for col, val, label, color in [
        (c1, user_count,    "總會員",     "var(--blue)"),
        (c2, active_today,  "今日活躍",   "var(--gold)"),
        (c3, new_users,     "本週新註冊", "var(--green)"),
        (c4, discount_count, "未用折扣碼", "var(--blue-deep)"),
    ]:
        with col:
            st.markdown(
                f"""<div class='metric-card'>
                  <div class='value' style='color:{color};'>{val}</div>
                  <div class='label'>{label}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── 最近 7 天每日活躍 ──
    st.markdown("### 最近 7 天每日活躍")
    rows = local_db.query_all(
        """
        SELECT log_date, COUNT(DISTINCT user_id) AS active_users,
               SUM(target_kcal) AS total_target
          FROM daily_logs
         WHERE log_date >= ?
      GROUP BY log_date
      ORDER BY log_date ASC
        """,
        (str(date.today() - timedelta(days=6)),),
    )
    if rows:
        st.bar_chart(
            {r["log_date"]: r["active_users"] for r in rows},
            use_container_width=True,
            height=240,
        )
    else:
        st.info("最近 7 天還沒人寫紀錄")

    # ── 最近 10 筆飲食 / 運動 ──
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("### 最近飲食紀錄")
        meals = local_db.query_all(
            """
            SELECT m.name, m.calories, m.source, m.created_at,
                   u.display_name AS who
              FROM meal_records m
              JOIN users u ON u.id = m.user_id
          ORDER BY m.created_at DESC
             LIMIT 10
            """
        )
        if not meals:
            st.caption("（沒有資料）")
        for m in meals:
            st.markdown(
                f"- **{m['who'] or '?'}** · {m['name']} "
                f"`{m['calories']} kcal` · {(m['created_at'] or '')[:16].replace('T',' ')}"
            )
    with cc2:
        st.markdown("### 最近運動紀錄")
        exes = local_db.query_all(
            """
            SELECT e.name, e.calories, e.duration_min, e.created_at,
                   u.display_name AS who
              FROM exercise_records e
              JOIN users u ON u.id = e.user_id
          ORDER BY e.created_at DESC
             LIMIT 10
            """
        )
        if not exes:
            st.caption("（沒有資料）")
        for e in exes:
            st.markdown(
                f"- **{e['who'] or '?'}** · {e['name']} "
                f"{e['duration_min']}分 `{e['calories']} kcal` · "
                f"{(e['created_at'] or '')[:16].replace('T',' ')}"
            )


# ═══════════════════════════════════════════════════════════
#  會員管理（list + drill-down + edit tier / xp）
# ═══════════════════════════════════════════════════════════

def page_members() -> None:
    st.markdown("## 會員管理", unsafe_allow_html=True)
    render_sync_banner()

    q = st.text_input("🔍 搜尋（display_name / email / line_user_id）", key="member_search")
    sql = """
        SELECT id, display_name, email, line_user_id, tier, xp,
               height_cm, weight_kg, created_at
          FROM users
    """
    params: tuple = ()
    if q:
        like = f"%{q}%"
        sql += " WHERE display_name LIKE ? OR email LIKE ? OR line_user_id LIKE ?"
        params = (like, like, like)
    sql += " ORDER BY created_at DESC LIMIT 200"

    users = local_db.query_all(sql, params)
    st.caption(f"顯示 {len(users)} 位會員（最多 200 筆）")

    if not users:
        st.info("沒有符合條件的會員")
        return

    # 表格 + 行動按鈕
    for u in users:
        with st.expander(
            f"👤 {u['display_name'] or '—'}  ·  {u['tier']}  ·  XP {u['xp']}",
            expanded=False,
        ):
            cc1, cc2 = st.columns([3, 2])
            with cc1:
                st.markdown(f"**ID**：`{u['id']}`")
                st.markdown(f"**Email**：{u['email'] or '—'}")
                st.markdown(f"**LINE UID**：{u['line_user_id'] or '—'}")
                st.markdown(
                    f"**身高 / 體重**：{u['height_cm'] or '—'} cm / "
                    f"{u['weight_kg'] or '—'} kg"
                )
                st.markdown(f"**註冊時間**：{(u['created_at'] or '')[:16].replace('T',' ')}")

            with cc2:
                with st.form(f"edit_user_{u['id']}"):
                    new_tier = st.selectbox(
                        "tier",
                        ["一般", "會員", "VIP"],
                        index=["一般", "會員", "VIP"].index(u["tier"])
                            if u["tier"] in ("一般", "會員", "VIP") else 0,
                        key=f"tier_{u['id']}",
                    )
                    new_xp = st.number_input(
                        "XP",
                        min_value=0,
                        max_value=999999,
                        value=int(u["xp"] or 0),
                        step=10,
                        key=f"xp_{u['id']}",
                    )
                    save = st.form_submit_button("💾 儲存（雙寫雲端 + 本機）",
                                                 type="primary", use_container_width=True)
                if save:
                    patch = {}
                    if new_tier != u["tier"]:
                        patch["tier"] = new_tier
                    if int(new_xp) != int(u["xp"] or 0):
                        patch["xp"] = int(new_xp)
                    if not patch:
                        st.info("沒有欄位變更")
                    else:
                        try:
                            sync_engine.write_through_update("users", u["id"], patch)
                            st.success(f"✅ 已更新 {list(patch.keys())}")
                            st.rerun()
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"更新失敗：{exc}")

            # ── 該會員最近活動 ──
            st.markdown("**最近 5 筆飲食**")
            recent_m = local_db.query_all(
                "SELECT name, calories, created_at FROM meal_records "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
                (u["id"],),
            )
            for m in recent_m:
                st.markdown(
                    f"- {m['name']} `{m['calories']} kcal` · "
                    f"{(m['created_at'] or '')[:16].replace('T',' ')}"
                )
            if not recent_m:
                st.caption("（沒紀錄）")


# ═══════════════════════════════════════════════════════════
#  折扣碼管理（list + 標記為已使用 / 撤銷）
# ═══════════════════════════════════════════════════════════

def page_discounts() -> None:
    st.markdown("## 折扣碼管理", unsafe_allow_html=True)
    render_sync_banner()

    show_used = st.checkbox("顯示已使用 / 過期", value=False, key="dc_show_used")
    sql = """
        SELECT d.id, d.code, d.discount_type, d.value, d.chapter_id,
               d.issued_at, d.expires_at, d.used_at,
               u.display_name AS who, u.email
          FROM user_discount_codes d
          LEFT JOIN users u ON u.id = d.user_id
    """
    if not show_used:
        sql += " WHERE d.used_at IS NULL"
    sql += " ORDER BY d.issued_at DESC LIMIT 300"

    codes = local_db.query_all(sql)
    st.caption(f"共 {len(codes)} 筆")

    if not codes:
        st.info("沒有折扣碼")
        return

    # CSV 匯出
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=list(codes[0].keys()))
    writer.writeheader()
    writer.writerows(codes)
    st.download_button(
        "📥 匯出 CSV",
        data=csv_buf.getvalue(),
        file_name=f"discount_codes_{date.today()}.csv",
        mime="text/csv",
    )

    for c in codes:
        used_label = "✅ 已用" if c["used_at"] else "🟢 未用"
        with st.expander(
            f"{used_label}  {c['code']}  ·  {c['discount_type']} {c['value']}  ·  "
            f"{c['who'] or '—'}",
            expanded=False,
        ):
            st.markdown(f"**用戶**：{c['who'] or '—'} ({c['email'] or '—'})")
            st.markdown(f"**章節**：{c['chapter_id']}")
            st.markdown(f"**發放**：{(c['issued_at'] or '—')[:16].replace('T',' ')}")
            st.markdown(f"**到期**：{(c['expires_at'] or '—')[:16].replace('T',' ')}")
            st.markdown(f"**使用**：{(c['used_at'] or '未使用')[:16].replace('T',' ')}")

            cc1, cc2 = st.columns(2)
            with cc1:
                if not c["used_at"] and st.button(
                    "標記為已使用", key=f"use_{c['id']}", type="secondary"
                ):
                    try:
                        sync_engine.write_through_update(
                            "user_discount_codes", c["id"],
                            {"used_at": datetime.utcnow().isoformat() + "Z"},
                        )
                        st.success("已標記")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"失敗：{exc}")
            with cc2:
                if c["used_at"] and st.button(
                    "撤銷使用標記", key=f"unuse_{c['id']}", type="secondary"
                ):
                    try:
                        sync_engine.write_through_update(
                            "user_discount_codes", c["id"], {"used_at": None},
                        )
                        st.success("已撤銷")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"失敗：{exc}")


# ═══════════════════════════════════════════════════════════
#  資料匯出（每張表 CSV）
# ═══════════════════════════════════════════════════════════

def page_export() -> None:
    st.markdown("## 資料匯出", unsafe_allow_html=True)
    render_sync_banner()

    st.markdown(
        "從本機 SQLite 匯出，給 Excel / Tableau / 報告用。匯出範圍 = "
        "**最後一次成功同步前的資料**（非即時）。"
    )

    for table in local_db.SYNCED_TABLES:
        rows = local_db.query_all(f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT 50000")
        if not rows:
            st.caption(f"`{table}` — （空）")
            continue
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            f"📥 {table} ({len(rows)} 筆)",
            data=buf.getvalue(),
            file_name=f"{table}_{date.today()}.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ═══════════════════════════════════════════════════════════
#  同步狀態 / 維運
# ═══════════════════════════════════════════════════════════

def page_sync() -> None:
    st.markdown("## 同步狀態", unsafe_allow_html=True)
    render_sync_banner()

    summary = local_db.sync_status_summary()

    st.markdown("### 各資料表 cursor / 上次同步")
    if not summary["tables"]:
        st.info("還沒同步過。請按上方「立刻同步」或執行 "
                "`python scripts/sync_from_cloud.py --full`。")
    else:
        st.dataframe(summary["tables"], use_container_width=True)

    st.markdown("---")
    st.markdown("### 高級操作")

    colA, colB = st.columns(2)
    with colA:
        if st.button("🔄 全量重抓所有表（會比較慢）", type="secondary"):
            with st.spinner("全量重抓…"):
                conn = local_db.get_conn()
                conn.execute("DELETE FROM _sync_meta")
                try:
                    result = sync_engine.pull_all()
                    st.success(f"✅ 重抓完成，共 {result['total_rows']} 筆")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"失敗：{exc}")
            st.rerun()
    with colB:
        if st.button("📂 開啟資料庫資料夾", type="secondary"):
            try:
                subprocess.Popen(["open", str(local_db.get_db_path().parent)])
            except Exception as exc:  # noqa: BLE001
                st.error(f"開啟失敗：{exc}")

    st.markdown("---")
    st.markdown("### 排程")
    st.code(
        f"# 安裝排程（macOS launchd，每小時整點）\n"
        f"bash {PROJECT_ROOT}/scripts/install_sync_schedule.sh\n\n"
        f"# 看下次預定執行時間\n"
        f"launchctl print gui/$(id -u)/com.sousville.sync | grep -E 'state|next'\n\n"
        f"# 立刻踢一次\n"
        f"launchctl kickstart -k gui/$(id -u)/com.sousville.sync\n\n"
        f"# 解除\n"
        f"bash {PROJECT_ROOT}/scripts/install_sync_schedule.sh --uninstall",
        language="bash",
    )


# ═══════════════════════════════════════════════════════════
#  題庫管理（純本地 quiz_bank.json，不上 Supabase）
# ═══════════════════════════════════════════════════════════

def _load_quiz() -> dict:
    if QUIZ_FILE.exists():
        with open(QUIZ_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"chapters": []}


def _save_quiz(data: dict) -> None:
    with open(QUIZ_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def page_quiz() -> None:
    st.markdown("## 題庫管理", unsafe_allow_html=True)
    st.caption("題庫存在 `quiz_bank.json`，後端啟動時讀檔；改完要 redeploy 才會生效。")

    quiz = _load_quiz()
    chapters = quiz.get("chapters", [])
    total_levels = sum(len(ch.get("levels", [])) for ch in chapters)
    total_q = sum(
        len(lv.get("questions", []))
        for ch in chapters for lv in ch.get("levels", [])
    )
    st.markdown(f"共 **{len(chapters)}** 章，**{total_levels}** 關，**{total_q}** 題")

    for ch in chapters:
        with st.expander(f"{ch.get('icon','')} 第 {ch.get('id')} 章 — {ch.get('title')}"):
            for lv in ch.get("levels", []):
                badge = " 👑 BOSS" if lv.get("boss") else ""
                st.markdown(
                    f"**Level {lv.get('id')}** — {lv.get('title')}{badge} · "
                    f"{len(lv.get('questions', []))} 題 · 獎勵 {lv.get('reward_xp')} XP"
                )

    st.markdown("---")
    st.markdown("### 編輯 JSON（高級）")
    raw = st.text_area("quiz_bank.json", value=json.dumps(quiz, ensure_ascii=False, indent=2),
                       height=400, key="quiz_raw")
    if st.button("💾 儲存", type="primary"):
        try:
            data = json.loads(raw)
            _save_quiz(data)
            st.success("✅ 已存檔。重新部署後端才會載入新題庫。")
        except json.JSONDecodeError as e:
            st.error(f"JSON 格式錯誤：{e}")


# ═══════════════════════════════════════════════════════════
#  Sidebar
# ═══════════════════════════════════════════════════════════

PAGES = [
    ("dashboard", "📊 數據總覽",   page_dashboard),
    ("members",   "👥 會員管理",   page_members),
    ("discounts", "🎫 折扣碼",     page_discounts),
    ("export",    "📥 資料匯出",   page_export),
    ("sync",      "🔄 同步狀態",   page_sync),
    ("quiz",      "📝 題庫",       page_quiz),
]


def render_sidebar() -> None:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=80)
    st.caption(f"DB：`{local_db.get_db_path().name}`")
    st.caption(f"路徑：{local_db.get_db_path().parent}")

    st.markdown("---")
    for key, label, _ in PAGES:
        if st.button(label, use_container_width=True, type="secondary",
                     key=f"nav_{key}"):
            st.session_state.page = key
            st.rerun()

    st.markdown("---")
    if st.button("登出", use_container_width=True, type="secondary", key="nav_logout"):
        st.session_state.admin_auth = False
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main() -> None:
    init_state()

    # 確保 schema 在
    local_db.get_conn()

    if not st.session_state.admin_auth:
        page_login()
        return

    with st.sidebar:
        render_sidebar()

    page = st.session_state.page
    page_func = next((f for k, _, f in PAGES if k == page), None)
    if page_func is None:
        st.session_state.page = "dashboard"
        page_dashboard()
    else:
        page_func()


if __name__ == "__main__":
    main()
