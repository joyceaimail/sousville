"""
舒肥底家 SousVille — 遊戲化健康管理系統
========================================
Streamlit + Notion API  |  BMI · TDEE · 熱量赤字 · 每日問答 · 運動紀錄 · XP 商城

啟動方式：
    export NOTION_TOKEN="ntn_..."
    export NOTION_USERS_DB_ID="..."
    export NOTION_DAILY_LOGS_DB_ID="..."
    streamlit run app.py
"""

import streamlit as st
import json
import os
import hashlib
import bisect
import math
import re
from datetime import date, timedelta, datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
import pytz

TAIPEI_TZ = pytz.timezone("Asia/Taipei")

def taiwan_today():
    """回傳台北時區的今天日期 (date)。"""
    return datetime.now(TAIPEI_TZ).date()

import requests as http_requests
from notion_client import Client
import google.generativeai as genai

# ═══════════════════════════════════════════════════════════
#  常數與設定
# ═══════════════════════════════════════════════════════════

def _get_secret(env_key):
    """優先從環境變數讀取（Render），找不到再從 st.secrets 讀取（Streamlit Cloud）。"""
    val = os.environ.get(env_key, "")
    if val:
        return val
    try:
        return st.secrets.get(env_key, "")
    except Exception:
        return ""

# 使用 _get_secret 同時支援 Render 環境變數與 Streamlit Cloud secrets
NOTION_TOKEN      = _get_secret("NOTION_TOKEN")
USERS_DB_ID       = _get_secret("NOTION_USERS_DB_ID")
NOTION_API_URL    = "https://api.notion.com/v1"
DAILY_LOGS_DB_ID  = _get_secret("NOTION_DAILY_LOGS_DB_ID")
EXERCISES_DB_ID   = _get_secret("NOTION_EXERCISES_DB_ID")
GEMINI_API_KEY    = _get_secret("GEMINI_API_KEY")

QUIZ_FILE      = Path(__file__).parent / "quiz_bank.json"
CUSTOM_EX_FILE = Path(__file__).parent / "custom_exercises.json"
AUTH_CACHE_FILE = Path(__file__).parent / ".auth_cache.json"

# ── 品牌圖檔路徑（替換成你自己的檔案即可） ──
LOGO_PATH  = Path(__file__).parent / "assets" / "logo.png"
BANNER_PATH = Path(__file__).parent / "assets" / "banner.png"

INTENSITY_MULT = {"低強度": 0.8, "中強度": 1.0, "高強度": 1.3}

ACTIVITY_LEVELS = {
    "久坐": 1.2,
    "輕度活動": 1.375,
    "中度活動": 1.55,
    "高度活動": 1.725,
    "極高度活動": 1.9,
}

GOAL_MULTIPLIERS = {
    "減重": 0.8,
    "維持體重": 1.0,
    "增肌": 1.1,
    "增重": 1.15,
    "體態雕塑": 1.0,
}

LEVEL_XP = [0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200, 4000]

BENTO_BOXES = {
    "原味蔗香雞腿排（小鳥胃）":  {"cal": 485,  "protein": 25.1, "fiber": 1.7, "fat": 1},
    "原味蔗香雞腿排（輕盈）":  {"cal": 539,  "protein": 26.8, "fiber": 1.9, "fat": 1.1},
    "原味蔗香雞腿排（勻稱）":  {"cal": 630,  "protein": 33.9, "fiber": 2.3, "fat": 1.4},
    "原味蔗香雞腿排（增肌）":  {"cal": 681,  "protein": 35.4, "fiber": 2.5, "fat": 1.5},
    "檸檬香茅雞腿排（小鳥胃）":  {"cal": 538,  "protein": 25.1, "fiber": 1.7, "fat": 1},
    "檸檬香茅雞腿排（輕盈）":  {"cal": 595,  "protein": 26.8, "fiber": 1.9, "fat": 1.1},
    "檸檬香茅雞腿排（勻稱）":  {"cal": 710,  "protein": 33.9, "fiber": 2.3, "fat": 1.4},
    "檸檬香茅雞腿排（增肌）":  {"cal": 762,  "protein": 35.4, "fiber": 2.5, "fat": 1.5},
    "紐奧良雞腿排（小鳥胃）":  {"cal": 541,  "protein": 26.9, "fiber": 1.7, "fat": 1},
    "紐奧良雞腿排（輕盈）":  {"cal": 595,  "protein": 28.5, "fiber": 1.9, "fat": 1.1},
    "紐奧良雞腿排（勻稱）":  {"cal": 714,  "protein": 36.5, "fiber": 2.3, "fat": 1.4},
    "紐奧良雞腿排（增肌）":  {"cal": 765,  "protein": 38.0, "fiber": 2.5, "fat": 1.5},
    "普羅旺斯雞腿排（小鳥胃）":  {"cal": 582,  "protein": 30.3, "fiber": 1.7, "fat": 1},
    "普羅旺斯雞腿排（輕盈）":  {"cal": 625,  "protein": 32.0, "fiber": 1.9, "fat": 1.1},
    "普羅旺斯雞腿排（勻稱）":  {"cal": 759,  "protein": 41.6, "fiber": 2.3, "fat": 1.4},
    "普羅旺斯雞腿排（增肌）":  {"cal": 811,  "protein": 43.1, "fiber": 2.5, "fat": 1.5},
    "海南嫩雞胸（小鳥胃）":  {"cal": 422,  "protein": 35.9, "fiber": 1.7, "fat": 1},
    "海南嫩雞胸（輕盈）":  {"cal": 477,  "protein": 37.6, "fiber": 1.9, "fat": 1.1},
    "海南嫩雞胸（勻稱）":  {"cal": 536,  "protein": 50.1, "fiber": 2.3, "fat": 1.4},
    "海南嫩雞胸（增肌）":  {"cal": 587,  "protein": 51.5, "fiber": 2.5, "fat": 1.5},
    "焙烤松阪豬（小鳥胃）":  {"cal": 536,  "protein": 25.0, "fiber": 1.7, "fat": 1},
    "焙烤松阪豬（輕盈）":  {"cal": 590,  "protein": 26.7, "fiber": 1.9, "fat": 1.1},
    "焙烤松阪豬（勻稱）":  {"cal": 650,  "protein": 30.3, "fiber": 2.3, "fat": 1.4},
    "焙烤松阪豬（增肌）":  {"cal": 701,  "protein": 31.8, "fiber": 2.5, "fat": 1.5},
    "鮮烤鱸魚排（小鳥胃）":  {"cal": 405,  "protein": 31.2, "fiber": 1.7, "fat": 1},
    "鮮烤鱸魚排（輕盈）":  {"cal": 460,  "protein": 32.8, "fiber": 1.9, "fat": 1.1},
    "鮮烤鱸魚排（勻稱）":  {"cal": 482,  "protein": 37.0, "fiber": 2.3, "fat": 1.4},
    "鮮烤鱸魚排（增肌）":  {"cal": 533,  "protein": 38.5, "fiber": 2.5, "fat": 1.5},
    "舒肥牛肉（小鳥胃）":  {"cal": 491,  "protein": 32.6, "fiber": 1.7, "fat": 1},
    "舒肥牛肉（輕盈）":  {"cal": 545,  "protein": 34.2, "fiber": 1.9, "fat": 1.1},
    "舒肥牛肉（勻稱）":  {"cal": 639,  "protein": 45.0, "fiber": 2.3, "fat": 1.4},
    "舒肥牛肉（增肌）":  {"cal": 691,  "protein": 46.5, "fiber": 2.5, "fat": 1.5},
    "照燒豬肉（小鳥胃）":  {"cal": 521,  "protein": 28.9, "fiber": 1.7, "fat": 1},
    "照燒豬肉（輕盈）":  {"cal": 567,  "protein": 28.9, "fiber": 1.9, "fat": 1.1},
    "照燒豬肉（勻稱）":  {"cal": 639,  "protein": 30.6, "fiber": 2.3, "fat": 1.4},
    "照燒豬肉（增肌）":  {"cal": 691,  "protein": 30.6, "fiber": 2.5, "fat": 1.5},
    "台式燒肉（小鳥胃）":  {"cal": 522,  "protein": 29.5, "fiber": 1.7, "fat": 1},
    "台式燒肉（輕盈）":  {"cal": 576,  "protein": 31.2, "fiber": 1.9, "fat": 1.1},
    "台式燒肉（勻稱）":  {"cal": 681,  "protein": 40.7, "fiber": 2.3, "fat": 1.4},
    "台式燒肉（增肌）":  {"cal": 733,  "protein": 42.2, "fiber": 2.5, "fat": 1.5},
}

EXERCISE_MET = {
    "慢走": 2.5, "快走": 4.0, "慢跑": 7.0, "快跑": 10.0,
    "騎自行車（輕鬆）": 6.0, "騎自行車（中強度）": 8.0,
    "游泳": 8.0, "瑜珈": 3.0, "重訓": 5.0, "HIIT": 12.0,
    "跳繩": 11.0, "有氧舞蹈": 7.0, "登山": 6.5,
    "羽球": 5.5, "籃球": 6.5, "桌球": 4.0,
}

PORTION_TARGETS = {
    "蛋白質": 6,
    "全穀根莖": 6,
    "蔬菜":   5,
    "油脂":   5,
    "奶類":   2,
}

PORTION_CAL = {
    "蛋白質":   75,
    "蔬菜":     25,
    "全穀根莖": 140,
    "油脂":     45,
    "奶類":     60,
}

AI_SYSTEM_PROMPT = """你是「舒肥底家 SousVille」的營養助手。你的唯一職責是辨識食物照片並回傳營養數據。

嚴格規則：
1. 只處理「餐盒中的食物」或「包裝上的營養標示表格」兩類圖片。
2. 如果照片不是食物或營養標示（例如：風景、人物、寵物、文具、建築等），必須回傳：
   {"error": "無法識別。請拍攝您的餐盒或營養標示標籤。"}
3. 絕對禁止回答與營養紀錄無關的任何問題或對話。
4. 必須回傳純 JSON，不要包含任何其他文字、markdown 格式或解釋。

輸出格式（食物照片）：
{"food_name": "食物名稱", "calories": 數字, "protein": 數字, "fat": 數字, "carbs": 數字, "fiber": 數字}

輸出格式（營養標示）：
精確提取標示上的數值，格式同上。單位皆為公克(g)。

舒肥底家份量參考（估算餐盒時使用）：
- 小鳥胃份量：約 400-540 kcal
- 輕盈份量：約 460-600 kcal
- 勻稱份量：約 480-760 kcal
- 增肌份量：約 530-810 kcal
- 蛋白質範圍：25-52 g
- 碳水化合物：40-80 g
- 膳食纖維：1.7-2.5 份（換算約 4-6 g）
- 油脂約 1-1.5 茶匙（換算約 5-7 g）

估算時以勻稱份量為基準，根據圖片中食物份量做上下調整。"""


_gemini_configured = False

def process_image(file):
    """使用 Gemini 2.0 Flash 辨識食物照片，回傳營養 JSON。"""
    global _gemini_configured
    if not GEMINI_API_KEY:
        return {"error": "AI 服務尚未設定，請聯絡管理員。"}

    try:
        if not _gemini_configured:
            genai.configure(api_key=GEMINI_API_KEY)
            _gemini_configured = True
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=AI_SYSTEM_PROMPT,
        )

        img_bytes = file.read()
        response = model.generate_content([
            {"mime_type": file.type, "data": img_bytes},
            "請辨識這張照片中的食物或營養標示，回傳 JSON 格式的營養數據。"
            "如果無法辨識為食物，請回傳 {\"error\": \"無法識別。請拍攝您的餐盒或營養標示標籤。\"}",
        ])

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(text)

        if "error" in result:
            return result

        required = ["food_name", "calories", "protein", "fat", "carbs", "fiber"]
        if not all(k in result for k in required):
            return {"error": "AI 回傳格式不完整，請重新拍攝。"}

        for k in ["calories", "protein", "fat", "carbs", "fiber"]:
            result[k] = float(result[k])

        return result

    except Exception:
        return {"error": "AI 分析失敗，請稍後再試。"}


def _load_local_custom_exercises():
    if CUSTOM_EX_FILE.exists():
        try:
            return json.loads(CUSTOM_EX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_local_custom_exercises(data):
    CUSTOM_EX_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ═══════════════════════════════════════════════════════════
#  海豚吉祥物「小舒」
# ═══════════════════════════════════════════════════════════

def _svg_dolphin(mood="happy", size=80):
    """渲染 inline SVG 海豚。mood: happy / neutral / sweat / celebrate"""
    if mood == "happy":
        eye = '<circle cx="78" cy="52" r="4" fill="#1A3C40"/><circle cx="79" cy="51" r="1.5" fill="#fff"/>'
        mouth = '<path d="M 92 62 Q 100 70 92 72" stroke="#1A3C40" stroke-width="2" fill="none" stroke-linecap="round"/>'
        cheek = '<circle cx="70" cy="66" r="5" fill="#FFCDD2" opacity="0.6"/>'
        extra = '<path d="M 58 38 Q 50 30 42 36" stroke="#7ED4D4" stroke-width="2.5" fill="none" stroke-linecap="round"/>'
        anim = 'animation: bounce 2s ease-in-out infinite;'
        blush_color = "#FFCDD2"
    elif mood == "sweat":
        eye = '<circle cx="78" cy="52" r="4" fill="#1A3C40"/><line x1="74" y1="48" x2="82" y2="56" stroke="#1A3C40" stroke-width="1.5" stroke-linecap="round"/>'
        mouth = '<path d="M 88 68 Q 95 64 100 68" stroke="#1A3C40" stroke-width="2" fill="none" stroke-linecap="round"/>'
        cheek = '<circle cx="70" cy="68" r="5" fill="#FFCDD2" opacity="0.8"/>'
        extra = (f'<g style="animation: sweat 0.6s ease-in-out infinite;">'
                 f'<circle cx="92" cy="40" r="3" fill="#7ED4D4" opacity="0.7"/>'
                 f'<circle cx="96" cy="48" r="2.5" fill="#7ED4D4" opacity="0.5"/>'
                 f'<circle cx="90" cy="55" r="2" fill="#7ED4D4" opacity="0.3"/>'
                 f'</g>')
        anim = 'animation: sweat 0.8s ease-in-out infinite;'
    elif mood == "celebrate":
        eye = '<path d="M 74 50 Q 78 46 82 50" stroke="#1A3C40" stroke-width="2.5" fill="none" stroke-linecap="round"/>'
        mouth = '<path d="M 88 62 Q 97 72 105 62" stroke="#1A3C40" stroke-width="2" fill="#FFCDD2" stroke-linecap="round"/>'
        cheek = '<circle cx="68" cy="64" r="6" fill="#FFCDD2" opacity="0.7"/>'
        extra = '<text x="105" y="38" font-size="16" fill="#FFB300">&#9733;</text><text x="40" y="30" font-size="12" fill="#FFB300">&#9733;</text>'
        anim = 'animation: bounce 1.5s ease-in-out infinite;'
    else:  # neutral
        eye = '<circle cx="78" cy="52" r="4" fill="#1A3C40"/><circle cx="79" cy="51" r="1.5" fill="#fff"/>'
        mouth = '<line x1="88" y1="66" x2="98" y2="66" stroke="#1A3C40" stroke-width="2" stroke-linecap="round"/>'
        cheek = '<circle cx="70" cy="66" r="4" fill="#FFCDD2" opacity="0.4"/>'
        extra = ''
        anim = 'animation: float 3s ease-in-out infinite;'

    return f"""
    <div style="text-align:center;">
      <svg width="{size}" height="{size}" viewBox="30 15 90 80" style="{anim}">
        <defs>
          <linearGradient id="dolphin-body" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color:#4DB8B8"/>
            <stop offset="100%" style="stop-color:#158586"/>
          </linearGradient>
          <linearGradient id="dolphin-belly" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" style="stop-color:#E8F4F4"/>
            <stop offset="100%" style="stop-color:#C8E8E8"/>
          </linearGradient>
        </defs>
        <ellipse cx="75" cy="58" rx="30" ry="18" fill="url(#dolphin-body)" stroke="#0E6E6F" stroke-width="0.5"/>
        <ellipse cx="75" cy="65" rx="22" ry="8" fill="url(#dolphin-belly)" opacity="0.7"/>
        <path d="M 48 50 Q 35 38 30 48 Q 35 55 48 52" fill="#4DB8B8" stroke="#0E6E6F" stroke-width="0.5"/>
        <path d="M 95 58 Q 105 48 110 55 Q 105 62 95 60" fill="url(#dolphin-body)" stroke="#0E6E6F" stroke-width="0.5"/>
        <path d="M 105 55 Q 115 50 118 55" stroke="#158586" stroke-width="2" fill="none" stroke-linecap="round"/>
        <path d="M 100 62 Q 108 68 112 65 Q 108 70 100 66" fill="url(#dolphin-body)" stroke="#0E6E6F" stroke-width="0.5"/>
        {cheek}
        {eye}
        {mouth}
        {extra}
      </svg>
    </div>"""


def get_dolphin_mood():
    """根據今日熱量餘額決定小舒的表情。"""
    ud = st.session_state.user_data
    if not ud.get("target"):
        return "neutral"
    cal_in = st.session_state.today_cal_in
    cal_out = st.session_state.today_cal_out
    tdee = ud.get("tdee") or 2000
    balance = (tdee + cal_out) - cal_in

    if cal_out == 0 and cal_in == 0:
        return "neutral"
    if balance > 200:
        return "celebrate"
    elif balance > 0:
        return "happy"
    elif balance == 0:
        return "neutral"
    else:
        return "sweat"


def get_dolphin_message(mood):
    """根據表情回傳小舒的健康建議。"""
    name = st.session_state.user_data.get("name", "")
    messages = {
        "celebrate": f"{name}，今日攝取控制得宜，熱量平衡狀態良好，請繼續維持。",
        "happy": f"{name}，目前攝取量在合理範圍內，建議搭配適度運動以優化體態管理。",
        "neutral": f"{name}，今日尚未記錄飲食，建議開始登錄以掌握每日營養攝取。",
        "sweat": f"{name}，目前攝取已超過建議量，建議增加運動或調整下一餐份量。",
    }
    return messages.get(mood, "")


def get_weight_trend_mood(history):
    if len(history) < 2:
        return "neutral"
    goal = st.session_state.user_data.get("goal", "維持體重")
    delta = history[-1][1] - history[0][1]
    if goal in ("\u6e1b\u91cd", "\u9ad4\u614b\u96d5\u5851"):
        if delta < -0.5:
            return "celebrate"
        elif delta <= 0.5:
            return "happy"
        else:
            return "sweat"
    elif goal in ("\u589e\u808c", "\u589e\u91cd"):
        if delta > 0.5:
            return "celebrate"
        elif delta >= -0.5:
            return "happy"
        else:
            return "sweat"
    else:
        if abs(delta) <= 0.5:
            return "celebrate"
        elif abs(delta) <= 1.5:
            return "happy"
        else:
            return "neutral"


def get_weight_trend_message(mood, delta):
    name = st.session_state.user_data.get("name", "")
    sign = "+" if delta > 0 else ""
    messages = {
        "celebrate": f"\u592a\u68d2\u4e86{name}\uff01\u9ad4\u91cd{sign}{delta:.1f}kg\uff0c\u8d8b\u52e2\u5f88\u68d2\uff01\u5c0f\u8212\u70ba\u4f60\u9a55\u50b2\uff01",
        "happy": f"{name}\uff0c\u9ad4\u91cd\u8b8a\u5316{sign}{delta:.1f}kg\uff0c\u7a69\u5b9a\u9032\u6b65\u4e2d\uff0c\u7e7c\u7e8c\u52a0\u6cb9\uff01",
        "neutral": f"{name}\uff0c\u9ad4\u91cd\u8b8a\u5316{sign}{delta:.1f}kg\uff0c\u5c0f\u8212\u966a\u4f60\u6162\u6162\u4f86\uff01",
        "sweat": f"{name}\uff0c\u9ad4\u91cd{sign}{delta:.1f}kg\uff0c\u5225\u7070\u5fc3\uff0c\u5c0f\u8212\u76f8\u4fe1\u4f60\u53ef\u4ee5\u7684\uff01",
    }
    return messages.get(mood, "")


# ═══════════════════════════════════════════════════════════
#  頁面設定 & 亮色主題
# ═══════════════════════════════════════════════════════════

st.set_page_config(
    page_title="舒肥底家 | SousVille",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": None,
    },
)

(LOGO_PATH.parent).mkdir(exist_ok=True)

st.markdown('<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700;900&family=Quicksand:wght@500;600;700&display=swap" rel="stylesheet">', unsafe_allow_html=True)

st.markdown("""
<style>

:root { lang: "zh-TW";
  --blue:         #1B9D9E;
  --blue-dim:     #158586;
  --blue-deep:    #0E6E6F;
  --blue-light:   #7ED4D4;
  --blue-glow:    rgba(27,157,158,0.22);
  --green:        #1B9D9E;
  --green-dim:    #158586;
  --green-glow:   rgba(27,157,158,0.18);
  --gold:         #FFB300;
  --gold-dim:     #FF8F00;
  --red:          #EF5350;
  --coral:        #FF7043;
  --bg:           #F0F7F8;
  --bg-white:     #FFFFFF;
  --bg-card:      #FFFFFF;
  --bg-card-alt:  #F5FAFB;
  --bg-sidebar:   linear-gradient(180deg, #E8F4F4 0%, #FFFFFF 40%);
  --text:         #1A3C40;
  --text-dim:     #6B9DA0;
  --border:       rgba(27,157,158,0.12);
  --shadow:       0 4px 20px rgba(27,157,158,0.08);
  --shadow-hover: 0 6px 28px rgba(27,157,158,0.15);
}

[data-testid="stAppViewContainer"] {
  background: var(--bg);
  color: var(--text);
}
[data-testid="stHeader"] {
  background: var(--bg-white) !important;
  border-bottom: 1px solid var(--border);
}
[data-testid="stSidebar"] {
  background: var(--bg-sidebar) !important;
  border-right: 2px solid rgba(27,157,158,0.08) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }

h1,h2,h3,h4 {
  font-family: 'Noto Sans TC', sans-serif !important;
  color: var(--text) !important;
  letter-spacing: 0.5px;
}

.card {
  background: var(--bg-card);
  border-radius: 18px;
  padding: 24px;
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  transition: box-shadow .3s, transform .2s;
}
.card:hover {
  box-shadow: var(--shadow-hover);
  transform: translateY(-2px);
}

.gauge-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.gauge-svg { filter: drop-shadow(0 3px 8px var(--blue-glow)); }
.gauge-value { font-size: 1.45rem; font-weight: 900; fill: var(--text); font-family: 'Quicksand', sans-serif; }
.gauge-label { font-size: 0.78rem; fill: var(--text-dim); text-transform: uppercase; letter-spacing: 2px; font-family: 'Quicksand', sans-serif; }

.xp-track { background: rgba(27,157,158,0.1); border-radius: 12px; height: 14px; overflow: hidden; }
.xp-fill { height: 100%; border-radius: 12px; background: linear-gradient(90deg, var(--blue), var(--blue-light)); transition: width .5s ease; }

.level-ring {
  width: 64px; height: 64px; border-radius: 50%;
  background: linear-gradient(135deg, var(--blue), var(--blue-deep));
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 900; font-size: 1.4rem; color: #fff;
  box-shadow: 0 3px 14px var(--blue-glow); border: 3px solid var(--blue-light);
  font-family: 'Quicksand', sans-serif;
}

.streak-badge {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--bg-card);
  padding: 6px 18px; border-radius: 24px; font-weight: 900; font-size: 1rem; color: var(--coral);
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  font-family: 'Quicksand', sans-serif;
}

.stTabs [data-baseweb="tab-list"] { gap: 8px; background: transparent; }
.stTabs [data-baseweb="tab"] {
  background: var(--bg-card); color: var(--text-dim); border-radius: 14px;
  padding: 12px 24px; font-weight: 700; font-size: 0.95rem;
  border: 1px solid var(--border); box-shadow: var(--shadow); transition: all .3s;
  font-family: 'Noto Sans TC', sans-serif;
}
.stTabs [data-baseweb="tab"]:hover { background: var(--bg-card-alt); color: var(--text); border-color: var(--blue-light); transform: translateY(-1px); }
.stTabs [aria-selected="true"] {
  background: linear-gradient(135deg, var(--blue), var(--blue-deep)) !important;
  color: #fff !important; border-color: var(--blue) !important; box-shadow: 0 3px 16px var(--blue-glow);
}
.stTabs [data-baseweb="tab-highlight"] { display: none; }
.stTabs [data-baseweb="tab-content"] { background: transparent; }

.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, var(--blue), var(--blue-deep)) !important;
  border: none !important; border-radius: 14px !important;
  font-weight: 700 !important; color: #fff !important;
  box-shadow: 6px 6px 12px #d1d9db, -6px -6px 12px #ffffff !important;
  font-family: 'Noto Sans TC', sans-serif !important;
  height: 62px !important;
  font-size: 1rem !important;
}
.stButton > button[kind="primary"]:hover { box-shadow: 4px 4px 8px #d1d9db, -4px -4px 8px #ffffff, 0 0 20px var(--blue-glow) !important; }
.stButton > button[kind="secondary"] {
  border-radius: 14px !important; font-weight: 600 !important;
  border: 1px solid var(--border) !important; color: var(--text) !important; background: var(--bg-card) !important;
  height: 62px !important;
  font-family: 'Noto Sans TC', sans-serif !important;
  box-shadow: 4px 4px 8px #d1d9db, -4px -4px 8px #ffffff !important;
}
.stButton > button[kind="secondary"]:hover { border-color: var(--blue-light) !important; background: var(--bg-card-alt) !important; }

.stSelectbox label, .stTextInput label, .stNumberInput label { color: var(--text-dim) !important; font-family: 'Noto Sans TC', sans-serif !important; }
.stSlider > div > div > div { background: linear-gradient(90deg, var(--blue), var(--blue-light)) !important; border-radius: 12px !important; }
.stSlider [data-baseweb="slider"] [class*="handle"] {
  background: var(--blue) !important; border: 3px solid #fff !important;
  box-shadow: 0 0 0 2px var(--blue), 0 3px 10px var(--blue-glow) !important;
}
.stProgress > div > div > div { background: linear-gradient(90deg, var(--blue), var(--blue-light)) !important; border-radius: 12px !important; }

.coupon-box {
  background: linear-gradient(135deg, #E8F4F4, #FFF8E1);
  border: 3px solid var(--gold); border-radius: 24px; padding: 36px;
  text-align: center; animation: pop .45s ease; box-shadow: 0 4px 24px rgba(255,179,0,0.2);
}

.ai-btn {
  background: linear-gradient(135deg, var(--green), var(--green-dim)); color: #fff;
  font-weight: 900; font-size: 1.05rem; padding: 14px 28px; border-radius: 14px;
  border: 2px dashed var(--gold); cursor: pointer; transition: all .3s; text-align: center;
  font-family: 'Noto Sans TC', sans-serif;
}
.ai-btn:hover { box-shadow: 0 4px 20px var(--green-glow); transform: translateY(-2px); }

.quiz-card {
  background: var(--bg-card); border-radius: 18px; padding: 32px;
  border: 1px solid var(--border); box-shadow: var(--shadow);
}

/* ── Game Map ── */
.game-map { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 20px 0; }
.game-row { display: flex; align-items: center; gap: 0; }
.game-node {
  width: 56px; height: 56px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; font-weight: 900; font-size: 1.1rem; color: #fff;
  cursor: default; transition: transform .2s, box-shadow .2s; position: relative;
  font-family: 'Quicksand', sans-serif;
}
.game-node.completed {
  background: #43A047; box-shadow: 0 3px 12px rgba(67,160,71,0.35); border: 3px solid #66BB6A;
}
.game-node.current {
  background: var(--gold); box-shadow: 0 3px 16px rgba(255,179,0,0.5);
  border: 3px solid #FFCA28; animation: pulse-glow 1.8s ease-in-out infinite;
}
.game-node.locked {
  background: #ccc; box-shadow: 0 2px 6px rgba(0,0,0,0.1); border: 3px solid #bbb; opacity: 0.6;
}
.game-node.boss { width: 64px; height: 64px; font-size: 1.3rem; }
.game-connector { width: 40px; height: 4px; border-radius: 2px; }
.game-connector.completed { background: #43A047; }
.game-connector.locked { background: #ddd; }
.game-chapter-label {
  text-align: center; font-size: .95rem; font-weight: 800; color: var(--text-dim);
  margin: 8px 0 4px; font-family: 'Noto Sans TC', sans-serif;
}
.game-hearts-bar {
  display: flex; align-items: center; gap: 6px; justify-content: center;
  font-size: 1.3rem; padding: 8px 0;
}
.game-hearts-bar .heart-full { color: #EF5350; }
.game-hearts-bar .heart-empty { color: #ddd; }
.game-progress-bar { display: flex; align-items: center; gap: 8px; justify-content: center; margin: 4px 0; }
.game-progress-track { width: 200px; height: 8px; background: rgba(27,157,158,0.12); border-radius: 4px; overflow: hidden; }
.game-progress-fill { height: 100%; background: linear-gradient(90deg, var(--blue), var(--blue-light)); border-radius: 4px; transition: width .5s ease; }
.game-result-box {
  text-align: center; padding: 40px 24px; border-radius: 24px;
  animation: pop .5s ease;
}
.game-result-box.success { background: linear-gradient(135deg, #E8F5E9, #FFF8E1); border: 2px solid #43A047; }
.game-result-box.fail { background: linear-gradient(135deg, #FFEBEE, #FFF3E0); border: 2px solid #EF5350; }

@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 3px 16px rgba(255,179,0,0.5); transform: scale(1); }
  50% { box-shadow: 0 3px 28px rgba(255,179,0,0.8); transform: scale(1.08); }
}

.brand-banner { width: 100%; border-radius: 0 0 18px 18px; overflow: hidden; margin-bottom: 8px; }
.brand-banner img { width: 100%; height: auto; display: block; border-radius: 0 0 18px 18px; }

[data-testid="stSidebar"] ::-webkit-scrollbar { width: 4px; }
[data-testid="stSidebar"] ::-webkit-scrollbar-thumb { background: rgba(27,157,158,0.2); border-radius: 4px; }

.advisor-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border-radius: 18px;
  padding: 20px 24px;
  box-shadow: var(--shadow);
  border: 1px solid var(--border);
  margin: 12px auto;
  max-width: 480px;
}
.advisor-card-text {
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--text);
  line-height: 1.6;
  font-family: 'Noto Sans TC', sans-serif;
}

.dolphin-progress-icon {
  display: inline-block;
  margin-right: 4px;
  vertical-align: middle;
}

@keyframes pop { 0% { transform: scale(.5); opacity:0; } 70% { transform: scale(1.04); } 100% { transform: scale(1); opacity:1; } }
@keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes bounce { 0%, 100% { transform: translateY(0) scaleY(1); } 30% { transform: translateY(-10px) scaleY(1.05); } 60% { transform: translateY(-4px) scaleY(0.97); } }
@keyframes sweat { 0%, 100% { transform: translateX(0); } 25% { transform: translateX(-2px); } 75% { transform: translateX(2px); } }

/* ── 隱藏 Streamlit 預設 UI ── */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
footer:after {
  content: '© 2026 舒肥底家 SousVille';
  visibility: visible;
  display: block;
  text-align: center;
  padding: 10px;
  color: var(--text-dim);
  font-size: 0.8rem;
  font-family: 'Noto Sans TC', sans-serif;
}

/* ── 手機 RWD ── */
@media only screen and (max-width: 768px) {
  .stButton > button {
    min-height: 52px !important;
    font-size: 1.05rem !important;
    padding: 14px 24px !important;
  }
  .stButton > button[kind="primary"] {
    min-height: 56px !important;
    padding: 16px 28px !important;
    font-size: 1.1rem !important;
  }
  .stNumberInput input, .stTextInput input, .stSelectbox select {
    font-size: 18px !important;
    min-height: 48px !important;
  }
  .stNumberInput label, .stTextInput label, .stSelectbox label {
    font-size: 16px !important;
  }
  .stNumberInput div[data-testid="stNumberInputStepControls"] button {
    min-width: 40px !important;
    min-height: 40px !important;
    font-size: 20px !important;
  }
  .stRadio label {
    font-size: 18px !important;
    padding: 10px 16px !important;
  }
  [data-testid="stCameraInput"] label {
    font-size: 18px !important;
    padding: 16px !important;
  }
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Session State
# ═══════════════════════════════════════════════════════════

def init_session_state():
    defaults = {
        "authenticated": False,
        "user_page_id": None,
        "user_data": {},
        "current_date": str(taiwan_today()),
        "today_cal_in": 0,
        "today_cal_out": 0,
        "today_meals": [],
        "today_exercises": [],
        "total_xp": 0,
        "daily_quiz_done": False,
        "coupon_unlocked": False,
        "today_log_id": None,
        "today_quiz_xp": 0,
        "profile_complete": False,
        "custom_exercises": _load_local_custom_exercises(),
        "streak": 0,
        "portions": {"蛋白質": 0, "全穀根莖": 0, "蔬菜": 0, "油脂": 0, "奶類": 0},
        "game_hearts": 5,
        "game_progress": {},
        "current_level": None,
        "level_q_idx": 0,
        "level_correct": 0,
        "hearts_regen_time": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def check_daily_reset():
    today_str = str(taiwan_today())
    if st.session_state.current_date != today_str:
        st.session_state.current_date = today_str
        st.session_state.today_cal_in = 0
        st.session_state.today_cal_out = 0
        st.session_state.today_meals = []
        st.session_state.today_exercises = []
        st.session_state.daily_quiz_done = False
        st.session_state.today_log_id = None
        st.session_state.today_quiz_xp = 0
        st.session_state.coupon_unlocked = False
        st.session_state.current_level = None
        st.session_state.level_q_idx = 0
        st.session_state.level_correct = 0
        st.session_state.portions = {"蛋白質": 0, "全穀根莖": 0, "蔬菜": 0, "油脂": 0, "奶類": 0}
        if st.session_state.get("user_page_id"):
            try:
                notion = get_notion()
                get_or_create_daily_log(notion, st.session_state.user_page_id, today_str)
            except Exception:
                pass


def get_client_ip():
    """從 headers 取得訪客真實 IP（支援 Cloudflare + Render 反向代理）。"""
    try:
        headers = st.context.headers
        # Cloudflare 代理會帶 CF-Connecting-IP
        ip = headers.get("CF-Connecting-IP", "").strip()
        if ip:
            return ip
        # Render 反向代理
        ip = headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if ip:
            return ip
        ip = headers.get("X-Real-IP", "").strip()
        if ip:
            return ip
    except Exception:
        pass
    return ""


def check_ip_change():
    """偵測 IP 變化，不同時自動登出。"""
    if not st.session_state.authenticated:
        return
    login_ip = st.session_state.get("login_ip", "")
    current_ip = get_client_ip()
    if not login_ip or not current_ip:
        return
    if current_ip != login_ip:
        _clear_auth_cache()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.warning("偵測到不同網路環境，已自動登出。請重新登入。")
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  Notion 工具函數（相容 notion-client v2 / v3）
# ═══════════════════════════════════════════════════════════

_notion_instance = None

def get_notion():
    global _notion_instance
    if _notion_instance is not None:
        return _notion_instance
    if not NOTION_TOKEN:
        st.error("NOTION_TOKEN 尚未設定")
        st.stop()
    _notion_instance = Client(auth=NOTION_TOKEN)
    return _notion_instance


def _query_db(notion, database_id, **kwargs):
    """查詢 Notion 資料庫，相容 notion-client v2 / v3。"""
    try:
        return notion.databases.query(database_id=database_id, **kwargs)
    except (AttributeError, Exception):
        pass
    try:
        return notion.request(path=f"databases/{database_id}/query",
                               method="POST", body=kwargs)
    except Exception:
        pass
    import httpx
    resp = httpx.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json=kwargs,
    )
    return resp.json()


def _notion_debug_msg(err):
    """從 Notion API 錯誤中提取完整 response.text 以供除錯。"""
    msg = str(err)
    resp = getattr(err, "response", None)
    if resp is not None:
        body = getattr(resp, "text", None) or ""
        if body:
            msg += f"\n\n📋 Notion 回傳：\n```\n{body}\n```"
    return msg


def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _verify_db_id(db_id, label="DB"):
    clean = db_id.replace("-", "").strip()
    if len(clean) != 32:
        st.error(f"⚠️ {label} ID 長度不正確：{len(clean)} 字元（應為 32）。原始值：`{db_id}`")
        st.stop()
    return db_id.strip()


def find_user(notion, email):
    db_id = _verify_db_id(USERS_DB_ID, "Users")
    try:
        q = _query_db(notion, db_id, filter={
            "property": "電子郵件", "email": {"equals": email},
        })
        results = q.get("results", [])
        return results[0] if results else None
    except Exception as e:
        st.error(_notion_debug_msg(e))
        return None


def deduplicate_users(notion, email):
    """查 Notion 中同信箱的重複使用者，保留最新一筆，其餘歸檔刪除。"""
    db_id = _verify_db_id(USERS_DB_ID, "Users")
    try:
        q = _query_db(notion, db_id, filter={
            "property": "電子郵件", "email": {"equals": email}},
            sorts=[{"timestamp": "created_time", "direction": "descending"}],
        )
        dupes = q.get("results", [])
    except Exception:
        return
    if len(dupes) <= 1:
        return
    for page in dupes[1:]:
        try:
            notion.pages.update(page_id=page["id"], properties={"archived": {"checkbox": True}})
        except Exception:
            pass


def _save_auth_cache(email, page_id):
    AUTH_CACHE_FILE.write_text(
        json.dumps({"email": email, "page_id": page_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_auth_cache():
    if AUTH_CACHE_FILE.exists():
        try:
            data = json.loads(AUTH_CACHE_FILE.read_text(encoding="utf-8"))
            return data.get("email"), data.get("page_id")
        except (json.JSONDecodeError, OSError):
            pass
    return None, None


def _clear_auth_cache():
    if AUTH_CACHE_FILE.exists():
        AUTH_CACHE_FILE.unlink()


def create_user(notion, name, phone, email):
    db_id = _verify_db_id(USERS_DB_ID, "Users")

    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "姓名":       {"title": [{"text": {"content": name}}]},
            "電子郵件":    {"email": email},
            "總經驗值":    {"number": 0},
            "等級":       {"number": 1},
            "優惠券已解鎖":  {"checkbox": False},
        },
    }

    try:
        resp = http_requests.post(
            f"{NOTION_API_URL}/pages",
            headers=_notion_headers(),
            json=payload,
        )

        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"建立帳號失敗（HTTP {resp.status_code}），請確認 Email 格式正確後重試。")
            return None
    except Exception as e:
        st.error(f"建立使用者時發生網路錯誤：{e}")
        return None


def update_user_profile(notion, page_id, props):
    try:
        notion.pages.update(page_id=page_id, properties=props)
    except Exception as e:
        st.error(_notion_debug_msg(e))


def get_or_create_daily_log(notion, user_page_id, date_str):
    if (st.session_state.get("today_log_id")
            and st.session_state.get("current_date") == date_str):
        return None
    try:
        results = _query_db(notion, DAILY_LOGS_DB_ID, filter={"and": [
            {"property": "使用者", "relation": {"contains": user_page_id}},
            {"property": "Date", "date": {"equals": date_str}},
        ]}).get("results", [])
    except Exception as e:
        st.error(_notion_debug_msg(e))
        return None

    if results:
        log = results[0]
        p = log["properties"]
        st.session_state.today_cal_in  = p.get("攝取卡路里", {}).get("number", 0) or 0
        st.session_state.today_cal_out = p.get("消耗卡路里", {}).get("number", 0) or 0
        st.session_state.today_quiz_xp = p.get("獲得經驗值", {}).get("number", 0) or 0
        st.session_state.daily_quiz_done = p.get("問答完成", {}).get("checkbox", False) or False
        st.session_state.today_log_id = log["id"]

        meal_text = p.get("飲食紀錄", {}).get("rich_text", [])
        if meal_text and meal_text[0].get("plain_text", "").strip():
            st.session_state.today_meals = [m.strip() for m in meal_text[0]["plain_text"].split(";") if m.strip()]

        ex_text = p.get("運動紀錄", {}).get("rich_text", [])
        if ex_text and ex_text[0].get("plain_text", "").strip():
            st.session_state.today_exercises = [e.strip() for e in ex_text[0]["plain_text"].split(";") if e.strip()]

        st.session_state.portions = {
            "\u86cb\u767d\u8cea": p.get("\u86cb\u767d\u8cea\u4efd\u6578", {}).get("number", 0) or 0,
            "\u852c\u83dc": p.get("\u852c\u83dc\u4efd\u6578", {}).get("number", 0) or 0,
            "\u6cb9\u8102": p.get("\u6cb9\u8102\u4efd\u6578", {}).get("number", 0) or 0,
            "\u5976\u985e": p.get("\u5976\u985e\u4efd\u6578", {}).get("number", 0) or 0,
        }

        return log

    try:
        new_log = notion.pages.create(
            parent={"database_id": DAILY_LOGS_DB_ID},
            properties={
                "Date":       {"date": {"start": date_str}},
                "使用者":     {"relation": [{"id": user_page_id}]},
                "攝取卡路里":  {"number": 0},
                "消耗卡路里":  {"number": 0},
                "獲得經驗值":  {"number": 0},
                "問答完成":    {"checkbox": False},
                "飲食紀錄":    {"rich_text": [{"text": {"content": ""}}]},
                "運動紀錄":    {"rich_text": [{"text": {"content": ""}}]},
                "\u86cb\u767d\u8cea\u4efd\u6578":  {"number": 0},
                "\u852c\u83dc\u4efd\u6578":    {"number": 0},
                "\u6cb9\u8102\u4efd\u6578":    {"number": 0},
                "\u5976\u985e\u4efd\u6578":    {"number": 0},
                "\u7b54\u984c\u5167\u5bb9":    {"rich_text": [{"text": {"content": ""}}]},
            },
        )
    except Exception as e:
        st.error(_notion_debug_msg(e))
        return None
    st.session_state.today_cal_in = 0
    st.session_state.today_cal_out = 0
    st.session_state.today_quiz_xp = 0
    st.session_state.daily_quiz_done = False
    st.session_state.today_log_id = new_log["id"]
    return new_log


def patch_daily_log(notion, log_id, props):
    if not log_id:
        return
    try:
        notion.pages.update(page_id=log_id, properties=props)
    except Exception as e:
        st.error(_notion_debug_msg(e))


def query_weight_history(notion, user_page_id, days=30):
    if "weight_history" in st.session_state:
        return st.session_state.weight_history
    start = (taiwan_today() - timedelta(days=days - 1)).isoformat()
    end = taiwan_today().isoformat()
    entries = []
    try:
        results = _query_db(notion, DAILY_LOGS_DB_ID, filter={"and": [
            {"property": "\u4f7f\u7528\u8005", "relation": {"contains": user_page_id}},
            {"property": "Date", "date": {"on_or_before": end, "on_or_after": start}},
        ]})
        for page in results.get("results", []):
            d = page["properties"]["Date"]["date"]["start"]
            props = page.get("properties", {})
            w = None
            if "\u9ad4\u91cd" in props and props["體重"].get("number") is not None:
                w = props["體重"]["number"]
            if w is not None:
                entries.append((d, w))
    except Exception:
        pass
    entries.sort(key=lambda x: x[0])
    st.session_state.weight_history = entries
    return entries


def sync_meal_to_notion(notion, log_id, meal_name, calories):
    if not log_id:
        return
    parts = st.session_state.today_meals + [meal_name]
    new_text = "; ".join(parts)[:2000]
    por = st.session_state.portions
    patch_daily_log(notion, log_id, {
        "攝取卡路里":   {"number": st.session_state.today_cal_in},
        "飲食紀錄":     {"rich_text": [{"text": {"content": new_text}}]},
        "\u86cb\u767d\u8cea\u4efd\u6578":  {"number": por.get("\u86cb\u767d\u8cea", 0)},
        "\u852c\u83dc\u4efd\u6578":    {"number": por.get("\u852c\u83dc", 0)},
        "\u6cb9\u8102\u4efd\u6578":    {"number": por.get("\u6cb9\u8102", 0)},
        "\u5976\u985e\u4efd\u6578":    {"number": por.get("\u5976\u985e", 0)},
    })


def sync_exercise_to_notion(notion, log_id, exercise_name, calories):
    if not log_id:
        return
    parts = st.session_state.today_exercises + [exercise_name]
    new_text = "; ".join(parts)[:2000]
    patch_daily_log(notion, log_id, {
        "消耗卡路里": {"number": st.session_state.today_cal_out},
        "運動紀錄":  {"rich_text": [{"text": {"content": new_text}}]},
    })


def add_user_xp(notion, user_page_id, amount):
    new_xp = st.session_state.total_xp + amount
    st.session_state.total_xp = new_xp
    new_level = get_level(new_xp)
    update_user_profile(notion, user_page_id, {
        "總經驗值": {"number": new_xp},
        "等級":   {"number": new_level},
    })
    if new_xp >= 500 and not st.session_state.coupon_unlocked:
        st.session_state.coupon_unlocked = True
        update_user_profile(notion, user_page_id, {"優惠券已解鎖": {"checkbox": True}})
        return True
    return False


def calc_streak(notion, user_page_id):
    if "streak" in st.session_state and "streak_date" in st.session_state:
        if st.session_state.streak_date == str(taiwan_today()):
            return
    start = (taiwan_today() - timedelta(days=60)).isoformat()
    try:
        results = _query_db(notion, DAILY_LOGS_DB_ID, filter={"and": [
            {"property": "使用者", "relation": {"contains": user_page_id}},
            {"property": "Date", "date": {"on_or_after": start}},
        ]}).get("results", [])
    except Exception:
        st.session_state.streak = 0
        st.session_state.streak_date = str(taiwan_today())
        return

    date_set = set()
    for page in results:
        d = page["properties"]["Date"]["date"]["start"]
        p = page["properties"]
        has = (
            (p.get("攝取卡路里", {}).get("number", 0) or 0) > 0
            or (p.get("消耗卡路里", {}).get("number", 0) or 0) > 0
        )
        if has:
            date_set.add(d)

    streak = 0
    check = taiwan_today() - timedelta(days=1)
    for _ in range(60):
        if str(check) in date_set:
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    st.session_state.streak = streak
    st.session_state.streak_date = str(taiwan_today())


# ─── 自訂運動 ───

def merge_exercises():
    return {**EXERCISE_MET, **st.session_state.custom_exercises}


def add_custom_exercise(name, met, category="自訂"):
    st.session_state.custom_exercises[name] = met
    _save_local_custom_exercises(st.session_state.custom_exercises)
    if EXERCISES_DB_ID:
        try:
            notion = get_notion()
            notion.pages.create(
                parent={"database_id": EXERCISES_DB_ID},
                properties={
                    "Name": {"title": [{"text": {"content": name}}]},
                    "MET":  {"number": met},
                    "Category": {"select": {"name": category}},
                },
            )
        except Exception:
            pass


def delete_custom_exercise(name):
    st.session_state.custom_exercises.pop(name, None)
    _save_local_custom_exercises(st.session_state.custom_exercises)


# ═══════════════════════════════════════════════════════════
#  計算函數
# ═══════════════════════════════════════════════════════════

def calc_bmi(w, h):
    return round(w / (h / 100) ** 2, 1)

def calc_bmr(w, h, age, gender):
    if gender in ("男", "男性", "其他"):
        return 10 * w + 6.25 * h - 5 * age + 5
    return 10 * w + 6.25 * h - 5 * age - 161

def calc_tdee(bmr, mult):
    return round(bmr * mult)

def calc_target(tdee, mult):
    return round(tdee * mult)

def calc_exercise_cal(met, weight, duration, intensity):
    return round(met * weight * (duration / 60) * INTENSITY_MULT.get(intensity, 1.0))

def get_level(xp):
    return bisect.bisect_right(LEVEL_XP, xp)

def get_next_level_xp(xp):
    lv = get_level(xp)
    if lv < len(LEVEL_XP):
        return LEVEL_XP[lv - 1], LEVEL_XP[lv]
    return LEVEL_XP[-1], LEVEL_XP[-1] + 1000

def bmi_category(bmi):
    if bmi < 18.5: return "體重過輕"
    if bmi < 24:    return "正常"
    if bmi < 27:    return "過重"
    if bmi < 30:    return "輕度肥胖"
    return "中度以上肥胖"


# ═══════════════════════════════════════════════════════════
#  UI 元件：Logo / Banner
# ═══════════════════════════════════════════════════════════

def _show_logo(center=False, height=120):
    """用 st.image 顯示 Logo，找不到檔案則提醒。"""
    if LOGO_PATH.exists():
        if center:
            st.markdown("<div style='text-align:center;'>", unsafe_allow_html=True)
            st.image(str(LOGO_PATH), width=height)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.image(str(LOGO_PATH), width=height)
    else:
        st.warning("⚠️ 請在 assets/ 資料夾放入 logo.png")


def _show_banner():
    """用 st.image 顯示 Banner。"""
    if BANNER_PATH.exists():
        st.image(str(BANNER_PATH), use_container_width=True)


# ═══════════════════════════════════════════════════════════
#  UI 元件：圓形儀表 (SVG)
# ═══════════════════════════════════════════════════════════

def _svg_circle_gauge(value, max_val, label, unit, color, size=130, stroke=9):
    r = (size - stroke) / 2
    circ = 2 * math.pi * r
    pct = min(value / max(max_val, 1), 1.0)
    offset = circ * (1 - pct)
    cx = size / 2
    cy = size / 2
    return f"""
    <div class="gauge-wrap">
      <svg width="{size}" height="{size}" class="gauge-svg">
        <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(0,0,0,0.06)"
                stroke-width="{stroke}" stroke-linecap="round"/>
        <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}"
                stroke-width="{stroke}" stroke-linecap="round"
                stroke-dasharray="{circ}" stroke-dashoffset="{offset}"
                transform="rotate(-90 {cx} {cy})" style="transition: stroke-dashoffset 1s ease;"/>
        <text x="{cx}" y="{cy - 4}" text-anchor="middle" class="gauge-value"
              font-size="{size // 5}">{value}</text>
        <text x="{cx}" y="{cy + 16}" text-anchor="middle" class="gauge-label"
              font-size="11">{unit}</text>
      </svg>
      <div style="font-weight:700; font-size:.85rem; color:var(--text-dim); margin-top:2px;">
        {label}
      </div>
    </div>"""


def _svg_circle_gauge_pct(pct, label, unit, color="#1B9D9E", size=150, stroke=10):
    """圓形儀表，顯示百分比（可超過 100%）。"""
    display = min(pct, 999)
    r = (size - stroke) / 2
    circ = 2 * math.pi * r
    fill_pct = min(pct / 100, 1.0)
    offset = circ * (1 - fill_pct)
    cx = size / 2
    cy = size / 2
    pct_text = f"{pct:.0f}%"
    return f"""
    <div class="gauge-wrap">
      <svg width="{size}" height="{size}" class="gauge-svg">
        <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="rgba(27,157,158,0.06)"
                stroke-width="{stroke}" stroke-linecap="round"/>
        <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}"
                stroke-width="{stroke}" stroke-linecap="round"
                stroke-dasharray="{circ}" stroke-dashoffset="{offset}"
                transform="rotate(-90 {cx} {cy})" style="transition: stroke-dashoffset 1s ease;"/>
        <text x="{cx}" y="{cy - 2}" text-anchor="middle" class="gauge-value"
              font-size="{size // 6}">{pct_text}</text>
        <text x="{cx}" y="{cy + 14}" text-anchor="middle" class="gauge-label"
              font-size="10">{unit}</text>
      </svg>
      <div style="font-weight:700; font-size:.85rem; color:var(--text-dim); margin-top:2px; font-family:'Noto Sans TC',sans-serif;">
        {label}
      </div>
    </div>"""


def _render_weight_chart(history, width=700, height=260):
    if not history:
        return '<p style="color:var(--text-dim); text-align:center;">尚無體重紀錄</p>'
    dates = [h[0][5:] for h in history]
    weights = [h[1] for h in history]
    pad = {"t": 20, "r": 20, "b": 36, "l": 46}
    cw = width - pad["l"] - pad["r"]
    ch = height - pad["t"] - pad["b"]
    w_min, w_max = min(weights) - 0.5, max(weights) + 0.5
    if w_max - w_min < 2:
        mid = (w_max + w_min) / 2
        w_min, w_max = mid - 1, mid + 1
    n = len(weights)

    def tx(i):
        return pad["l"] + (i / max(n - 1, 1)) * cw

    def ty(w):
        return pad["t"] + ch - ((w - w_min) / (w_max - w_min)) * ch

    pts = " ".join(f"{tx(i)},{ty(w)}" for i, w in enumerate(weights))
    fill_pts = (f"{tx(0)},{ty(weights[0])} {pts} "
                f"{tx(n-1)},{ty(weights[-1])} {tx(n-1)},{pad['t']+ch} {tx(0)},{pad['t']+ch}")

    grid_lines = ""
    steps = 4
    for i in range(steps + 1):
        gv = w_min + (w_max - w_min) * i / steps
        gy = ty(gv)
        grid_lines += (f'<line x1="{pad["l"]}" y1="{gy}" x2="{width-pad["r"]}" y2="{gy}" '
                      f'stroke="rgba(0,0,0,0.06)" stroke-width="1"/>')
        grid_lines += (f'<text x="{pad["l"]-6}" y="{gy+4}" text-anchor="end" '
                       f'fill="var(--text-dim)" font-size="11">{gv:.1f}</text>')

    x_labels = ""
    label_step = max(1, n // 8)
    for i in range(0, n, label_step):
        x_labels += f'<text x="{tx(i)}" y="{height-8}" text-anchor="middle" fill="var(--text-dim)" font-size="10">{dates[i]}</text>'
    if (n - 1) % label_step != 0:
        x_labels += f'<text x="{tx(n-1)}" y="{height-8}" text-anchor="middle" fill="var(--text-dim)" font-size="10">{dates[-1]}</text>'

    dots = ""
    for i, w in enumerate(weights):
        dots += f'<circle cx="{tx(i)}" cy="{ty(w)}" r="4" fill="#1B9D9E" stroke="#fff" stroke-width="2"/>'
        dots += (f'<text x="{tx(i)}" y="{ty(w)-10}" text-anchor="middle" '
                 f'fill="var(--text)" font-size="10" font-weight="700">{w:.1f}</text>')

    svg = (f'<svg viewBox="0 0 {width} {height}" style="width:100%;max-width:{width}px;'
           f"font-family:'Noto Sans TC',sans-serif;\">"
           f'<defs><linearGradient id="wf" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0%" stop-color="#1B9D9E" stop-opacity="0.25"/>'
           f'<stop offset="100%" stop-color="#1B9D9E" stop-opacity="0.02"/>'
           f'</linearGradient></defs>'
           f'{grid_lines}{x_labels}'
           f'<polygon points="{fill_pts}" fill="url(#wf)"/>'
           f'<polyline points="{pts}" fill="none" stroke="#1B9D9E" stroke-width="2.5" '
           f'stroke-linecap="round" stroke-linejoin="round"/>'
           f'{dots}</svg>')
    return f'<div style="overflow-x:auto;">{svg}</div>'


def render_top_dashboard():
    _show_logo(center=True, height=52)
    ud = st.session_state.user_data
    if not st.session_state.profile_complete:
        return

    tdee = ud.get("tdee", 2000)
    target = ud.get("target", tdee)
    cal_in = st.session_state.today_cal_in
    cal_out = st.session_state.today_cal_out
    balance = (tdee + cal_out) - cal_in

    mood = get_dolphin_mood()
    msg = get_dolphin_message(mood)
    st.markdown(f"""
    <div class="advisor-card">
      <div>{_svg_dolphin(mood, size=70)}</div>
      <div class="advisor-card-text">
        <div style="font-size:.8rem; color:var(--text-dim); margin-bottom:4px;">小舒健康建議</div>
        <div style="font-size:.92rem; color:var(--text); line-height:1.5;">{msg}</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # ── 三個核心指標圓圈 ──
    intake_pct = round(cal_in / max(target, 1) * 100, 1)
    exercise_pct = round(cal_out / max(target, 1) * 100, 1)
    intake_color = "#EF5350" if intake_pct >= 100 else "#1B9D9E"

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(_svg_circle_gauge_pct(intake_pct, "已攝取", "攝取率", intake_color, size=140, stroke=10),
                    unsafe_allow_html=True)
        st.markdown(f'<p style="text-align:center; color:var(--text-dim); font-size:.8rem; '
                    f'margin:-4px 0 0; font-family:Noto Sans TC,sans-serif;">'
                    f'{cal_in} / {target} kcal</p>', unsafe_allow_html=True)
    with c2:
        st.markdown(_svg_circle_gauge_pct(exercise_pct, "已消耗", "運動率", "#1B9D9E", size=140, stroke=10),
                    unsafe_allow_html=True)
        st.markdown(f'<p style="text-align:center; color:var(--text-dim); font-size:.8rem; '
                    f'margin:-4px 0 0; font-family:Noto Sans TC,sans-serif;">'
                    f'{cal_out} kcal</p>', unsafe_allow_html=True)
    with c3:
        if balance >= 0:
            bal_text = f"剩餘 {balance}"
            bal_color = "#1B9D9E"
            bal_label = "可攝取"
        else:
            bal_text = f"超出 {abs(balance)}"
            bal_color = "#EF5350"
            bal_label = "已達成赤字"
        st.markdown(f'<div style="text-align:center; margin-top:16px;">'
                    f'<div style="font-size:1.6rem; font-weight:900; color:{bal_color}; '
                    f'font-family:Noto Sans TC,sans-serif;">{bal_text}</div>'
                    f'<div style="font-size:.75rem; color:var(--text-dim); '
                    f'text-transform:uppercase; letter-spacing:1px; font-family:Noto Sans TC,sans-serif;">'
                    f'{bal_label} kcal</div></div>', unsafe_allow_html=True)



# ═══════════════════════════════════════════════════════════
#  UI 元件：Sidebar
# ═══════════════════════════════════════════════════════════

def render_sidebar():
    ud = st.session_state.user_data
    name = ud.get("name", "")
    xp = st.session_state.total_xp
    lv = get_level(xp)
    cur_xp, next_xp = get_next_level_xp(xp)
    pct = min((xp - cur_xp) / max(1, next_xp - cur_xp), 1.0)
    streak = st.session_state.streak

    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=100)
    else:
        st.markdown("""
        <div style="text-align:center; margin-bottom:8px;">
          <span style="font-size:1.4rem; font-weight:900;
                       background:linear-gradient(135deg,#1B9D9E,#0E6E6F);
                       -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                       font-family:'Noto Sans TC',sans-serif;">
            SousVille
          </span>
        </div>""", unsafe_allow_html=True)

    _show_banner()

    if st.session_state.profile_complete:
        mood = get_dolphin_mood()
        st.markdown(_svg_dolphin(mood, size=80), unsafe_allow_html=True)
        msg = get_dolphin_message(mood)
        st.markdown(f'<div class="mascot-speech">{msg}</div>', unsafe_allow_html=True)

    if st.session_state.profile_complete and ud.get("bmi"):
        bmi = ud["bmi"]
        bmi_color = "#1B9D9E" if 18.5 <= bmi < 24 else ("#FFB300" if 24 <= bmi < 27 else "#EF5350")
        st.markdown(f"""
        <div style="text-align:center; margin:6px 0 2px;">
          <span style="font-weight:900; font-size:1.1rem; color:{bmi_color}; font-family:'Noto Sans TC',sans-serif;">
            BMI {bmi}
          </span>
          <span style="color:var(--text-dim); font-size:.78rem;">（{bmi_category(bmi)}）</span>
        </div>""", unsafe_allow_html=True)

    st.markdown(f"<p style='text-align:center; font-weight:700; font-size:1.05rem; "
                f"margin-bottom:4px; font-family:Noto Sans TC,sans-serif;'>{name}</p>", unsafe_allow_html=True)
    st.caption(f"&#128197; {st.session_state.current_date}")
    st.markdown("---")

    st.markdown(f"""
    <div style="display:flex; align-items:center; gap:14px; margin-bottom:10px;">
      <div class="level-ring">{lv}</div>
      <div style="flex:1;">
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
          <span style="font-weight:700; font-size:.9rem;">Lv.{lv}</span>
          <span style="color:var(--text-dim); font-size:.8rem;">{xp} / {next_xp} XP</span>
        </div>
        <div class="xp-track">
          <div class="xp-fill" style="width:{pct * 100}%"></div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    if streak > 0:
        streak_icon = "&#128293;"
        st.markdown(f"""
        <div style="text-align:center; margin:8px 0;">
          <span class="streak-badge">{streak_icon} {streak} 天連續活躍</span>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="text-align:center; margin:8px 0;">
          <span style="color:var(--text-dim); font-size:.85rem;">&#128293; &#38283;&#22987;&#35352;&#37636;&#20358;&#24314;&#31435;&#36899;&#21205;&#65281;</span>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    if st.button("&#9881; &#20491;&#20154;&#35373;&#23450;", use_container_width=True, type="secondary"):
        st.session_state["show_profile"] = True
    if st.button("&#128221; &#36939;&#21205;&#38917;&#30446;&#26032;&#22686;", use_container_width=True, type="secondary"):
        st.session_state["show_exercise_mgr"] = True

    st.markdown("---")
    if st.button("&#30331;&#20986;", use_container_width=True, type="secondary"):
        _clear_auth_cache()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


def render_coupon_popup():
    st.markdown("""
    <div class="coupon-box">
      <div style="font-size:3rem; margin-bottom:12px;">&#127881;</div>
      <h2 style="color:var(--blue); margin-bottom:8px;">&#24680;&#21909;&#35299;&#38745;&#21830;&#22478;&#51229;&#24833;&#65281;</h2>
      <p style="font-size:1.05rem; color:var(--text-dim); margin-bottom:16px;">&#20320;&#24050;&#32044;&#31309;&#36229;&#36942; 500 XP</p>
      <div style="background:linear-gradient(135deg,var(--blue),var(--blue-deep));
                  display:inline-block; padding:14px 36px; border-radius:14px;
                  font-weight:900; font-size:1.3rem; color:#fff;
                  border:2px dashed var(--gold); letter-spacing:2px;">
        SOUSVILLE85
      </div>
      <p style="color:var(--text-dim); margin-top:10px; font-size:.82rem;">
        &#35531;&#20351;&#29992;&#20778;&#24863;&#30906; SOUSVILLE85 &#33267;&#33805;&#32933;&#24213;&#23478;&#21830;&#22478;&#20139; 85 &#25240;
      </p>
    </div>""", unsafe_allow_html=True)
    st.markdown(
        "[🛒 前往舒肥底家商城](https://sousville.com)  "
        "使用優惠碼 **SOUSVILLE85** 享 85 折優惠！"
    )


# ═══════════════════════════════════════════════════════════
#  頁面：身份驗證
# ═══════════════════════════════════════════════════════════

def _parse_user_props(p):
    """從 Notion page properties 解析出 user_data dict，包含 TDEE/BMR/BMI/target。"""
    data = {
        "name":  p["姓名"]["title"][0]["text"]["content"],
        "phone": p.get("電話", {}).get("phone_number", ""),
        "email": p["電子郵件"]["email"],
        "gender":   p.get("性別", {}).get("select", {}).get("name", ""),
        "age":      p.get("年齡", {}).get("number"),
        "height":   p.get("身高", {}).get("number"),
        "weight":   p.get("體重", {}).get("number"),
        "activity": p.get("活動程度", {}).get("select", {}).get("name", ""),
        "goal":     p.get("目標", {}).get("select", {}).get("name", ""),
        "bmi":      p.get("BMI", {}).get("number"),
        "bmr":      p.get("BMR", {}).get("number"),
        "tdee":     p.get("TDEE", {}).get("number"),
        "target":   p.get("目標卡路里", {}).get("number"),
        "total_xp": p.get("總經驗值", {}).get("number", 0) or 0,
        "level":    p.get("等級", {}).get("number", 1) or 1,
        "coupon":   p.get("優惠券已解鎖", {}).get("checkbox", False) or False,
    }
    gp_text = p.get("遊戲進度", {}).get("rich_text", [])
    if gp_text and gp_text[0].get("plain_text", "").strip():
        try:
            data["game_progress"] = json.loads(gp_text[0]["plain_text"])
        except (json.JSONDecodeError, KeyError):
            data["game_progress"] = {}
    gh = p.get("遊戲生命", {}).get("number")
    if gh is not None:
        data["game_hearts"] = gh
    return data


def _apply_user_session(user_data):
    """將 user_data 寫入 session_state 並判斷 profile 是否完整。"""
    st.session_state.user_data = user_data
    st.session_state.total_xp = user_data["total_xp"]
    st.session_state.coupon_unlocked = user_data["coupon"]
    if user_data.get("height") and user_data.get("weight"):
        st.session_state.profile_complete = True
    # Load game progress from Notion if available
    if user_data.get("game_progress") and isinstance(user_data["game_progress"], dict):
        st.session_state.game_progress = user_data["game_progress"]
    if user_data.get("game_hearts") is not None:
        st.session_state.game_hearts = user_data["game_hearts"]


def _restore_user_session(notion, page_id):
    """從 Notion page_id 載入使用者資料到 session state，回傳成功與否。"""
    try:
        page = notion.pages.retrieve(page_id=page_id)
        if page.get("archived"):
            return False
        st.session_state.user_page_id = page_id
        _apply_user_session(_parse_user_props(page["properties"]))
        return True
    except Exception:
        return False


def page_auth():
    _show_logo(center=True, height=140)
    st.markdown("""
    <div style="text-align:center; padding:0 0 28px;">
      <p style="color:var(--text-dim); font-size:1.05rem;">SousVille — 你的遊戲化健康管理夥伴</p>
    </div>""", unsafe_allow_html=True)

    # ── 自動登入：嘗試從本地快取恢復 ──
    cached_email, cached_page_id = _load_auth_cache()
    if cached_email and cached_page_id:
        try:
            notion = get_notion()
            if _restore_user_session(notion, cached_page_id):
                st.session_state.authenticated = True
                st.session_state.login_ip = get_client_ip()
                st.success(f"歡迎回來，{st.session_state.user_data['name']}！")
                st.rerun()
            else:
                _clear_auth_cache()
        except Exception:
            _clear_auth_cache()

    # ── 手動登入表單（只需姓名 + 信箱） ──
    with st.form("auth_form"):
        c1, c2 = st.columns(2)
        with c1:
            name  = st.text_input("姓名", placeholder="請輸入你的姓名")
        with c2:
            email = st.text_input("Email", placeholder="you@example.com")
        submitted = st.form_submit_button("開始你的健康旅程", use_container_width=True)

    if submitted:
        if not name or not email:
            st.warning("請填寫姓名與 Email")
            return

        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
            st.error("Email 格式不正確，請輸入有效的信箱，例如 you@example.com")
            return

        email = email.strip()

        try:
            notion = get_notion()
        except Exception as e:
            st.error(f"連接 Notion 失敗：{e}")
            return

        user = find_user(notion, email)

        if user:
            st.session_state.user_page_id = user["id"]
            _apply_user_session(_parse_user_props(user["properties"]))
            st.success(f"歡迎回來，{name}！")
        else:
            new_user = create_user(notion, name, "", email)
            if new_user is None:
                return
            st.session_state.user_page_id = new_user["id"]
            st.session_state.user_data = {
                "name": name, "phone": "", "email": email,
                "gender": "", "age": None, "height": None,
                "weight": None, "activity": "", "goal": "",
                "total_xp": 0, "level": 1, "coupon": False,
            }
            st.session_state.total_xp = 0
            st.session_state.coupon_unlocked = False
            st.success(f"歡迎加入舒肥底家，{name}！")

        # 去重並快取
        deduplicate_users(notion, email)
        _save_auth_cache(email, st.session_state.user_page_id)
        st.session_state.authenticated = True
        st.session_state.login_ip = get_client_ip()
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  頁面：個人設定
# ═══════════════════════════════════════════════════════════

def page_profile(notion):
    st.markdown("## ⚙️ 個人資料與體態設定", unsafe_allow_html=True)
    ud = st.session_state.user_data

    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        with c1:
            gender = st.selectbox("性別", ["男性", "女性", "其他"],
                                  index=0 if ud.get("gender") != "女性" else 1)
            age = st.number_input("年齡", min_value=1.0, max_value=120.0,
                                  value=round(float(ud.get("age") or 25), 1), step=0.1, format="%.1f")
        with c2:
            height = st.number_input("身高（公分）", min_value=100.0, max_value=250.0,
                                     value=round(float(ud.get("height") or 170), 1), step=0.1, format="%.1f")
            weight = st.number_input("體重（公斤）", min_value=30.0, max_value=300.0,
                                     value=round(float(ud.get("weight") or 70), 1), step=0.1, format="%.1f")

        st.markdown("---")
        activity = st.selectbox("現有運動強度", list(ACTIVITY_LEVELS.keys()),
                                index=list(ACTIVITY_LEVELS.keys()).index(ud["activity"])
                                if ud.get("activity") in ACTIVITY_LEVELS else 1)
        goal = st.selectbox("體態目標", list(GOAL_MULTIPLIERS.keys()),
                            index=list(GOAL_MULTIPLIERS.keys()).index(ud["goal"])
                            if ud.get("goal") in GOAL_MULTIPLIERS else 0)

        submitted = st.form_submit_button("儲存設定", use_container_width=True, type="primary")

    if submitted:
        bmi = calc_bmi(float(weight), float(height))
        bmr = calc_bmr(float(weight), float(height), int(float(age)), gender)
        tdee = calc_tdee(bmr, ACTIVITY_LEVELS[activity])
        target = calc_target(tdee, GOAL_MULTIPLIERS[goal])

        update_user_profile(notion, st.session_state.user_page_id, {
            "性別":       {"select": {"name": gender}},
            "年齡":       {"number": int(float(age))},
            "身高":       {"number": float(height)},
            "體重":       {"number": float(weight)},
            "BMI":        {"number": bmi},
            "BMR":        {"number": round(bmr)},
            "TDEE":       {"number": tdee},
            "目標卡路里":   {"number": target},
            "活動程度":    {"select": {"name": activity}},
            "目標":       {"select": {"name": goal}},
        })

        st.session_state.user_data.update({
            "gender": gender, "age": int(float(age)),
            "height": float(height), "weight": float(weight),
            "bmi": bmi, "bmr": round(bmr),
            "tdee": tdee, "target": target,
            "activity": activity, "goal": goal,
        })
        st.session_state.profile_complete = True
        st.success("資料已儲存！")

        try:
            if not st.session_state.get("today_log_id"):
                get_or_create_daily_log(notion, st.session_state.user_page_id, str(taiwan_today()))
            if st.session_state.get("today_log_id"):
                try:
                    notion.pages.update(page_id=st.session_state.today_log_id, properties={
                        "\u9ad4\u91cd": {"number": float(weight)},
                    })
                except Exception:
                    pass
        except Exception:
            pass
        st.session_state.pop("weight_history", None)

    if st.session_state.profile_complete and ud.get("tdee"):
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("← 返回首頁", use_container_width=True, type="secondary"):
                st.session_state.pop("show_profile", None)
                st.rerun()
        with c2:
            st.markdown("")

    if st.session_state.profile_complete and ud.get("tdee"):
        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"<div class='card' style='text-align:center;'>"
                        f"<div style='font-size:1.8rem; margin-bottom:4px;'>⚖️</div>"
                        f"<div style='font-size:1.7rem; font-weight:900; color:#1B9D9E;'>"
                        f"{ud['bmi']}</div>"
                        f"<div style='color:var(--text-dim); font-size:.75rem; "
                        f"text-transform:uppercase; letter-spacing:1px;'>BMI</div>"
                        f"<div style='color:#1B9D9E; font-size:.8rem; margin-top:2px;'>"
                        f"{bmi_category(ud['bmi'])}</div></div>", unsafe_allow_html=True)
        with c2:
            st.markdown(f"<div class='card' style='text-align:center;'>"
                        f"<div style='font-size:1.8rem; margin-bottom:4px;'>🔥</div>"
                        f"<div style='font-size:1.7rem; font-weight:900; color:#1B9D9E;'>"
                        f"{ud['bmr']}</div>"
                        f"<div style='color:var(--text-dim); font-size:.75rem; "
                        f"text-transform:uppercase; letter-spacing:1px;'>BMR</div>"
                        f"<div style='color:var(--text-dim); font-size:.8rem; margin-top:2px;'>"
                        f"大卡/天</div></div>", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<div class='card' style='text-align:center;'>"
                        f"<div style='font-size:1.8rem; margin-bottom:4px;'>⚡</div>"
                        f"<div style='font-size:1.7rem; font-weight:900; color:#FFB300;'>"
                        f"{ud['tdee']}</div>"
                        f"<div style='color:var(--text-dim); font-size:.75rem; "
                        f"text-transform:uppercase; letter-spacing:1px;'>TDEE</div>"
                        f"<div style='color:var(--text-dim); font-size:.8rem; margin-top:2px;'>"
                        f"目標 {ud['target']} kcal</div></div>", unsafe_allow_html=True)
        with c4:
            deficit = ud["tdee"] - ud.get("target", ud["tdee"])
            st.markdown(f"<div class='card' style='text-align:center;'>"
                        f"<div style='font-size:1.8rem; margin-bottom:4px;'>📉</div>"
                        f"<div style='font-size:1.7rem; font-weight:900; color:#1B9D9E;'>"
                        f"{deficit}</div>"
                        f"<div style='color:var(--text-dim); font-size:.75rem; "
                        f"text-transform:uppercase; letter-spacing:1px;'>熱量赤字</div>"
                        f"<div style='color:var(--text-dim); font-size:.8rem; margin-top:2px;'>"
                        f"大卡/天</div></div>", unsafe_allow_html=True)

    if st.session_state.profile_complete and ud.get("tdee"):
        st.markdown("---")
        st.markdown("### 📈 體重趨勢")
        history = query_weight_history(notion, st.session_state.user_page_id, days=30)
        if history:
            st.markdown(_render_weight_chart(history, width=800, height=300), unsafe_allow_html=True)
            mood = get_weight_trend_mood(history)
            delta = history[-1][1] - history[0][1]
            st.markdown(_svg_dolphin(mood, size=60), unsafe_allow_html=True)
            msg = get_weight_trend_message(mood, delta)
            st.markdown(f'<p style="text-align:center; font-weight:700; font-size:.9rem; '
                        f'color:var(--blue-deep); margin:-4px 0 8px; '
                        f'font-family:Noto Sans TC,sans-serif;">{msg}</p>', unsafe_allow_html=True)
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("\u6700\u65b0\u9ad4\u91cd", f"{history[-1][1]:.1f} kg")
            sc2.metric("\u671f\u9593\u6700\u9ad8", f"{max(h[1] for h in history):.1f} kg")
            sc3.metric("\u671f\u9593\u6700\u4f4e", f"{min(h[1] for h in history):.1f} kg")
        else:
            st.info("調整體重後會自動記錄，累積資料後會顯示趨勢圖。")

def _load_quiz_bank():
    if not QUIZ_FILE.exists():
        return None
    with open(QUIZ_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_all_levels(quiz_bank):
    levels = []
    for ch in quiz_bank["chapters"]:
        for lv in ch["levels"]:
            levels.append(lv)
    return levels


def _get_next_level(quiz_bank, completed):
    for ch in quiz_bank["chapters"]:
        for lv in ch["levels"]:
            if lv["id"] not in completed:
                return lv
    return None


def _save_game_progress(notion, user_page_id):
    gp = st.session_state.game_progress
    gp["hearts"] = st.session_state.game_hearts
    gp["total_game_xp"] = gp.get("total_game_xp", 0)
    try:
        update_user_profile(notion, user_page_id, {
            "遊戲進度": {"rich_text": [{"text": {"content": json.dumps(gp, ensure_ascii=False)}}]},
            "遊戲生命": {"number": st.session_state.game_hearts},
        })
    except Exception:
        pass


def _check_hearts_regen():
    rt = st.session_state.hearts_regen_time
    if rt is None or st.session_state.game_hearts >= 5:
        return
    now = datetime.now(TAIPEI_TZ)
    elapsed = (now - rt).total_seconds() / 60
    regen_count = int(elapsed / 30)
    if regen_count > 0:
        st.session_state.game_hearts = min(5, st.session_state.game_hearts + regen_count)
        if st.session_state.game_hearts >= 5:
            st.session_state.hearts_regen_time = None
        else:
            st.session_state.hearts_regen_time = rt + timedelta(minutes=regen_count * 30)


def _render_hearts_bar():
    full = st.session_state.game_hearts
    empty = 5 - full
    hearts_html = '<div class="game-hearts-bar">'
    hearts_html += '<span class="heart-full">' + '❤️' * full + '</span>'
    hearts_html += '<span class="heart-empty">' + '🖤' * empty + '</span>'
    rt = st.session_state.hearts_regen_time
    if rt and full < 5:
        now = datetime.now(TAIPEI_TZ)
        mins_left = max(0, 30 - int((now - rt).total_seconds() / 60))
        hearts_html += f'<span style="font-size:.75rem; color:var(--text-dim); margin-left:6px;">{mins_left}分鐘後恢復 1 顆</span>'
    hearts_html += '</div>'
    st.markdown(hearts_html, unsafe_allow_html=True)


def _render_game_map(quiz_bank):
    completed = set(st.session_state.game_progress.get("completed", []))
    next_lv = _get_next_level(quiz_bank, completed)
    next_id = next_lv["id"] if next_lv else None

    nodes_per_row = 5
    map_html = '<div class="game-map">'

    for ch in quiz_bank["chapters"]:
        map_html += f'<div class="game-chapter-label">{ch["icon"]} {ch["title"]}</div>'
        ch_levels = ch["levels"]
        for row_start in range(0, len(ch_levels), nodes_per_row):
            row_levels = ch_levels[row_start:row_start + nodes_per_row]
            row_idx = row_start // nodes_per_row
            if row_idx % 2 == 1:
                row_levels = list(reversed(row_levels))
            map_html += '<div class="game-row">'
            for i, lv in enumerate(row_levels):
                is_completed = lv["id"] in completed
                is_current = lv["id"] == next_id
                is_boss = lv.get("boss", False)
                if is_completed:
                    cls = "completed"
                    icon = "✅"
                elif is_current:
                    cls = "current"
                    icon = "⭐"
                else:
                    cls = "locked"
                    icon = "🔒"
                boss_cls = " boss" if is_boss else ""
                title = lv["title"].replace("🧬 ", "").replace("🥗 ", "").replace("🏃 ", "")
                map_html += f'<div class="game-node {cls}{boss_cls}" title="{title}">{icon}</div>'
                if i < len(row_levels) - 1:
                    conn_cls = "completed" if is_completed else "locked"
                    map_html += f'<div class="game-connector {conn_cls}"></div>'
            map_html += '</div>'
    map_html += '</div>'
    st.markdown(map_html, unsafe_allow_html=True)


def _render_level_stats(quiz_bank):
    completed = set(st.session_state.game_progress.get("completed", []))
    total_levels = sum(len(ch["levels"]) for ch in quiz_bank["chapters"])
    done_count = len(completed & {lv["id"] for ch in quiz_bank["chapters"] for lv in ch["levels"]})
    total_game_xp = st.session_state.game_progress.get("total_game_xp", 0)
    pct = int(done_count / max(1, total_levels) * 100)

    stats_html = f'''<div class="game-progress-bar">
      <div class="game-progress-track">
        <div class="game-progress-fill" style="width:{pct}%"></div>
      </div>
      <span style="font-size:.82rem; color:var(--text-dim); font-weight:700;">{done_count}/{total_levels}</span>
      <span style="font-size:.82rem; color:var(--gold); font-weight:900; margin-left:4px;">{total_game_xp} XP</span>
    </div>'''
    st.markdown(stats_html, unsafe_allow_html=True)


def tab_daily_challenge(notion):
    st.markdown("### 🎯 關卡挑戰", unsafe_allow_html=True)

    quiz_bank = _load_quiz_bank()
    if not quiz_bank:
        st.error("找不到 quiz_bank.json")
        return

    completed = set(st.session_state.game_progress.get("completed", []))
    _check_hearts_regen()

    # ── STATE: playing a level ──
    if st.session_state.current_level is not None:
        _play_level(notion, quiz_bank)
        return

    # ── STATE: map view ──
    _render_level_stats(quiz_bank)
    _render_hearts_bar()

    # Refill hearts button
    if st.session_state.game_hearts < 5 and st.session_state.total_xp >= 10:
        if st.button("💔 花 10 XP 補滿 ❤️×5", use_container_width=True):
            st.session_state.total_xp -= 10
            st.session_state.game_hearts = 5
            st.session_state.hearts_regen_time = None
            update_user_profile(notion, st.session_state.user_page_id, {
                "總經驗值": {"number": st.session_state.total_xp},
            })
            _save_game_progress(notion, st.session_state.user_page_id)
            st.rerun()

    st.markdown("---")
    _render_game_map(quiz_bank)

    next_lv = _get_next_level(quiz_bank, completed)
    if next_lv:
        if st.session_state.game_hearts <= 0:
            st.warning("❤️ 生命值已用完！請等待恢復或花 10 XP 補滿。")
        else:
            boss_tag = " 👑 BOSS" if next_lv.get("boss") else ""
            reward = next_lv["reward_xp"]
            if st.button(f"🎮 開始挑戰：{next_lv['title']}{boss_tag}（+{reward} XP）",
                         type="primary", use_container_width=True):
                st.session_state.current_level = next_lv["id"]
                st.session_state.level_q_idx = 0
                st.session_state.level_correct = 0
                st.rerun()
    else:
        st.markdown("""
        <div class="quiz-card" style="text-align:center; padding:44px;">
          <div style="font-size:3rem; margin-bottom:10px;">🏆</div>
          <h3 style="color:#FFB300;">恭喜全部通關！</h3>
          <p style="color:var(--text-dim);">你是健康知識達人！</p>
        </div>""", unsafe_allow_html=True)


def _play_level(notion, quiz_bank):
    level_id = st.session_state.current_level
    level = None
    for ch in quiz_bank["chapters"]:
        for lv in ch["levels"]:
            if lv["id"] == level_id:
                level = lv
                break
        if level:
            break
    if not level:
        st.session_state.current_level = None
        return

    questions = level["questions"]
    q_idx = st.session_state.level_q_idx
    total_q = len(questions)

    # Progress bar
    pct = int((q_idx) / max(1, total_q) * 100)
    st.markdown(f'''<div style="margin:8px 0 4px;">
      <span style="font-weight:800; font-size:.9rem; color:var(--text);">
        {level["title"]}
      </span>
      <span style="color:var(--text-dim); font-size:.8rem; margin-left:8px;">
        {q_idx + 1} / {total_q}
      </span>
    </div>
    <div style="width:100%; height:8px; background:rgba(27,157,158,0.1);
                border-radius:4px; overflow:hidden;">
      <div style="width:{pct}%; height:100%; border-radius:4px;
                  background:linear-gradient(90deg,var(--blue),var(--blue-light));
                  transition:width .4s ease;"></div>
    </div>''', unsafe_allow_html=True)

    _render_hearts_bar()

    if q_idx >= total_q:
        _finish_level(notion, quiz_bank, level)
        return

    q = questions[q_idx]
    boss_cls = " boss" if level.get("boss") else ""

    st.markdown(f'''
    <div class="quiz-card{boss_cls}" style="padding:28px 32px; margin:16px 0;">
      <h3 style="font-size:1.1rem; margin:0;">{q["question"]}</h3>
    </div>''', unsafe_allow_html=True)

    selected = st.radio("選擇答案", range(len(q["options"])),
                        format_func=lambda i: q["options"][i],
                        key=f"game_q_{q_idx}",
                        label_visibility="collapsed")

    if st.button("確認答案", type="primary", use_container_width=True,
                 key=f"game_btn_{q_idx}"):
        correct = selected == q["answer"]
        if correct:
            st.session_state.level_correct += 1
            st.success(f"✅ 正確！{q['explanation']}")
        else:
            st.session_state.game_hearts = max(0, st.session_state.game_hearts - 1)
            if st.session_state.game_hearts <= 0:
                st.session_state.hearts_regen_time = datetime.now(TAIPEI_TZ)
            st.error(f"❌ 答錯了！正確答案：{q['options'][q['answer']]}")
            st.markdown(f"📖 {q['explanation']}")
            if st.session_state.game_hearts <= 0:
                st.session_state.current_level = None
                _save_game_progress(notion, st.session_state.user_page_id)
                st.rerun()
                return

        st.session_state.level_q_idx = q_idx + 1
        st.rerun()


def _finish_level(notion, quiz_bank, level):
    correct = st.session_state.level_correct
    total_q = len(level["questions"])
    passed = correct >= 3  # Need 3/5 correct to pass
    is_boss = level.get("boss", False)
    reward = level["reward_xp"]

    if passed:
        gp = st.session_state.game_progress
        gp.setdefault("completed", []).append(level["id"])
        gp["completed"] = list(set(gp["completed"]))
        gp["total_game_xp"] = gp.get("total_game_xp", 0) + reward
        st.session_state.game_progress = gp
        st.session_state.daily_quiz_done = True
        st.session_state.today_quiz_xp = reward

        unlocked = add_user_xp(notion, st.session_state.user_page_id, reward)

        if st.session_state.today_log_id:
            patch_daily_log(notion, st.session_state.today_log_id, {
                "問答完成": {"checkbox": True},
                "獲得經驗值": {"number": reward},
            })

        _save_game_progress(notion, st.session_state.user_page_id)

        boss_text = " 👑 BOSS 通過！" if is_boss else ""
        st.markdown(f'''
        <div class="game-result-box success">
          <div style="font-size:3rem; margin-bottom:8px;">{"🏆" if is_boss else "🎉"}</div>
          <h3 style="color:#43A047; margin:0 0 8px;">通關成功{boss_text}</h3>
          <p style="color:var(--text-dim); margin:0 0 12px;">
            答對 {correct}/{total_q} 題
          </p>
          <span style="display:inline-block; background:#43A047;
                      padding:6px 20px; border-radius:20px; font-weight:900; color:#fff;">
            +{reward} XP
          </span>
        </div>''', unsafe_allow_html=True)
        st.balloons()

        if is_boss:
            st.session_state.coupon_unlocked = True
            update_user_profile(notion, st.session_state.user_page_id, {
                "優惠券已解鎖": {"checkbox": True},
            })
            render_coupon_popup()
        elif unlocked:
            st.markdown("<br>", unsafe_allow_html=True)
            render_coupon_popup()
    else:
        st.markdown(f'''
        <div class="game-result-box fail">
          <div style="font-size:3rem; margin-bottom:8px;">💪</div>
          <h3 style="color:#EF5350; margin:0 0 8px;">挑戰失敗</h3>
          <p style="color:var(--text-dim); margin:0 0 4px;">
            答對 {correct}/{total_q} 題（需 3 題才能通關）
          </p>
          <p style="color:var(--text-dim); font-size:.85rem;">再接再厲，你可以的！</p>
        </div>''', unsafe_allow_html=True)

    if st.button("← 返回地圖", use_container_width=True):
        st.session_state.current_level = None
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  Tab 2：飲食紀錄
# ═══════════════════════════════════════════════════════════

def tab_diet_record(notion):
    st.markdown("### &#127869;&#65039; 飲食紀錄", unsafe_allow_html=True)

    ud = st.session_state.user_data
    target = ud.get("target", 2000)
    cal_in = st.session_state.today_cal_in

    mode = st.radio("輸入方式", ["📷 AI 辨識", "🍱 餐盒快選", "✏️ 手動份量"],
                    horizontal=True, label_visibility="collapsed")

    # ── 模式一：AI 辨識 ──
    if mode == "📷 AI 辨識":
        camera_photo = st.camera_input("拍攝食物照片", label_visibility="visible")

        if camera_photo:
            st.image(camera_photo, width=250)

            if "ai_result" not in st.session_state:
                with st.spinner("AI 分析中..."):
                    camera_photo.seek(0)
                    st.session_state.ai_result = process_image(camera_photo)

            result = st.session_state.ai_result

            if "error" in result:
                st.warning(result["error"])
                if st.button("重新拍攝", use_container_width=True, type="secondary"):
                    st.session_state.pop("ai_result", None)
                    st.rerun()
            else:
                st.success(f"辨識結果：**{result['food_name']}**")

                c1, c2 = st.columns(2)
                with c1:
                    food_name = st.text_input("食物名稱", value=result["food_name"],
                                              key="ai_food_name")
                with c2:
                    cal_val = st.number_input("熱量 (kcal)", min_value=0.0,
                                              max_value=5000.0, value=float(result["calories"]),
                                              step=10.0, format="%.0f", key="ai_cal")

                c3, c4, c5 = st.columns(3)
                with c3:
                    prot_val = st.number_input("蛋白質 (g)", min_value=0.0,
                                               max_value=500.0, value=float(result["protein"]),
                                               step=1.0, format="%.1f", key="ai_prot")
                with c4:
                    fat_val = st.number_input("脂肪 (g)", min_value=0.0,
                                              max_value=500.0, value=float(result["fat"]),
                                              step=1.0, format="%.1f", key="ai_fat")
                with c5:
                    carbs_val = st.number_input("碳水 (g)", min_value=0.0,
                                                max_value=500.0, value=float(result["carbs"]),
                                                step=1.0, format="%.1f", key="ai_carbs")

                fiber_val = st.number_input("膳食纖維 (g)", min_value=0.0,
                                            max_value=50.0, value=float(result["fiber"]),
                                            step=0.5, format="%.1f", key="ai_fiber")

                if st.button("確認紀錄", type="primary", use_container_width=True):
                    cal_int = int(cal_val)
                    st.session_state.today_cal_in += cal_int
                    log_text = f"{food_name} ({cal_int} kcal)"
                    st.session_state.today_meals.append(log_text)
                    sync_meal_to_notion(notion, st.session_state.today_log_id,
                                        food_name, cal_int)
                    st.session_state.pop("ai_result", None)
                    st.success(f"已紀錄：{log_text} ✅")
                    st.rerun()
        else:
            st.session_state.pop("ai_result", None)

    # ── 模式二：餐盒快選 ──
    elif mode == "🍱 餐盒快選":
        bento_names = list(BENTO_BOXES.keys())
        bento_name = st.selectbox("選擇餐盒", bento_names)
        bento = BENTO_BOXES[bento_name]
        bento_cal = bento["cal"]
        bento_protein = bento.get("protein", 0)
        bento_fiber = bento.get("fiber", 0)
        bento_fat = bento.get("fat", 0)

        st.metric("預估熱量", f"{bento_cal} kcal")
        c1, c2, c3 = st.columns(3)
        c1.metric(label="蛋白質", value=f"{bento_protein} g")
        c2.metric(label="膳食纖維", value=f"{bento_fiber} 份")
        c3.metric(label="油脂", value=f"{bento_fat} 茶匙")

        if st.button("紀錄此餐盒", type="primary", use_container_width=True):
            st.session_state.today_cal_in += bento_cal
            st.session_state.portions["\u852c\u83dc"] += bento_fiber
            st.session_state.portions["\u6cb9\u8102"] += bento_fat
            log_text = f"{bento_name} ({bento_cal} kcal)"
            st.session_state.today_meals.append(log_text)
            sync_meal_to_notion(notion, st.session_state.today_log_id,
                                bento_name, bento_cal)
            st.success(f"已紀錄：{log_text} ✅")
            st.rerun()

    # ── 模式三：手動份量 ──
    else:
        portion_img = Path(__file__).parent / "assets" / "01.png"
        if portion_img.exists():
            st.image(str(portion_img), width=480)
        st.caption("依據每日飲食指南份量計算熱量")
        cols = st.columns(5)
        keys = list(PORTION_CAL.keys())
        vals = []
        for i, col in enumerate(cols):
            with col:
                v = st.number_input(keys[i], min_value=0.0, max_value=20.0,
                                    value=0.0, step=0.5, format="%.1f",
                                    key=f"port_{keys[i]}")
                vals.append(v)

        manual_cal = round(
            vals[0] * PORTION_CAL["蛋白質"]
            + vals[1] * PORTION_CAL["蔬菜"]
            + vals[2] * PORTION_CAL["全穀根莖"]
            + vals[3] * PORTION_CAL["油脂"]
            + vals[4] * PORTION_CAL["奶類"]
        )

        st.markdown(f"""
        <div style="text-align:center; padding:14px; margin:8px 0;
                    background:linear-gradient(135deg, rgba(255,87,34,0.06), rgba(0,200,83,0.06));
                    border-radius:14px; border:1px solid rgba(255,87,34,0.12);">
          <div style="color:var(--text-dim); font-size:.85rem; margin-bottom:4px;">估算總熱量</div>
          <div style="font-size:2rem; font-weight:900; color:#1B9D9E;">{manual_cal} kcal</div>
        </div>""", unsafe_allow_html=True)

        if st.button("紀錄份量", type="primary", use_container_width=True):
            st.session_state.today_cal_in += manual_cal
            for i, k in enumerate(keys):
                st.session_state.portions[k] += vals[i]
            log_text = f"手動份量 ({manual_cal} kcal)"
            st.session_state.today_meals.append(log_text)
            sync_meal_to_notion(notion, st.session_state.today_log_id,
                                "手動份量", manual_cal)
            st.success(f"已紀錄：{log_text} ✅")
            st.rerun()

    # ── 份量達成進度 ──
    st.markdown("---")
    dol_icon = '<span class="dolphin-progress-icon">&#128044;</span>'
    st.markdown(f"#### {dol_icon} &#20170;&#26085;&#20221;&#37327;&#36948;&#25104;", unsafe_allow_html=True)
    for name, target_val in PORTION_TARGETS.items():
        cur = st.session_state.portions.get(name, 0)
        pct = min(cur / target_val, 1.0) if target_val > 0 else 0
        icon = "&#9989;" if pct >= 1.0 else "&#128044;"
        label = f"{icon} {name}　{cur:.1f} / {target_val} &#20221;"
        st.progress(pct, text=label)

    # ── 今日餐點列表 ──
    st.markdown("---")
    if st.session_state.today_meals:
        for m in st.session_state.today_meals:
            st.markdown(f"- {m}")
        st.markdown(f"**總攝取：{cal_in} kcal**")
    else:
        st.caption("尚未紀錄任何餐點")


# ═══════════════════════════════════════════════════════════
#  Tab 3：運動紀錄
# ═══════════════════════════════════════════════════════════

def tab_exercise_record(notion):
    st.markdown("### 🏃 運動紀錄", unsafe_allow_html=True)

    if not st.session_state.profile_complete:
        st.warning("請先完成「個人設定」以啟用此功能。")
        return

    ud = st.session_state.user_data
    weight = float(ud.get("weight", 70) or 70)

    # ── 今日運動消耗摘要 ──
    cal_out = st.session_state.today_cal_out
    m1, m2 = st.columns(2)
    m1.metric(label="運動次數", value=f"{len(st.session_state.today_exercises)} 次")
    m2.metric(label="總消耗", value=f"{cal_out} kcal")

    st.markdown("---")

    # ── 運動輸入區 ──
    all_exercises = merge_exercises()
    ex_list = list(all_exercises.keys())
    ex_name = st.selectbox("選擇運動項目", ex_list, key="ex_select")

    if ex_name != st.session_state.get("_prev_ex"):
        st.session_state["_prev_ex"] = ex_name
        st.session_state["_ex_met"] = all_exercises[ex_name]
        st.rerun()

    duration = st.number_input("運動時間（分鐘）", min_value=1, max_value=300,
                               value=30, step=1, key="ex_duration")

    met = st.number_input("MET 強度修正", min_value=0.1, max_value=25.0,
                          value=st.session_state.get("_ex_met", all_exercises[ex_name]),
                          step=0.1, format="%.1f", key="ex_met")
    st.session_state["_ex_met"] = met

    st.caption("💡 提示：系統已為您預設標準強度，您可依個人感受手動微調 MET 係數。")

    est_cal = round((met * 3.5 * weight / 200) * duration)

    st.markdown(f"""
    <div style="text-align:center; padding:14px; margin:8px 0;
                background:linear-gradient(135deg, rgba(255,87,34,0.06), rgba(0,200,83,0.06));
                border-radius:14px; border:1px solid rgba(255,87,34,0.12);">
      <div style="color:var(--text-dim); font-size:.85rem; margin-bottom:4px;">預估消耗熱量</div>
      <div style="font-size:2rem; font-weight:900; color:#1B9D9E;">{est_cal} kcal</div>
    </div>""", unsafe_allow_html=True)

    if st.button("🏃 紀錄運動", type="primary", use_container_width=True):
        st.session_state.today_cal_out += est_cal
        log_text = f"{ex_name} MET {met} {duration}分 ({est_cal} kcal)"
        st.session_state.today_exercises.append(log_text)
        sync_exercise_to_notion(notion, st.session_state.today_log_id, log_text, est_cal)
        st.success(f"已紀錄：{log_text} ✅")
        st.rerun()

    st.markdown("---")
    if st.session_state.today_exercises:
        for e in st.session_state.today_exercises:
            st.markdown(f"- {e}")
        st.markdown(f"**總消耗：{st.session_state.today_cal_out} kcal**")
    else:
        st.caption("尚未紀錄運動")




# ═# ═# ═# ═# ═# ═# ══
#  Tab 4：熱量赤字
# ═# ═# ═# ═# ═# ═# ══

def tab_calorie_deficit(notion):
    st.markdown("### ▽ 今日熱量總覽", unsafe_allow_html=True)

    if not st.session_state.profile_complete:
        st.warning("請先完成「個人設定」以啟用此功能。")
        return

    ud = st.session_state.user_data
    tdee = ud.get("tdee") or 2000
    target = ud.get("target", tdee)
    cal_in = st.session_state.today_cal_in
    cal_out = st.session_state.today_cal_out
    balance = (tdee + cal_out) - cal_in

    # ── 三個核心指標卡 ──
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='card' style='text-align:center;'>"
                    "<div style='font-size:1.5rem; margin-bottom:4px;'>&#127869;&#65039;</div>"
                    f"<div style='font-size:1.5rem; font-weight:900; color:#FFB300;'>"
                    f"{cal_in}</div>"
                    "<div style='color:var(--text-dim); font-size:.75rem; "
                    "text-transform:uppercase; letter-spacing:1px;'>已攝取</div>"
                    "</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='card' style='text-align:center;'>"
                    "<div style='font-size:1.5rem; margin-bottom:4px;'>&#127939;</div>"
                    f"<div style='font-size:1.5rem; font-weight:900; color:#1B9D9E;'>"
                    f"{cal_out}</div>"
                    "<div style='color:var(--text-dim); font-size:.75rem; "
                    "text-transform:uppercase; letter-spacing:1px;'>已消耗</div>"
                    "</div>", unsafe_allow_html=True)
    with c3:
        if balance >= 0:
            net_color = "#1B9D9E"
            net_label = "淨餘額"
            net_icon = "&#128293;"
        else:
            net_color = "#EF5350"
            net_label = "淨餘額"
            net_icon = "&#128680;"
        st.markdown(f"<div class='card' style='text-align:center;'>"
                    f"<div style='font-size:1.5rem; margin-bottom:4px;'>{net_icon}</div>"
                    f"<div style='font-size:1.5rem; font-weight:900; color:{net_color};'>"
                    f"{'+' if balance > 0 else ''}{balance}</div>"
                    f"<div style='color:var(--text-dim); font-size:.75rem; "
                    f"text-transform:uppercase; letter-spacing:1px;'>{net_label}</div>"
                    f"</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── 攝取進度條（以目標為分母）──
    intake_bar_pct = min(cal_in / max(target, 1), 1.0)
    st.progress(intake_bar_pct, text=f"攝取 {cal_in} / 目標 {target} kcal")

    # ── 遊戲化視覺結果 ──
    if balance > 0:
        result_icon = "&#128293;"
        result_color = "#1B9D9E"
        result_text = f"剩餘可攝取 {balance} kcal"
        result_sub = "脂肪正在燃燒中！繼續保持！"
        bg_style = "background:rgba(27,157,158,0.08); border:1px solid rgba(27,157,158,0.15);"
    else:
        result_icon = "&#128680;"
        result_color = "#EF5350"
        result_text = f"已超出 {abs(balance)} kcal"
        result_sub = "能量過剩！建議快去運動 20 分鐘來消抵。"
        bg_style = "background:rgba(239,83,80,0.08); border:1px solid rgba(239,83,80,0.15);"

    st.markdown(f"""
    <div style="text-align:center; padding:16px; {bg_style} border-radius:12px; margin-top:12px;">
      <div style="font-size:2rem; margin-bottom:6px;">{result_icon}</div>
      <div style="font-size:1.8rem; font-weight:900; color:{result_color}; font-family:'Noto Sans TC',sans-serif;">
        {result_text}
      </div>
      <div style="font-size:.9rem; color:var(--text-dim); margin-top:4px;">
        {result_sub}
      </div>
    </div>""", unsafe_allow_html=True)

    # ── 提示 ──
    st.markdown(f"""
    <div style="text-align:center; padding:12px; background:rgba(0,200,83,0.06);
                border-radius:12px; border:1px solid rgba(0,200,83,0.12);">
      <span style="color:var(--text-dim); font-size:.85rem;">
        &#128161; TDEE <strong style="color:#1B9D9E;">{tdee} kcal</strong>
        是你一天總消耗（含基礎代謝 + 日常活動）。攝取不超過 TDEE 就不會胖，運動越多赤字越大！
      </span>
    </div>""", unsafe_allow_html=True)


def page_exercise_manager():
    st.markdown("## 🗂️ 運動項目新增", unsafe_allow_html=True)

    all_ex = merge_exercises()
    sorted_names = sorted(all_ex.items(), key=lambda x: x[0])

    with st.form("add_ex_form"):
        new_name = st.text_input("運動名稱", placeholder="選擇或輸入新運動名稱",
                                 key="ex_mgr_name")
        if new_name in all_ex:
            st.markdown(f'<span style="color:var(--text-dim); font-size:.85rem;">'
                        f'自動帶入 MET：<strong style="color:#FFB300;">{all_ex[new_name]}</strong></span>',
                        unsafe_allow_html=True)
            default_met = all_ex[new_name]
        else:
            default_met = 5.0
        new_met = st.number_input("MET 係數", min_value=0.1, max_value=25.0,
                                  value=default_met, step=0.1, format="%.1f", key="ex_mgr_met")
        st.caption("💡 提示：MET 係數為該運動相對於靜息狀態的能量消耗倍率。"
                   "數值越大代表運動越激烈。你可依個人實際感受手動修正。")
        add_sub = st.form_submit_button("新增 / 更新", use_container_width=True, type="primary")

    if add_sub:
        name = new_name.strip()
        if not name:
            st.warning("請輸入名稱")
        elif name in EXERCISE_MET and new_met != EXERCISE_MET[name]:
            st.info(f"已將「{name}」的 MET 從 {EXERCISE_MET[name]} 覆蓋為 {new_met}（儲存於自訂清單）")
            st.session_state.custom_exercises[name] = new_met
            _save_local_custom_exercises(st.session_state.custom_exercises)
            st.rerun()
        elif name in EXERCISE_MET:
            st.info(f"「{name}」為內建運動（MET {EXERCISE_MET[name]}），無需重複新增")
        elif name in st.session_state.custom_exercises:
            st.session_state.custom_exercises[name] = new_met
            _save_local_custom_exercises(st.session_state.custom_exercises)
            st.success(f"已更新「{name}」MET → {new_met}")
            st.rerun()
        else:
            add_custom_exercise(name, new_met)
            st.success(f"已新增「{name}」（MET {new_met}）")
            st.rerun()

    st.markdown("---")
    st.markdown("### 📋 全部運動項目", unsafe_allow_html=True)

    tabs_builtin, tabs_custom = st.tabs(["🥇 內建運動", "✏️ 自訂運動"])

    with tabs_builtin:
        builtin = sorted(EXERCISE_MET.items(), key=lambda x: x[0])
        cols = st.columns(3)
        for i, (n, m) in enumerate(builtin):
            with cols[i % 3]:
                st.markdown(f"**{n}** — MET `{m}`")

    with tabs_custom:
        custom = st.session_state.custom_exercises
        if custom:
            for name, met in custom.items():
                ci, cb = st.columns([5, 1])
                with ci:
                    st.markdown(f"**{name}** — MET `{met}`")
                with cb:
                    if st.button("刪除", key=f"del_{name}", type="secondary"):
                        delete_custom_exercise(name)
                        st.rerun()
        else:
            st.caption("尚未新增自訂運動")

    if st.button("← 返回首頁", use_container_width=True, type="secondary"):
        st.session_state.pop("show_exercise_mgr", None)
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════

def main():
    init_session_state()
    check_daily_reset()
    check_ip_change()

    if not st.session_state.authenticated:
        page_auth()
        return

    try:
        notion = get_notion()
    except Exception as e:
        st.error(f"連接 Notion 失敗：{e}")
        st.stop()

    if st.session_state.profile_complete and st.session_state.user_page_id:
        get_or_create_daily_log(notion, st.session_state.user_page_id,
                                st.session_state.current_date)

    if st.session_state.user_page_id:
        calc_streak(notion, st.session_state.user_page_id)

    if st.session_state.get("show_profile"):
        render_sidebar()
        page_profile(notion)
        return

    if st.session_state.get("show_exercise_mgr"):
        render_sidebar()
        page_exercise_manager()
        return

    with st.sidebar:
        render_sidebar()

    render_top_dashboard()

    if not st.session_state.profile_complete:
        st.warning("請先點擊左側「⚙️ 個人設定」完成資料填寫。")
        return

    tab1, tab2, tab3, tab4 = st.tabs(["🎯 今日挑戰", "🍽️ 飲食紀錄", "🏃 運動紀錄", "📉 熱量赤字"])

    with tab1:
        tab_daily_challenge(notion)
    with tab2:
        tab_diet_record(notion)
    with tab3:
        tab_exercise_record(notion)
    with tab4:
        tab_calorie_deficit(notion)

    st.markdown("""
    <div style="display:flex; justify-content:center; gap:10px; padding:20px 0 8px;">
      <span style="width:10px; height:10px; border-radius:50%; background:#1B9D9E; display:inline-block;"></span>
      <span style="width:10px; height:10px; border-radius:50%; background:rgba(27,157,158,0.25); display:inline-block;"></span>
      <span style="width:10px; height:10px; border-radius:50%; background:rgba(27,157,158,0.25); display:inline-block;"></span>
      <span style="width:10px; height:10px; border-radius:50%; background:rgba(27,157,158,0.25); display:inline-block;"></span>
    </div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
