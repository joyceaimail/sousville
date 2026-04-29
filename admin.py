"""
舒肥底家 SousVille — 管理後台
==============================
Streamlit + Supabase REST API + Notion API

啟動方式：
    streamlit run admin.py
"""

import csv
import io
import json
import os
from datetime import date
from pathlib import Path

import requests as http_requests
import streamlit as st
from notion_client import Client

# ═══════════════════════════════════════════════════════════
#  常數與設定
# ═══════════════════════════════════════════════════════════

def _env(key):
    return os.environ.get(key, "") or st.secrets.get(key, "")

SUPABASE_URL    = _env("SUPABASE_URL")
SUPABASE_KEY    = _env("SUPABASE_SERVICE_KEY")
NOTION_TOKEN    = _env("NOTION_TOKEN")
NOTION_USERS_DB = _env("NOTION_USERS_DB_ID")
ADMIN_SECRET    = _env("ADMIN_SECRET")

QUIZ_FILE = Path(__file__).parent / "quiz_bank.json"
LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"

NOTION_API_URL = "https://api.notion.com/v1"


# ── Supabase REST helpers ──

def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def sb_get(table, columns="*", order=None, limit=500, **filters):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={columns}&limit={limit}"
    for k, v in filters.items():
        if v is not None:
            url += f"&{k}=eq.{v}"
    if order:
        url += f"&order={order}"
    resp = http_requests.get(url, headers=_sb_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()

def sb_post(table, data):
    resp = http_requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_sb_headers(), json=data, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def sb_patch(table, row_id, data):
    headers = {**_sb_headers()}
    headers["Prefer"] = "return=representation"
    resp = http_requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}",
        headers=headers, json=data, timeout=15,
    )
    resp.raise_for_status()
    return resp.json()

def sb_delete(table, row_id):
    resp = http_requests.delete(
        f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}",
        headers=_sb_headers(), timeout=15,
    )
    resp.raise_for_status()


# ── Notion helpers ──

def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

def get_notion():
    if not NOTION_TOKEN:
        st.error("NOTION_TOKEN 尚未設定")
        st.stop()
    return Client(auth=NOTION_TOKEN)

def fetch_all_users():
    """從 Notion Users DB 抓取所有會員。"""
    if not NOTION_TOKEN or not NOTION_USERS_DB:
        return []
    notion = get_notion()
    results = []
    has_more = True
    cursor = None
    while has_more:
        kw = {"database_id": NOTION_USERS_DB, "page_size": 100}
        if cursor:
            kw["start_cursor"] = cursor
        resp = notion.databases.query(**kw)
        results.extend(resp.get("results", []))
        has_more = resp.get("has_more", False)
        cursor = resp.get("next_cursor")
    return [p for p in results if not p.get("archived")]

def parse_user(page):
    props = page["properties"]
    return {
        "id": page["id"],
        "name": (props.get("姓名", {}).get("title") or [{}])[0].get("text", {}).get("content", ""),
        "email": props.get("電子郵件", {}).get("email", ""),
        "phone": props.get("電話", {}).get("phone_number", ""),
        "created": page.get("created_time", "")[:10],
    }


# ═══════════════════════════════════════════════════════════
#  頁面設定
# ═══════════════════════════════════════════════════════════

st.set_page_config(
    page_title="舒肥底家 | 管理後台",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"Get Help": None, "Report a bug": None, "About": None},
)

st.markdown('<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=Quicksand:wght@500;600;700&display=swap" rel="stylesheet">', unsafe_allow_html=True)

st.markdown("""
<style>
:root { lang: "zh-TW";
  --blue: #1B9D9E; --blue-dim: #158586; --blue-deep: #0E6E6F;
  --blue-light: #7ED4D4; --blue-glow: rgba(27,157,158,0.22);
  --gold: #FFB300; --gold-dim: #FF8F00;
  --red: #EF5350; --green: #43A047;
  --bg: #F0F7F8; --bg-card: #FFFFFF; --text: #1A3C40;
  --text-dim: #6B9DA0; --border: rgba(27,157,158,0.12);
  --shadow: 0 4px 20px rgba(27,157,158,0.08);
}
[data-testid="stAppViewContainer"] { background: var(--bg); }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #E8F4F4 0%, #FFF 40%) !important;
  border-right: 2px solid rgba(27,157,158,0.08) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }
h1,h2,h3,h4 { font-family:'Noto Sans TC',sans-serif !important; color:var(--text) !important; }
.stTabs [data-baseweb="tab-list"] { gap:6px; background:transparent; }
.stTabs [data-baseweb="tab"] {
  background:var(--bg-card); color:var(--text-dim); border-radius:12px;
  padding:10px 20px; font-weight:700; border:1px solid var(--border);
  font-family:'Noto Sans TC',sans-serif;
}
.stTabs [aria-selected="true"] {
  background:linear-gradient(135deg,var(--blue),var(--blue-deep)) !important;
  color:#fff !important; border-color:var(--blue) !important;
}
.stTabs [data-baseweb="tab-highlight"] { display:none; }
.stTabs [data-baseweb="tab-content"] { background:transparent; }
.stButton > button[kind="primary"] {
  background:linear-gradient(135deg,var(--blue),var(--blue-deep)) !important;
  border:none !important; border-radius:12px !important;
  font-weight:700 !important; color:#fff !important;
  font-family:'Noto Sans TC',sans-serif !important;
}
.stButton > button[kind="secondary"] {
  border-radius:12px !important; font-weight:600 !important;
  border:1px solid var(--border) !important; color:var(--text) !important;
  background:var(--bg-card) !important;
  font-family:'Noto Sans TC',sans-serif !important;
}
.card {
  background:var(--bg-card); border-radius:16px; padding:24px;
  border:1px solid var(--border); box-shadow:var(--shadow);
  transition:box-shadow .3s,transform .2s;
}
.card:hover { box-shadow:0 6px 28px rgba(27,157,158,0.15); transform:translateY(-2px); }
.metric-card {
  background:var(--bg-card); border-radius:16px; padding:24px 28px;
  border:1px solid var(--border); box-shadow:var(--shadow); text-align:center;
}
.metric-card .value { font-size:2rem; font-weight:900; font-family:'Quicksand',sans-serif; }
.metric-card .label { font-size:.85rem; color:var(--text-dim); margin-top:4px; }
#MainMenu { visibility:hidden; }
footer { visibility:hidden; }
footer:after {
  content:'© 2026 舒肥底家 SousVille 管理後台'; visibility:visible;
  display:block; text-align:center; padding:10px;
  color:var(--text-dim); font-size:.8rem; font-family:'Noto Sans TC',sans-serif;
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Session State
# ═══════════════════════════════════════════════════════════

def init_state():
    defaults = {
        "admin_auth": False,
        "admin_user": "",
        "page": "dashboard",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ═══════════════════════════════════════════════════════════
#  頁面：登入
# ═══════════════════════════════════════════════════════════

def page_login():
    st.markdown("<div style='text-align:center; padding:60px 0 20px;'>", unsafe_allow_html=True)
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=120)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div style='text-align:center; max-width:400px; margin:0 auto;'>
      <h1 style='font-size:1.6rem;'>舒肥底家 管理後台</h1>
      <p style='color:var(--text-dim);'>請輸入管理員帳號以登入</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        c1, c2 = st.columns(2)
        with c1:
            username = st.text_input("帳號")
        with c2:
            password = st.text_input("密碼", type="password")
        secret = st.text_input("後台金鑰", type="password")
        submitted = st.form_submit_button("登入", use_container_width=True, type="primary")

    if submitted:
        if not username or not password or not secret:
            st.warning("請填寫所有欄位")
            return

        if ADMIN_SECRET and secret != ADMIN_SECRET:
            st.error("後台金鑰錯誤")
            return

        if SUPABASE_URL:
            try:
                admins = sb_get("admin_users", columns="id,username",
                                username=username)
                if not admins:
                    st.error("帳號不存在")
                    return
                st.session_state.admin_auth = True
                st.session_state.admin_user = username
                st.rerun()
            except Exception as e:
                st.error(f"驗證失敗：{e}")
        else:
            st.error("SUPABASE_URL 尚未設定")


# ═══════════════════════════════════════════════════════════
#  頁面：數據總覽
# ═══════════════════════════════════════════════════════════

def page_dashboard():
    st.markdown("## 數據總覽", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)

    # ── 會員數（Notion）──
    with col1:
        try:
            users = fetch_all_users()
            member_count = len(users)
        except Exception:
            member_count = 0
        st.markdown(f"""
        <div class='metric-card'>
          <div class='value' style='color:var(--blue);'>{member_count}</div>
          <div class='label'>會員數</div>
        </div>""", unsafe_allow_html=True)

    # ── 訂單數 / 營收 / VIP（Supabase）──
    order_count = 0
    total_revenue = 0
    vip_count = 0

    if SUPABASE_URL:
        try:
            orders = sb_get("orders", columns="id,amount,status", limit=1000)
            order_count = len(orders)
            total_revenue = sum(
                float(o.get("amount") or 0) for o in orders
                if o.get("status") in ("completed", "paid", "已付款")
            )
        except Exception:
            pass
        try:
            tiers = sb_get("member_tiers", columns="id", tier="VIP")
            vip_count = len(tiers)
        except Exception:
            pass

    with col2:
        st.markdown(f"""
        <div class='metric-card'>
          <div class='value' style='color:var(--gold);'>{order_count}</div>
          <div class='label'>訂單數</div>
        </div>""", unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class='metric-card'>
          <div class='value' style='color:var(--green);'>${total_revenue:,.0f}</div>
          <div class='label'>營收</div>
        </div>""", unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class='metric-card'>
          <div class='value' style='color:var(--blue-deep);'>{vip_count}</div>
          <div class='label'>VIP 會員</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ── 最近訂單 ──
    st.markdown("### 最近訂單")
    if SUPABASE_URL:
        try:
            recent = sb_get("orders", order="created_at.desc", limit=10)
            if recent:
                for o in recent:
                    status = o.get("status", "-")
                    amount = float(o.get("amount") or 0)
                    created = (o.get("created_at") or "")[:16].replace("T", " ")
                    email = o.get("user_email", o.get("email", "-"))
                    st.markdown(
                        f"`{created}`  {email}  "
                        f"**${amount:,.0f}**  "
                        f"<span style='color:{_status_color(status)};'>{status}</span>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("尚無訂單資料")
        except Exception as e:
            st.error(f"讀取訂單失敗：{e}")
    else:
        st.warning("SUPABASE_URL 尚未設定")


def _status_color(status):
    s = str(status).lower()
    if s in ("completed", "paid", "已付款"):
        return "var(--green)"
    if s in ("cancelled", "已取消"):
        return "var(--red)"
    if s in ("pending", "pending_payment", "待付款"):
        return "var(--gold)"
    return "var(--text-dim)"


# ═══════════════════════════════════════════════════════════
#  頁面：會員管理
# ═══════════════════════════════════════════════════════════

def page_members():
    st.markdown("## 會員管理", unsafe_allow_html=True)

    if not NOTION_TOKEN or not NOTION_USERS_DB:
        st.error("NOTION_TOKEN / NOTION_USERS_DB_ID 尚未設定")
        return

    with st.spinner("載入會員清單..."):
        users_raw = fetch_all_users()
    members = [parse_user(u) for u in users_raw]

    # ── VIP tier 查詢 ──
    vip_map = {}
    if SUPABASE_URL:
        try:
            tiers = sb_get("member_tiers", columns="id,notion_user_id,tier,email", limit=1000)
            for t in tiers:
                key = t.get("notion_user_id") or t.get("email") or ""
                vip_map[key] = t
        except Exception:
            pass

    # ── 搜尋 ──
    search = st.text_input("搜尋會員（姓名 / Email）", placeholder="輸入關鍵字…")
    if search:
        q = search.lower()
        members = [m for m in members if q in m["name"].lower() or q in m["email"].lower()]

    st.caption(f"共 {len(members)} 位會員")

    # ── 列表 ──
    for m in members:
        tier = vip_map.get(m["id"]) or vip_map.get(m["email"])
        current_tier = tier.get("tier", "一般") if tier else "一般"

        with st.container():
            c1, c2, c3, c4 = st.columns([3, 3, 1.5, 1.5])
            c1.markdown(f"**{m['name']}**")
            c2.markdown(f"{m['email']}")
            c3.markdown(f"📅 {m['created']}")
            with c4:
                new_tier = st.selectbox(
                    "等級",
                    ["一般", "VIP", "VVIP"],
                    index=["一般", "VIP", "VVIP"].index(current_tier) if current_tier in ("一般", "VIP", "VVIP") else 0,
                    key=f"tier_{m['id']}",
                    label_visibility="collapsed",
                )
                if new_tier != current_tier:
                    if st.button("更新", key=f"btn_{m['id']}", type="primary"):
                        try:
                            if tier:
                                sb_patch("member_tiers", tier["id"], {
                                    "tier": new_tier,
                                    "notion_user_id": m["id"],
                                    "email": m["email"],
                                })
                            else:
                                sb_post("member_tiers", {
                                    "notion_user_id": m["id"],
                                    "email": m["email"],
                                    "tier": new_tier,
                                })
                            st.success(f"{m['name']} → {new_tier}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"更新失敗：{e}")
        st.markdown("---", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  頁面：訂單管理
# ═══════════════════════════════════════════════════════════

def page_orders():
    st.markdown("## 訂單管理", unsafe_allow_html=True)

    if not SUPABASE_URL:
        st.error("SUPABASE_URL 尚未設定")
        return

    # ── 篩選 ──
    fc1, fc2 = st.columns(2)
    with fc1:
        status_filter = st.selectbox(
            "訂單狀態",
            ["全部", "待付款", "已付款", "已取消"],
            label_visibility="collapsed",
        )
    with fc2:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        if st.button("匯出 CSV", type="secondary"):
            _export_orders_csv(status_filter)

    with st.spinner("載入訂單..."):
        try:
            orders = sb_get("orders", order="created_at.desc", limit=500)
        except Exception as e:
            st.error(f"讀取失敗：{e}")
            return

    if status_filter != "全部":
        mapping = {"待付款": "pending", "已付款": "completed", "已取消": "cancelled"}
        target = mapping.get(status_filter, status_filter)
        orders = [o for o in orders if o.get("status") == target]

    st.caption(f"共 {len(orders)} 筆訂單")

    if not orders:
        st.info("目前沒有訂單")
        return

    for o in orders:
        oid = o.get("id", "")
        email = o.get("user_email", o.get("email", "-"))
        amount = float(o.get("amount") or 0)
        status = o.get("status", "-")
        created = (o.get("created_at") or "")[:16].replace("T", " ")

        with st.container():
            c1, c2, c3, c4 = st.columns([2, 3, 1.5, 2])
            c1.markdown(f"`{oid[:8]}…`")
            c2.markdown(f"{email}")
            c3.markdown(f"**${amount:,.0f}**")
            with c4:
                new_status = st.selectbox(
                    "狀態",
                    ["pending", "completed", "cancelled"],
                    index=["pending", "completed", "cancelled"].index(status) if status in ("pending", "completed", "cancelled") else 0,
                    key=f"ost_{oid}",
                    label_visibility="collapsed",
                    format_func=lambda x: {"pending": "待付款", "completed": "已付款", "cancelled": "已取消"}.get(x, x),
                )
                if new_status != status:
                    if st.button("更新", key=f"ob_{oid}", type="primary"):
                        try:
                            sb_patch("orders", oid, {"status": new_status})
                            st.success(f"訂單 {oid[:8]}… → {new_status}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"更新失敗：{e}")
        st.markdown("---", unsafe_allow_html=True)


def _export_orders_csv(status_filter):
    try:
        orders = sb_get("orders", order="created_at.desc", limit=500)
    except Exception as e:
        st.error(f"匯出失敗：{e}")
        return

    if status_filter != "全部":
        mapping = {"待付款": "pending", "已付款": "completed", "已取消": "cancelled"}
        target = mapping.get(status_filter, status_filter)
        orders = [o for o in orders if o.get("status") == target]

    buf = io.StringIO()
    writer = csv.writer(buf)
    all_keys = set()
    for o in orders:
        all_keys.update(o.keys())
    all_keys = sorted(all_keys)
    writer.writerow(all_keys)
    for o in orders:
        writer.writerow([o.get(k, "") for k in all_keys])

    st.download_button(
        label=f"下載 CSV ({len(orders)} 筆)",
        data=buf.getvalue().encode("utf-8-sig"),
        file_name=f"orders_{date.today()}.csv",
        mime="text/csv",
        type="primary",
    )


# ═══════════════════════════════════════════════════════════
#  頁面：折扣碼管理
# ═══════════════════════════════════════════════════════════

def page_discounts():
    st.markdown("## 折扣碼管理", unsafe_allow_html=True)

    if not SUPABASE_URL:
        st.error("SUPABASE_URL 尚未設定")
        return

    # ── 新增表單 ──
    with st.expander("新增折扣碼", expanded=False):
        with st.form("discount_form"):
            dc1, dc2 = st.columns(2)
            with dc1:
                code = st.text_input("折扣碼", placeholder="例：SOUSVILLE85")
                discount_type = st.selectbox("類型", ["percentage", "fixed"])
            with dc2:
                value = st.number_input("折扣值", min_value=0, step=1, value=15)
                max_uses = st.number_input("最大使用次數", min_value=0, value=100, step=1)
            min_order = st.number_input("最低訂單金額", min_value=0, value=0, step=50)
            expires = st.date_input("到期日")
            is_active = st.checkbox("啟用", value=True)
            submitted = st.form_submit_button("建立", type="primary")

        if submitted:
            if not code:
                st.warning("請輸入折扣碼")
            else:
                try:
                    sb_post("discount_codes", {
                        "code": code.upper(),
                        "discount_type": discount_type,
                        "value": value,
                        "max_uses": max_uses or None,
                        "min_order": min_order or None,
                        "expires_at": expires.isoformat() if expires else None,
                        "is_active": is_active,
                        "used_count": 0,
                    })
                    st.success(f"折扣碼 {code.upper()} 已建立")
                    st.rerun()
                except Exception as e:
                    st.error(f"建立失敗：{e}")

    st.markdown("---")

    # ── 列表 ──
    with st.spinner("載入折扣碼..."):
        try:
            codes = sb_get("discount_codes", order="created_at.desc")
        except Exception as e:
            st.error(f"讀取失敗：{e}")
            return

    if not codes:
        st.info("尚無折扣碼")
        return

    for c in codes:
        cid = c.get("id", "")
        code_val = c.get("code", "")
        dtype = c.get("discount_type", "")
        val = c.get("value", 0)
        used = c.get("used_count", 0) or 0
        max_u = c.get("max_uses")
        active = c.get("is_active", False)
        expires = c.get("expires_at", "")

        display_val = f"{val}%" if dtype == "percentage" else f"${val}"
        status_text = "啟用" if active else "停用"
        status_color = "var(--green)" if active else "var(--red)"
        limit_text = f"{used}/{max_u}" if max_u else f"{used}/∞"
        expires_text = expires[:10] if expires else "無期限"

        with st.container():
            mc1, mc2, mc3, mc4, mc5, mc6 = st.columns([2, 1.5, 1.5, 1.5, 1.5, 1])
            mc1.markdown(f"**{code_val}**")
            mc2.markdown(display_val)
            mc3.markdown(limit_text)
            mc4.markdown(f"📅 {expires_text}")
            mc5.markdown(f"<span style='color:{status_color};'>{status_text}</span>", unsafe_allow_html=True)
            with mc6:
                if st.button("切換", key=f"dt_{cid}", type="secondary"):
                    try:
                        sb_patch("discount_codes", cid, {"is_active": not active})
                        st.rerun()
                    except Exception as e:
                        st.error(f"更新失敗：{e}")
                if st.button("刪除", key=f"dd_{cid}", type="secondary"):
                    try:
                        sb_delete("discount_codes", cid)
                        st.rerun()
                    except Exception as e:
                        st.error(f"刪除失敗：{e}")
        st.markdown("---", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  頁面：題庫管理
# ═══════════════════════════════════════════════════════════

def load_quiz():
    if QUIZ_FILE.exists():
        with open(QUIZ_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_quiz(data):
    with open(QUIZ_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def page_quiz():
    st.markdown("## 題庫管理", unsafe_allow_html=True)

    quiz = load_quiz()
    st.caption(f"共 {len(quiz)} 題")

    # ── 新增 ──
    with st.expander("新增題目", expanded=False):
        with st.form("quiz_form"):
            question = st.text_area("題目")
            oc1, oc2 = st.columns(2)
            with oc1:
                opt0 = st.text_input("選項 A", key="qo0")
                opt1 = st.text_input("選項 B", key="qo1")
            with oc2:
                opt2 = st.text_input("選項 C", key="qo2")
                opt3 = st.text_input("選項 D", key="qo3")
            answer = st.selectbox("正確答案", ["A", "B", "C", "D"], index=0)
            explanation = st.text_area("解析")
            submitted = st.form_submit_button("新增題目", type="primary")

        if submitted:
            if not question or not all([opt0, opt1, opt2, opt3]):
                st.warning("請填寫完整")
            else:
                new_q = {
                    "id": max((q.get("id", 0) for q in quiz), default=0) + 1,
                    "question": question,
                    "options": [opt0, opt1, opt2, opt3],
                    "answer": ["A", "B", "C", "D"].index(answer),
                    "explanation": explanation,
                }
                quiz.append(new_q)
                save_quiz(quiz)
                st.success("題目已新增")
                st.rerun()

    st.markdown("---")

    # ── 題目列表 ──
    for i, q in enumerate(quiz):
        qid = q.get("id", i + 1)
        opts = q.get("options", [])
        ans_idx = q.get("answer", 0)
        ans_label = ["A", "B", "C", "D"][ans_idx] if ans_idx < len(opts) else "?"
        expl = q.get("explanation", "")

        with st.container():
            st.markdown(f"**Q{id}:** {q['question']}")
            opt_text = "  |  ".join(
                f"{'**' if j == ans_idx else ''}{['A','B','C','D'][j]}. {opts[j]}{'**' if j == ans_idx else ''}"
                for j in range(min(len(opts), 4))
            )
            st.markdown(opt_text)
            if expl:
                st.caption(f"解析：{expl}")

            bc1, bc2 = st.columns([1, 1])
            with bc1:
                if st.button("編輯", key=f"qe_{qid}", type="secondary"):
                    st.session_state[f"edit_{qid}"] = True
                    st.rerun()
            with bc2:
                if st.button("刪除", key=f"qd_{qid}", type="secondary"):
                    quiz = [x for x in quiz if x.get("id") != qid]
                    save_quiz(quiz)
                    st.success("已刪除")
                    st.rerun()

            # ── 編輯模式 ──
            if st.session_state.get(f"edit_{qid}"):
                with st.form(f"edit_form_{qid}"):
                    eq = st.text_area("題目", value=q["question"], key=f"ef_q_{qid}")
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        e0 = st.text_input("A", value=opts[0] if len(opts) > 0 else "", key=f"ef_0_{qid}")
                        e1 = st.text_input("B", value=opts[1] if len(opts) > 1 else "", key=f"ef_1_{qid}")
                    with ec2:
                        e2 = st.text_input("C", value=opts[2] if len(opts) > 2 else "", key=f"ef_2_{qid}")
                        e3 = st.text_input("D", value=opts[3] if len(opts) > 3 else "", key=f"ef_3_{qid}")
                    ea = st.selectbox("正確答案", ["A", "B", "C", "D"], index=ans_idx, key=f"ef_a_{qid}")
                    ee = st.text_area("解析", value=expl, key=f"ef_e_{qid}")
                    save_btn = st.form_submit_button("儲存", type="primary")

                if save_btn:
                    for x in quiz:
                        if x.get("id") == qid:
                            x["question"] = eq
                            x["options"] = [e0, e1, e2, e3]
                            x["answer"] = ["A", "B", "C", "D"].index(ea)
                            x["explanation"] = ee
                            break
                    save_quiz(quiz)
                    st.session_state.pop(f"edit_{qid}", None)
                    st.success("已更新")
                    st.rerun()

        st.markdown("---", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Sidebar 導航
# ═══════════════════════════════════════════════════════════

def render_sidebar():
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=80)
    st.markdown(f"**{st.session_state.admin_user}**", unsafe_allow_html=True)
    st.caption("管理員")

    st.markdown("---")

    pages = [
        ("dashboard", "📊 數據總覽"),
        ("members", "👥 會員管理"),
        ("orders", "📦 訂單管理"),
        ("discounts", "🎫 折扣碼管理"),
        ("quiz", "📝 題庫管理"),
    ]

    for key, label in pages:
        if st.button(label, use_container_width=True, type="secondary"):
            st.session_state.page = key
            st.rerun()

    st.markdown("---")
    if st.button("登出", use_container_width=True, type="secondary"):
        st.session_state.admin_auth = False
        st.session_state.admin_user = ""
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    init_state()

    if not st.session_state.admin_auth:
        page_login()
        return

    with st.sidebar:
        render_sidebar()

    page = st.session_state.page
    if page == "dashboard":
        page_dashboard()
    elif page == "members":
        page_members()
    elif page == "orders":
        page_orders()
    elif page == "discounts":
        page_discounts()
    elif page == "quiz":
        page_quiz()
    else:
        page_dashboard()


if __name__ == "__main__":
    main()
