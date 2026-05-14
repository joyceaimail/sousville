"""
NutriGo NutriGo — 遊戲化健康管理系統
========================================
Streamlit 前端  |  BMI · TDEE · 熱量赤字 · 每日問答 · 運動紀錄 · XP 商城

後端 API：sufeidijia-api（FastAPI + Supabase），預設 ``https://api.joyceaimail.org``。

啟動方式：
    export API_BASE_URL="https://api.joyceaimail.org"   # 或自架後端
    export GEMINI_API_KEY="..."                         # AI 食物辨識用（可選）
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

import api_client
from api_client import APIError

TAIPEI_TZ = pytz.timezone("Asia/Taipei")

def taiwan_today():
    """回傳台北時區的今天日期 (date)。"""
    return datetime.now(TAIPEI_TZ).date()


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
GEMINI_API_KEY = _get_secret("GEMINI_API_KEY")

CUSTOM_EX_FILE = Path(__file__).parent / "custom_exercises.json"

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

AI_SYSTEM_PROMPT = """你是「NutriGo NutriGo」的營養助手。你的唯一職責是辨識食物照片並回傳營養數據。

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

NutriGo份量參考（估算餐盒時使用）：
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
        import google.generativeai as genai
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
    page_title="NutriGo | NutriGo",
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
  /* ─── 暖珊瑚 + 金（柔暖系，不壓迫）── */
  --red:          #FF8A65;          /* 主色：珊瑚桃，暖但不壓迫 */
  --red-deep:     #F4511E;          /* 強調：烤橙紅 */
  --red-light:    #FFCDB2;          /* 淺色：淡桃 */
  --red-glow:     rgba(255,138,101,0.25);
  --orange:       #FFB088;          /* 暖橘（柔） */
  --gold:         #FFB300;          /* 金 */
  --gold-deep:    #FF8F00;
  --gold-glow:    rgba(255,179,0,0.30);
  --success:      #43A047;          /* 對的、達標保留綠 */
  --success-glow: rgba(67,160,71,0.18);

  --cream:        #FFFAF5;          /* 米白底（更亮） */
  --warm-card:    #FFFFFF;
  --warm-card-alt:#FFFAF3;
  --warm-sidebar: linear-gradient(180deg, #FFEFE3 0%, #FFFFFF 50%);

  --text:         #2D1B0E;          /* 暖黑 */
  --text-dim:     #8B5A3C;          /* 暖棕 */
  --border:       rgba(230,57,70,0.12);
  --shadow:       0 4px 20px rgba(230,57,70,0.08);
  --shadow-hover: 0 6px 28px rgba(230,57,70,0.18);

  /* ─── 舊變數 alias（不改舊 class，自動繼承新色）── */
  --blue:         var(--red);
  --blue-dim:     var(--red-deep);
  --blue-deep:    var(--red-deep);
  --blue-light:   var(--red-light);
  --blue-glow:    var(--red-glow);
  --green:        var(--success);
  --green-dim:    var(--success);
  --green-glow:   var(--success-glow);
  --gold-dim:     var(--gold-deep);
  --coral:        var(--orange);
  --bg:           var(--cream);
  --bg-white:     #FFFFFF;
  --bg-card:      var(--warm-card);
  --bg-card-alt:  var(--warm-card-alt);
  --bg-sidebar:   var(--warm-sidebar);
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
.xp-fill { height: 100%; border-radius: 12px; background: linear-gradient(90deg, var(--gold), var(--orange)); transition: width .5s ease; box-shadow: 0 0 12px var(--gold-glow); }

.level-ring {
  width: 72px; height: 72px; border-radius: 50%;
  background: linear-gradient(135deg, var(--red), var(--orange));
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 900; font-size: 1.6rem; color: #fff;
  box-shadow: 0 4px 18px var(--red-glow); border: 4px solid var(--gold);
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
  background: linear-gradient(135deg, var(--red), var(--red-deep)) !important;
  color: #fff !important; border-color: var(--red) !important;
  box-shadow: 0 4px 18px var(--red-glow);
  transform: translateY(-1px);
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
  content: '© 2026 NutriGo NutriGo';
  visibility: visible;
  display: block;
  text-align: center;
  padding: 10px;
  color: var(--text-dim);
  font-size: 0.8rem;
  font-family: 'Noto Sans TC', sans-serif;
}

/* ── 手機 RWD ── */
/* ── Game-first 首頁（status 條 / hero / section nav）── */
.top-status-bar {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; background: var(--warm-card);
  border-radius: 18px; box-shadow: var(--shadow);
  margin-bottom: 12px; border: 1px solid var(--border);
}
.status-level-pill {
  background: linear-gradient(135deg, var(--red-deep), var(--gold));
  color: #fff; font-weight: 900; font-size: 1rem;
  padding: 8px 16px; border-radius: 20px;
  font-family: 'Quicksand', sans-serif;
  box-shadow: 0 3px 8px var(--gold-glow);
  white-space: nowrap;
}
.status-name { font-weight: 800; color: var(--text); font-size: .95rem; }
.status-xp-section { flex: 1; min-width: 100px; }
.status-xp-track {
  height: 14px; background: rgba(255,138,101,0.15);
  border-radius: 8px; overflow: hidden;
}
.status-xp-fill {
  height: 100%; background: linear-gradient(90deg, var(--gold), var(--red-deep));
  transition: width .5s ease; box-shadow: 0 0 10px var(--gold-glow);
}
.status-xp-text { font-size: .78rem; color: var(--text-dim); margin-top: 3px; text-align: right; }
.status-hearts { font-size: 1.3rem; letter-spacing: 1px; white-space: nowrap; }

/* Hero next-level 卡（大 CTA） */
.hero-next-level {
  display: flex; align-items: center; gap: 16px;
  background: linear-gradient(135deg, rgba(255,179,0,0.14), rgba(255,138,101,0.10));
  border: 2px solid var(--gold); border-radius: 22px;
  padding: 20px 22px; margin-bottom: 14px;
  box-shadow: 0 6px 20px var(--gold-glow);
}
.hero-icon {
  font-size: 3rem; flex-shrink: 0;
  animation: pulse-glow 2s ease-in-out infinite;
}
.hero-text { flex: 1; min-width: 0; }
.hero-label { font-size: .78rem; color: var(--text-dim); font-weight: 700;
              text-transform: uppercase; letter-spacing: 1.5px; }
.hero-title { font-size: 1.15rem; font-weight: 900; color: var(--text);
              margin-top: 4px; line-height: 1.3; word-wrap: break-word; }
.hero-xp-badge {
  background: var(--gold); color: var(--text); font-weight: 900;
  padding: 6px 12px; border-radius: 14px; font-size: .9rem;
  white-space: nowrap; box-shadow: 0 2px 6px var(--gold-glow);
}

/* Section nav 4 顆按鈕（取代 tabs） */
.section-nav { display: flex; gap: 8px; margin-bottom: 14px; }
div[data-testid="stHorizontalBlock"] .stButton button.section-nav-btn-active {
  background: linear-gradient(135deg, var(--red-deep), var(--red)) !important;
  color: #fff !important;
  border: 2px solid var(--gold) !important;
  box-shadow: 0 4px 14px var(--red-glow) !important;
}

/* All-quest summary 圓圖 (mini gauge for top bar) */
.mini-gauge {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 12px; background: var(--warm-card-alt);
  border-radius: 14px; font-size: .82rem; color: var(--text-dim);
}

/* ── 手機 RWD（Duolingo-style 大 tap 區）── */
@media only screen and (max-width: 768px) {
  .stButton > button {
    min-height: 60px !important;
    font-size: 1.1rem !important;
    padding: 16px 24px !important;
    border-radius: 18px !important;
    font-weight: 800 !important;
  }
  .stButton > button[kind="primary"] {
    min-height: 64px !important;
    padding: 18px 28px !important;
    font-size: 1.2rem !important;
    box-shadow: 0 6px 0 var(--red-deep) !important;  /* Duolingo 招牌「按下去陷下去」陰影 */
  }
  .stButton > button[kind="primary"]:active {
    transform: translateY(4px);
    box-shadow: 0 2px 0 var(--red-deep) !important;
  }
  .stNumberInput input, .stTextInput input, .stSelectbox select {
    font-size: 18px !important;
    min-height: 52px !important;
    border-radius: 14px !important;
  }
  .stNumberInput label, .stTextInput label, .stSelectbox label {
    font-size: 16px !important;
    font-weight: 700 !important;
  }
  .stNumberInput div[data-testid="stNumberInputStepControls"] button {
    min-width: 44px !important;
    min-height: 44px !important;
    font-size: 22px !important;
  }
  .stRadio label {
    font-size: 18px !important;
    padding: 14px 18px !important;
  }
  [data-testid="stCameraInput"] label {
    font-size: 18px !important;
    padding: 18px !important;
  }
  /* 卡片更圓潤、emoji 更大 */
  .card { border-radius: 22px !important; padding: 20px !important; }
  .level-ring { width: 72px !important; height: 72px !important; font-size: 1.6rem !important; }
  /* 關卡 5 圈 + 4 條連線必須塞進 360px iPhone */
  .game-node {
    width: 44px !important; height: 44px !important;
    font-size: 1rem !important; border-width: 2px !important;
  }
  .game-node.boss {
    width: 50px !important; height: 50px !important;
    font-size: 1.15rem !important;
  }
  .game-connector { width: 14px !important; height: 3px !important; }
  .game-row { gap: 0 !important; flex-wrap: nowrap !important;
              justify-content: center !important; }
  .game-hearts-bar { font-size: 1.6rem !important; }
  /* tabs 在手機上要可橫滑 */
  .stTabs [data-baseweb="tab-list"] {
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
  .stTabs [data-baseweb="tab"] {
    flex-shrink: 0 !important;
    padding: 14px 22px !important;
    font-size: 1rem !important;
  }
}

/* ── 超窄螢幕（小手機 ≤ 380px）關卡圈再縮小一點 ── */
@media only screen and (max-width: 380px) {
  .game-node {
    width: 38px !important; height: 38px !important;
    font-size: 0.9rem !important;
  }
  .game-node.boss {
    width: 44px !important; height: 44px !important;
    font-size: 1rem !important;
  }
  .game-connector { width: 10px !important; }
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  Session State
# ═══════════════════════════════════════════════════════════

import time as _time_for_cache


def _maybe_refresh(key: str, refresh_fn, ttl_secs: float = 60) -> None:
    """避免 Streamlit 每次 rerun 都打 API（觸發點只要按按鈕、輸入文字就 rerun）。

    same 個 ``key`` 在 ``ttl_secs`` 秒內最多只實際執行 ``refresh_fn`` 一次；
    其餘 rerun 直接跳過讓 session_state 裡的舊資料繼續用。

    使用者按下「開始挑戰」「補血」等動作後，動作端會直接呼叫 refresh_*
    helper（不走這個 wrapper），所以那條路徑不受 TTL 限制，能立刻看到變化。
    """
    last_key = f"_last_refresh_{key}"
    now = _time_for_cache.time()
    last = float(st.session_state.get(last_key, 0) or 0)
    if now - last < ttl_secs:
        return
    try:
        refresh_fn()
    except Exception:
        pass
    # 即使 API 失敗也記時間戳，避免短時間內反覆撞 cold start API
    st.session_state[last_key] = now


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
        try:
            api_client.refresh_today_log_into_session()
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
        try:
            api_client.clear_tokens()
        except Exception:
            pass
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.warning("偵測到不同網路環境，已自動登出。請重新登入。")
        st.rerun()


# ─── 自訂運動 ───

def merge_exercises():
    return {**EXERCISE_MET, **st.session_state.custom_exercises}


def add_custom_exercise(name, met, category="自訂"):
    """新增 / 更新本地自訂運動清單（後端目前不存運動字典；純 client side）。"""
    del category  # 保留 signature 相容；目前只本地存
    st.session_state.custom_exercises[name] = met
    _save_local_custom_exercises(st.session_state.custom_exercises)


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

    # 移除左上角 logo，改用更精簡的文字 header（手機友善）
    st.markdown("""
    <div style="text-align:center; margin: 4px 0 12px;">
      <span style="font-size:1.5rem; font-weight:900;
                   background:linear-gradient(135deg,#FF8A65,#FFB300);
                   -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                   font-family:'Noto Sans TC',sans-serif;
                   letter-spacing: 1px;">
        🔥 NutriGo
      </span>
    </div>""", unsafe_allow_html=True)

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
        try:
            api_client.clear_tokens()
        except Exception:
            pass
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
        "[🛒 前往NutriGo商城](https://sousville.com)  "
        "使用優惠碼 **SOUSVILLE85** 享 85 折優惠！"
    )


# ═══════════════════════════════════════════════════════════
#  頁面：身份驗證
# ═══════════════════════════════════════════════════════════

def _prewarm_backend_async():
    """背景 thread ping 後端，喚醒它而不卡 UI。

    Streamlit free tier 經常因為 cold start 第一次 API 呼叫會 502。
    這個 helper 在使用者打開 app 那一刻就背景 ping，讓使用者真的點
    「LINE 登入」/「寄送驗證碼」時後端已經醒了或正在醒。

    用 ``_backend_prewarmed_at`` session_state 旗標避免每次 rerun 都開新 thread；
    5 分鐘內最多 ping 一次。
    """
    import threading
    import time as _t
    last = float(st.session_state.get("_backend_prewarmed_at") or 0)
    if _t.time() - last < 300:  # 5 分鐘
        return
    st.session_state["_backend_prewarmed_at"] = _t.time()

    def _ping():
        try:
            import requests
            requests.get(
                f"{api_client.API_BASE_URL}/api/v1/constants/all",
                timeout=60,
            )
        except Exception:
            pass  # 失敗也 OK，使用者按 login 時再走正常路徑

    threading.Thread(target=_ping, daemon=True).start()


def _is_cold_start_error(exc) -> bool:
    """偵測 502 / 503 / 504 / 「Application Loading」HTML 等 cold start 訊號。"""
    if isinstance(exc, APIError):
        if 500 <= int(exc.status_code or 0) < 600:
            return True
    s = str(getattr(exc, "detail", None) or exc).lower()
    return any(marker in s for marker in (
        "502", "503", "504",
        "bad gateway", "service unavailable",
        "<title>502", "<title>503", "<title>504",
        "<!doctype html",
    ))


def _render_cold_start_waking_card(action_label: str = "🔄 重新嘗試"):
    """取代紅色 502 error — 友善「服務喚醒中」卡，自帶重試按鈕。"""
    st.markdown("""
    <div class="card" style="text-align:center; padding:36px 22px; margin: 20px auto;
                             max-width: 480px;
                             background: linear-gradient(135deg, rgba(255,179,0,0.10), rgba(255,138,101,0.08));
                             border: 2px solid var(--gold);">
      <div style="font-size: 3.4rem; margin-bottom: 10px;">☕</div>
      <h3 style="margin: 8px 0 14px; color: var(--text);">服務正在喚醒中…</h3>
      <p style="color:var(--text-dim); font-size:0.95rem; line-height:1.7;">
        免費方案的服務閒置太久會自動進入睡眠 💤<br>
        第一次打開要等它伸個懶腰（約 <strong>30-60 秒</strong>）<br>
        ☘️ 之後就會很快了
      </p>
    </div>
    """, unsafe_allow_html=True)

    if st.button(action_label,
                 type="primary",
                 use_container_width=True,
                 key=f"cold_start_retry_{action_label}"):
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.rerun()


def page_auth():
    """LINE Login OAuth 流程 — 已從舊版 email/Notion 切換到新後端 API。"""
    # 一進來就在背景戳醒後端（不卡 UI）— 等使用者看完文案 + 點 login 時
    # 後端已經在醒了
    _prewarm_backend_async()

    _show_logo(center=True, height=140)
    st.markdown("""
    <div style="text-align:center; padding:0 0 28px;">
      <p style="color:var(--text-dim); font-size:1.05rem;">NutriGo — 你的遊戲化健康管理夥伴</p>
    </div>""", unsafe_allow_html=True)

    # ── 1. 處理 LINE 跳回的 callback (?code=...&state=...) ──
    qp = dict(st.query_params)
    if "code" in qp:
        try:
            api_client.handle_oauth_callback(qp)
        except APIError as exc:
            if _is_cold_start_error(exc):
                _render_cold_start_waking_card("🔄 等 30 秒後重新登入")
                return
            st.error(f"登入失敗：{exc.detail}")
            try:
                st.query_params.clear()
            except Exception:
                pass
            return

        if api_client.load_user_into_session():
            st.session_state.authenticated = True
            st.session_state.login_ip = get_client_ip()
            st.success(f"歡迎，{st.session_state.user_data.get('name') or '使用者'}！")
            st.rerun()
        else:
            st.error("無法載入使用者資料，請稍後再試")
            api_client.clear_tokens()
        return

    # ── 2. 嘗試用快取的 JWT 自動恢復登入 ──
    if api_client.is_authenticated():
        if api_client.load_user_into_session():
            st.session_state.authenticated = True
            st.session_state.login_ip = get_client_ip()
            st.rerun()
        else:
            # 不 clear_tokens — 可能只是後端 cold start 或暫時 502。
            # 顯示提示讓使用者重整頁，token 還在不會被踢出。
            st.warning("後端暫時無法回應，請稍後重整頁面再試一次。")

    # ── 3. 雙路徑登入 UI：LINE / Email ──
    tab_line, tab_email = st.tabs(["🟢 LINE", "📧 Email"])

    with tab_line:
        st.markdown(
            "<p style='text-align:center; color:var(--text-dim); margin:8px 0 18px;'>"
            "用你的 LINE 帳號登入"
            "</p>",
            unsafe_allow_html=True,
        )
        if not api_client.get_line_channel_id():
            st.error("尚未設定 LINE_CHANNEL_ID，請聯絡管理員。")
        else:
            line_url = api_client.build_line_oauth_url()
            st.link_button(
                "🟢 用 LINE 登入",
                line_url,
                type="primary",
                use_container_width=True,
            )

    with tab_email:
        _render_email_login_flow()


def _render_email_login_flow():
    """Email 登入兩階段：輸 email 寄碼 → 輸碼登入。state 在 session_state。"""
    step = st.session_state.get("email_login_step", "request")

    if step == "verify":
        target_email = st.session_state.get("email_login_email", "")
        st.success(
            f"✉️ 驗證碼已寄到 **{target_email}**，10 分鐘內有效。"
        )
        with st.form("email_verify_form"):
            code = st.text_input(
                "6 位驗證碼",
                max_chars=6,
                placeholder="123456",
                help="從信箱複製過來",
            )
            c1, c2 = st.columns(2)
            with c1:
                verify_clicked = st.form_submit_button(
                    "登入", type="primary", use_container_width=True
                )
            with c2:
                back_clicked = st.form_submit_button(
                    "← 換 email", use_container_width=True
                )

        # 表單外加「重寄」按鈕（form_submit_button 一個 form 一次只能觸發一個，
        # 把 resend 拉出來才不會跟 verify / back 互相搶）
        resend_clicked = st.button(
            "🔄 沒收到？重寄一次驗證碼",
            key="resend_email_code",
            use_container_width=True,
            type="secondary",
        )

        if back_clicked:
            st.session_state.email_login_step = "request"
            st.session_state.pop("email_login_email", None)
            st.rerun()

        if resend_clicked:
            try:
                api_client.request_email_code(target_email)
                st.success("✅ 已重新寄出，請查看 Gmail（或垃圾信匣）")
            except APIError as exc:
                if _is_cold_start_error(exc):
                    st.warning("☕ 後端正在喚醒，等 30 秒再按一次重寄")
                else:
                    # 60 秒內重複申請會被 rate limit 擋下；訊息直接給使用者看
                    st.warning(f"重寄太頻繁：{exc.detail}")

        if verify_clicked:
            if not code or not code.strip():
                st.warning("請輸入驗證碼")
                return
            try:
                api_client.verify_email_code(target_email, code.strip())
            except APIError as exc:
                if _is_cold_start_error(exc):
                    _render_cold_start_waking_card("🔄 重新驗證")
                    return
                st.error(f"驗證失敗：{exc.detail}")
                return

            if api_client.load_user_into_session():
                st.session_state.authenticated = True
                st.session_state.login_ip = get_client_ip()
                # 清掉 email 流程暫存
                st.session_state.pop("email_login_step", None)
                st.session_state.pop("email_login_email", None)
                st.success(
                    f"歡迎，{st.session_state.user_data.get('name') or '使用者'}！"
                )
                st.rerun()
            else:
                # token 還在 .auth_cache.json，使用者重整頁就會走快取登入，
                # 不要在這 clear — backend cold start 常見、不該把 user 踢回 step 1。
                st.warning(
                    "登入成功但載入使用者資料超時（後端 cold start）。"
                    "請按 ⌘+R 或 F5 重整頁面，會自動完成登入。"
                )
        return

    # step == "request"
    st.markdown(
        "<p style='text-align:center; color:var(--text-dim); margin:8px 0 18px;'>"
        "輸入 email 收 6 位驗證碼，免註冊免密碼"
        "</p>",
        unsafe_allow_html=True,
    )
    with st.form("email_request_form"):
        email = st.text_input(
            "Email",
            placeholder="you@example.com",
            help="第一次用會自動建立帳號",
        )
        send_clicked = st.form_submit_button(
            "📧 寄送驗證碼", type="primary", use_container_width=True
        )

    if send_clicked:
        if not email or "@" not in email:
            st.warning("請輸入有效的 email")
            return
        try:
            api_client.request_email_code(email.strip())
        except APIError as exc:
            if _is_cold_start_error(exc):
                _render_cold_start_waking_card("🔄 重新寄送驗證碼")
                return
            st.error(f"寄送失敗：{exc.detail}")
            return
        st.session_state.email_login_step = "verify"
        st.session_state.email_login_email = email.strip()
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  頁面：個人設定
# ═══════════════════════════════════════════════════════════

def page_profile():
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

        # 把年齡 → birth_date（取當年 1/1，後端只用來算 age）
        try:
            today_d = taiwan_today()
            birth_iso = f"{today_d.year - int(float(age))}-01-01"
        except Exception:
            birth_iso = None

        try:
            updates = {
                "gender": gender,
                "height_cm": float(height),
                "weight_kg": float(weight),
                "activity_level": activity,
                "goal": goal,
            }
            if birth_iso:
                updates["birth_date"] = birth_iso
            api_client.update_profile(updates)
            # 體重變動 → 寫入 weight_history（後端會 dedupe 同日）
            try:
                api_client.record_weight(float(weight))
            except APIError:
                pass
        except APIError as exc:
            st.error(f"儲存失敗：{exc.detail}")
            return

        st.session_state.user_data.update({
            "gender": gender, "age": int(float(age)),
            "height": float(height), "weight": float(weight),
            "bmi": bmi, "bmr": round(bmr),
            "tdee": tdee, "target": target,
            "activity": activity, "goal": goal,
        })
        st.session_state.profile_complete = True
        st.success("✅ 資料已儲存！系統已幫你算好 BMR / TDEE / 目標卡路里")
        st.info("💧 提醒：之後可以隨時在「📊 數據」section 更新體重，追蹤趨勢")
        # onboarding 流程結束後讓主畫面變成 game-first 首頁
        st.session_state.pop("onboarding_step", None)
        st.session_state.pop("onboarding_quiz_idx", None)

        # 重新拉今日 log，讓 BMR/TDEE/target 由後端計算覆蓋本地估算
        api_client.refresh_today_log_into_session()
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
        try:
            history_raw = api_client.list_weight_history(limit=30)
        except APIError:
            history_raw = []
        # 後端回 [{recorded_date, weight_kg}, ...]；轉成舊版 [(date_str, kg), ...]
        history = []
        for item in history_raw:
            d = item.get("recorded_date") or item.get("date")
            w = item.get("weight_kg") or item.get("weight")
            if d and w is not None:
                history.append((str(d), float(w)))
        history.sort(key=lambda x: x[0])
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

    # ── 徽章牆 ──
    if st.session_state.profile_complete:
        st.markdown("---")
        st.markdown("### 🏅 我的徽章")
        render_badge_wall()


def _get_next_level(chapters_data, completed):
    """Walk API ``chapters_data`` and return the first level not yet completed."""
    for ch in chapters_data:
        for lv in ch["levels"]:
            if lv["id"] not in completed:
                return lv
    return None


def _render_hearts_bar():
    full = int(st.session_state.get("game_hearts", 0) or 0)
    full = max(0, min(5, full))
    empty = 5 - full
    hearts_html = '<div class="game-hearts-bar">'
    hearts_html += '<span class="heart-full">' + '❤️' * full + '</span>'
    hearts_html += '<span class="heart-empty">' + '🖤' * empty + '</span>'
    secs_left = int(st.session_state.get("hearts_seconds_to_next_regen", 0) or 0)
    if full < 5 and secs_left > 0:
        mins_left = max(1, int(secs_left / 60))
        hearts_html += (
            f'<span style="font-size:.75rem; color:var(--text-dim); margin-left:6px;">'
            f'{mins_left}分鐘後恢復 1 顆</span>'
        )
    hearts_html += '</div>'
    st.markdown(hearts_html, unsafe_allow_html=True)


def _render_game_map(chapters_data):
    completed = set(st.session_state.game_progress.get("completed", []))
    next_lv = _get_next_level(chapters_data, completed)
    next_id = next_lv["id"] if next_lv else None

    nodes_per_row = 5
    map_html = '<div class="game-map">'

    for ch in chapters_data:
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


def _render_level_stats(chapters_data):
    completed = set(st.session_state.game_progress.get("completed", []))
    all_ids = {lv["id"] for ch in chapters_data for lv in ch["levels"]}
    total_levels = len(all_ids)
    done_count = len(completed & all_ids)
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


def tab_daily_challenge():
    st.markdown("### 🎯 關卡挑戰", unsafe_allow_html=True)

    # 跟後端拉最新 game state — TTL 保護避免重複拉
    _maybe_refresh("game_state",
                   api_client.refresh_game_state_into_session, ttl_secs=30)

    try:
        # 章節結構幾乎不變，用 cache 版（5 分鐘 TTL）
        chapters_resp = api_client.get_chapters_cached()
    except APIError as exc:
        st.error(f"無法載入關卡：{exc.detail}")
        return

    chapters_data = chapters_resp.get("chapters", []) if isinstance(chapters_resp, dict) else chapters_resp
    if not chapters_data:
        st.info("目前還沒有關卡資料。")
        return

    completed = set(st.session_state.game_progress.get("completed", []))

    # ── STATE: playing a level ──
    if st.session_state.get("current_level") is not None:
        _play_level(chapters_data)
        return

    # ── STATE: map view ──
    _render_level_stats(chapters_data)
    _render_hearts_bar()

    # Refill hearts via API (花 10 XP)
    if st.session_state.game_hearts < 5 and st.session_state.total_xp >= 10:
        if st.button("💔 花 10 XP 補滿 ❤️×5", use_container_width=True):
            try:
                api_client.refill_hearts()
            except APIError as exc:
                st.error(f"補血失敗：{exc.detail}")
                return
            api_client.refresh_game_state_into_session()
            st.rerun()

    st.markdown("---")
    _render_game_map(chapters_data)

    next_lv = _get_next_level(chapters_data, completed)
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
                st.session_state.level_answers = []
                st.session_state.pop("current_level_data", None)
                st.rerun()
    else:
        st.markdown('''
        <div class="quiz-card" style="text-align:center; padding:44px;">
          <div style="font-size:3rem; margin-bottom:10px;">🏆</div>
          <h3 style="color:#FFB300;">恭喜全部通關！</h3>
          <p style="color:var(--text-dim);">你是健康知識達人！</p>
        </div>''', unsafe_allow_html=True)


def _play_level(chapters_data):
    level_id = st.session_state.current_level

    # 載一次該關完整題目（含答案 + 解釋）並 cache 在 session_state
    level = st.session_state.get("current_level_data")
    if not level or level.get("id") != level_id:
        try:
            level = api_client.get_level(int(level_id))
        except APIError as exc:
            st.error(f"無法載入關卡：{exc.detail}")
            st.session_state.current_level = None
            return
        st.session_state.current_level_data = level

    questions = level.get("questions") or []
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
        _finish_level(level)
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
        # 紀錄答案，最後 submit 一次
        answers_so_far = list(st.session_state.get("level_answers") or [])
        answers_so_far.append(int(selected))
        st.session_state.level_answers = answers_so_far

        is_correct = (selected == q["answer"])
        if is_correct:
            st.session_state.level_correct += 1
            st.success(f"✅ 正確！{q['explanation']}")
        else:
            # 本地 hearts 顯示先扣（後端 submit 時還會做一次權威結算）
            st.session_state.game_hearts = max(0, int(st.session_state.game_hearts) - 1)
            st.error(f"❌ 答錯了！正確答案：{q['options'][q['answer']]}")
            st.markdown(f"📖 {q['explanation']}")

        st.session_state.level_q_idx = q_idx + 1
        st.rerun()


def _finish_level(level):
    answers = list(st.session_state.get("level_answers") or [])
    if not answers:
        st.session_state.current_level = None
        st.rerun()
        return

    try:
        result = api_client.submit_level(int(level["id"]), answers)
    except APIError as exc:
        st.error(f"提交失敗：{exc.detail}")
        return

    # 把後端結果寫進 session_state（權威來源）
    correct = int(result.get("correct_count", 0))
    total_q = int(result.get("total_questions", len(answers)))
    passed = bool(result.get("passed"))
    reward = int(result.get("reward_xp", 0) or 0)
    is_boss = bool(result.get("boss_completed"))
    new_hearts = result.get("hearts")
    if new_hearts is not None:
        st.session_state.game_hearts = int(new_hearts)

    # 同步整個 game state（completed_levels / xp / level / 倒數秒數）
    api_client.refresh_game_state_into_session()

    if passed:
        st.session_state.daily_quiz_done = True
        st.session_state.today_quiz_xp = reward

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

        # BOSS 通過 → 後端可能發了折扣碼，跳優惠券 popup
        issued = result.get("discount_code_issued")
        if is_boss or issued:
            st.session_state.coupon_unlocked = True
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
        st.session_state.pop("current_level_data", None)
        st.session_state.pop("level_answers", None)
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  Tab 2：飲食紀錄
# ═══════════════════════════════════════════════════════════

def tab_diet_record():
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
                    try:
                        api_client.create_meal(
                            meal_type="snack",
                            name=food_name,
                            calories=cal_int,
                            source="gemini",
                        )
                    except APIError as exc:
                        st.error(f"紀錄失敗：{exc.detail}")
                        return
                    st.session_state.pop("ai_result", None)
                    api_client.refresh_today_log_into_session()
                    new_total = int(st.session_state.get("today_cal_in", 0) or 0)
                    target_kcal = int(st.session_state.user_data.get("target") or 2000)
                    st.success(
                        f"✅ AI 辨識已紀錄：**{food_name} {cal_int} kcal**\n\n"
                        f"📊 今日累計攝取：**{new_total} / {target_kcal} kcal**"
                    )
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
            try:
                api_client.create_meal(
                    meal_type="snack",
                    name=bento_name,
                    calories=int(bento_cal),
                    source="bento",
                    bento_key=bento_name,
                    portions={
                        "蔬菜": float(bento_fiber or 0),
                        "油脂": float(bento_fat or 0),
                    },
                )
            except APIError as exc:
                st.error(f"紀錄失敗：{exc.detail}")
                return
            api_client.refresh_today_log_into_session()
            new_total = int(st.session_state.get("today_cal_in", 0) or 0)
            target_kcal = int(st.session_state.user_data.get("target") or 2000)
            st.success(
                f"✅ 已紀錄：**{bento_name} {bento_cal} kcal**\n\n"
                f"📊 今日累計攝取：**{new_total} / {target_kcal} kcal**"
            )
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
            portions_payload = {keys[i]: float(vals[i]) for i in range(len(keys))}
            try:
                api_client.create_meal(
                    meal_type="snack",
                    name="手動份量",
                    calories=int(manual_cal),
                    source="custom",
                    portions=portions_payload,
                )
            except APIError as exc:
                st.error(f"紀錄失敗：{exc.detail}")
                return
            api_client.refresh_today_log_into_session()
            new_total = int(st.session_state.get("today_cal_in", 0) or 0)
            target_kcal = int(st.session_state.user_data.get("target") or 2000)
            st.success(
                f"✅ 已紀錄：**手動份量 {manual_cal} kcal**\n\n"
                f"📊 今日累計攝取：**{new_total} / {target_kcal} kcal**"
            )
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

def tab_exercise_record():
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
        try:
            api_client.create_exercise(
                name=ex_name,
                met=float(met),
                duration_min=int(duration),
                intensity="中強度",
            )
        except APIError as exc:
            st.error(f"紀錄失敗：{exc.detail}")
            return
        api_client.refresh_today_log_into_session()
        new_burned = int(st.session_state.get("today_cal_out", 0) or 0)
        log_text = f"{ex_name} MET {met} {duration}分 ({est_cal} kcal)"
        st.success(
            f"✅ 已紀錄：**{log_text}**\n\n"
            f"🔥 今日累計消耗：**{new_burned} kcal**"
        )
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

def tab_calorie_deficit():
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


# ═══════════════════════════════════════════════════════════
#  Theme Sprint widget（5 天主題挑戰，友善鼓勵語氣）
# ═══════════════════════════════════════════════════════════

def _theme_progress_bar(filled: int, total: int) -> str:
    filled = max(0, min(filled, total))
    return "●" * filled + "○" * (total - filled)


def render_theme_widget():
    """首頁頂部的「本期主題」進度卡。

    友善設計：
    - 沒 active run → 顯示「下一期推薦 + 開始按鈕」
    - 有 active run + 走順 → 「繼續加油 X/N」
    - 有 active run + 已斷 streak → 「沒關係，碎片繼續累積」
    - 已 5/5 滿分 → 「太厲害了！等待結算」
    """
    data = st.session_state.get("active_theme") or {}

    if not data:
        # 第一次顯示（剛載入），先拉一次
        if api_client.refresh_active_theme_into_session():
            data = st.session_state.get("active_theme") or {}

    # 防禦性邏輯：只看 run_id 來決定渲染哪一條 path
    # （之前看 has_active 預設 True 會導致 API 失敗時走錯 branch）
    has_run = bool(data.get("run_id"))

    # ── 沒 active run → 顯示「開始下一期」CTA ──
    if not has_run:
        next_theme = data.get("next_theme") or {}
        encouragement = data.get("encouragement", "")

        # 全部通關 (next_theme is null but server confirmed)
        if data and "next_theme" in data and next_theme is None:
            st.markdown(f"""
            <div class="card" style="text-align:center; padding:20px; margin-bottom:14px;
                                     background:linear-gradient(135deg, rgba(255,179,0,0.10), rgba(255,107,53,0.06));">
              <div style="font-size:2rem; margin-bottom:6px;">🏆</div>
              <div style="color:var(--text); font-weight:700;">{encouragement or "你已經把所有主題都通關了，太厲害了！"}</div>
            </div>""", unsafe_allow_html=True)
            return

        # 後端 down / 還在 cold start：用 fiber 當 default 介紹（不會卡住 UI）
        if not next_theme:
            next_theme = {
                "icon": "🥦",
                "title": "膳食纖維週",
                "description": "連續 5 天蔬菜吃 5 份、全穀根莖 6 份，腸道菌會跟你說謝謝",
            }
            encouragement = encouragement or "歡迎挑戰你的第一期主題 🚀"

        icon = next_theme.get("icon", "🎯")
        title = next_theme.get("title", "")
        desc = next_theme.get("description", "")
        st.markdown(f"""
        <div class="card" style="padding:20px; margin-bottom:14px;
                                 background:linear-gradient(135deg, rgba(255,138,101,0.10), rgba(255,179,0,0.14));
                                 border:2px solid var(--gold);">
          <div style="display:flex; align-items:center; gap:14px; margin-bottom:10px;">
            <div style="font-size:2.6rem;">{icon}</div>
            <div style="flex:1;">
              <div style="font-weight:900; font-size:1.15rem; color:var(--text);">下一期主題：{title}</div>
              <div style="color:var(--text-dim); font-size:.88rem; margin-top:4px; line-height:1.4;">{desc}</div>
            </div>
          </div>
          <div style="color:var(--text); font-size:.92rem; margin:10px 0; padding:10px;
                      background:rgba(255,255,255,0.7); border-radius:12px; text-align:center;">
            {encouragement}
          </div>
        </div>""", unsafe_allow_html=True)
        if st.button(f"🚀 開始挑戰 {title}", key="start_next_theme",
                     type="primary", use_container_width=True):
            try:
                api_client.start_next_theme()
                api_client.refresh_active_theme_into_session()
                st.success("開始囉！第一片徽章在等你 ✨")
                st.rerun()
            except APIError as exc:
                st.warning(f"開新主題遇到問題：{exc.detail}（可以稍後再試）")
        return

    # 有 active run
    theme = data.get("theme") or {}
    icon = theme.get("icon", "🎯")
    title = theme.get("title", "")
    duration = int(data.get("duration_days", 5))
    days = data.get("days") or []
    days_achieved = int(data.get("days_achieved", 0) or 0)
    streak_broken = bool(data.get("streak_broken", False))
    encouragement = data.get("encouragement", "")
    today_idx = len(days)

    progress_dots = _theme_progress_bar(today_idx, duration)

    # 計算今天進度（最新一筆）
    today_row = days[-1] if days else None
    today_metric_html = ""
    if today_row:
        mv = today_row.get("metric_value")
        mt = today_row.get("metric_target")
        if mv is not None and mt:
            pct = min(float(mv) / float(mt), 1.0) * 100 if mt else 0
            color = "var(--green)" if today_row.get("achieved") else "var(--gold)"
            today_metric_html = f"""
            <div style="margin-top:10px;">
              <div style="display:flex; justify-content:space-between; font-size:.82rem; color:var(--text-dim); margin-bottom:4px;">
                <span>今天進度</span>
                <span><strong style="color:{color};">{mv:.1f}</strong> / {mt:.1f}</span>
              </div>
              <div style="height:8px; background:rgba(27,157,158,0.1); border-radius:4px; overflow:hidden;">
                <div style="width:{pct}%; height:100%; background:linear-gradient(90deg, var(--blue), var(--blue-light)); transition:width .4s;"></div>
              </div>
            </div>"""

    # 達標天數的「碎片」視覺化
    pieces_html = ""
    for i in range(duration):
        achieved = i < len(days) and days[i].get("achieved")
        if achieved:
            pieces_html += '<span style="font-size:1.4rem;">🧩</span>'
        elif i < today_idx:
            pieces_html += '<span style="font-size:1.4rem; opacity:0.3;">⬜</span>'
        else:
            pieces_html += '<span style="font-size:1.4rem; opacity:0.4;">⬜</span>'

    bg_gradient = (
        "linear-gradient(135deg, rgba(67,160,71,0.10), rgba(27,157,158,0.08))"
        if not streak_broken
        else "linear-gradient(135deg, rgba(255,179,0,0.10), rgba(255,87,34,0.06))"
    )

    st.markdown(f"""
    <div class="card" style="padding:18px; margin-bottom:14px; background:{bg_gradient};">
      <div style="display:flex; align-items:center; gap:12px;">
        <div style="font-size:2rem;">{icon}</div>
        <div style="flex:1;">
          <div style="font-weight:900; font-size:1.05rem; color:var(--text);">本期主題：{title}</div>
          <div style="color:var(--text-dim); font-size:.82rem; margin-top:2px;">
            Day {today_idx}/{duration} &nbsp;{progress_dots}
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:.75rem; color:var(--text-dim);">徽章碎片</div>
          <div style="font-weight:900; color:var(--blue); font-size:1.1rem;">{days_achieved} / {duration}</div>
        </div>
      </div>

      <div style="margin-top:12px; text-align:center; letter-spacing:6px;">
        {pieces_html}
      </div>

      {today_metric_html}

      <div style="margin-top:12px; padding:10px 12px; background:rgba(255,255,255,0.6);
                  border-radius:10px; font-size:.88rem; color:var(--text); text-align:center;">
        {encouragement}
      </div>
    </div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
#  徽章牆（Profile 頁底部）
# ═══════════════════════════════════════════════════════════

def render_badge_wall():
    """Profile 頁底部顯示已收集的主題徽章。"""
    try:
        badges = api_client.list_badges()
    except APIError:
        badges = []

    if not badges:
        st.markdown(
            "<div style='color:var(--text-dim); text-align:center; padding:20px;'>"
            "🌱 還沒有徽章，完成主題挑戰就會收集到這裡！"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    cols = st.columns(min(len(badges), 4) or 1)
    THEME_LABELS = {
        "fiber":    ("🥦", "纖維大師"),
        "protein":  ("💪", "蛋白質達人"),
        "exercise": ("🏃", "運動行家"),
        "deficit":  ("🔥", "赤字王者"),
    }
    for i, b in enumerate(badges):
        icon, label = THEME_LABELS.get(b.get("theme_key", ""), ("🏅", b.get("theme_key", "")))
        pieces = int(b.get("pieces_earned", 0) or 0)
        completed = b.get("completed")
        opacity = "1" if completed else f"{0.3 + 0.14 * pieces}"
        ribbon = ""
        if completed:
            ribbon = '<div style="position:absolute; top:6px; right:6px; font-size:.7rem; color:var(--green);">✨ 完整</div>'
        with cols[i % len(cols)]:
            st.markdown(f"""
            <div class="card" style="text-align:center; padding:16px 8px; position:relative; opacity:{opacity};">
              {ribbon}
              <div style="font-size:2.4rem;">{icon}</div>
              <div style="font-weight:700; margin-top:4px;">{label}</div>
              <div style="font-size:.78rem; color:var(--text-dim); margin-top:2px;">
                {pieces}/5 碎片
              </div>
            </div>""", unsafe_allow_html=True)


ONBOARDING_QUESTIONS = [
    {
        "topic": "🔥 BMR（基礎代謝率）",
        "question": "BMR 是什麼？",
        "options": [
            "你一天總共消耗多少熱量",
            "你完全休息時，身體運作所需要的最低熱量",
            "你運動時消耗的熱量",
            "你吃進去的熱量",
        ],
        "answer": 1,
        "explanation": (
            "BMR (Basal Metabolic Rate) 是你完全躺著不動時，身體維持心跳、"
            "呼吸、體溫等基本機能消耗的熱量。通常占一天總消耗的 60-70%。"
        ),
    },
    {
        "topic": "📏 BMI（身體質量指數）",
        "question": "BMI 怎麼算？",
        "options": [
            "體重(kg) / 身高(m)²",
            "體重(kg) × 身高(m)",
            "腰圍 / 臀圍",
            "體脂肪 / 體重",
        ],
        "answer": 0,
        "explanation": (
            "BMI = 體重(kg) / 身高(m)² → 例如 60kg / 1.65² ≈ 22。"
            "正常範圍 18.5-24，但 BMI 不分肌肉脂肪，肌肉量大的人 BMI 可能偏高。"
        ),
    },
    {
        "topic": "⚡ TDEE（每日總消耗）",
        "question": "TDEE 跟 BMR 有什麼差別？",
        "options": [
            "TDEE 跟 BMR 是一樣的東西",
            "TDEE = BMR + 你日常活動 / 運動的消耗",
            "TDEE 只算運動消耗",
            "TDEE 比 BMR 小",
        ],
        "answer": 1,
        "explanation": (
            "TDEE = BMR × 活動係數。久坐 1.2 倍、輕度活動 1.375 倍、中度 1.55 倍…等。"
            "想減重 → 每天攝取 < TDEE 就會有熱量赤字。"
        ),
    },
    {
        "topic": "📉 熱量赤字",
        "question": "想要健康減 1 公斤，大約需要累積多少熱量赤字？",
        "options": [
            "1000 大卡",
            "3500 大卡",
            "7700 大卡",
            "15000 大卡",
        ],
        "answer": 2,
        "explanation": (
            "1 公斤脂肪 ≈ 7700 大卡。如果每天少吃 / 多動 500 卡，"
            "大約 15-16 天可以減 1 公斤（不要太快，肌肉會掉太多）。"
        ),
    },
]


# ═══════════════════════════════════════════════════════════
#  Onboarding 流程（新使用者引導）
# ═══════════════════════════════════════════════════════════

def _clear_onboarding_state():
    """清掉 onboarding 全部 session_state（退出預覽 / 完成時用）。"""
    for k in ("show_onboarding", "onboarding_step", "onboarding_quiz_idx"):
        st.session_state.pop(k, None)
    for i in range(len(ONBOARDING_QUESTIONS)):
        st.session_state.pop(f"ob_q{i}_answered", None)
        st.session_state.pop(f"ob_q{i}_selected", None)


def page_onboarding(is_preview: bool = False):
    """新使用者引導：Welcome → BMR/TDEE Quiz 教學 → Summary → Profile。

    is_preview=True 表示老使用者按「🎓 重看引導教學」進來預覽，最後一步不會
    跳到真的 profile 表單（避免改到既有資料），改顯示「預覽結束」卡片。
    """
    step = st.session_state.get("onboarding_step", "welcome")

    if step == "welcome":
        _render_onboarding_welcome()
    elif step == "quiz":
        _render_onboarding_quiz()
    elif step == "summary":
        _render_onboarding_summary()
    elif step == "profile":
        if is_preview:
            _render_onboarding_preview_end()
        else:
            _render_onboarding_profile()
    else:
        # 未知狀態 → 回 welcome
        st.session_state.onboarding_step = "welcome"
        st.rerun()


def _render_onboarding_preview_end():
    """預覽模式結束卡（避免老使用者被導去 profile 頁）。"""
    st.markdown("""
    <div class="card" style="text-align:center; padding:32px 22px; margin:18px 0;
                             background: linear-gradient(135deg, rgba(67,160,71,0.10), rgba(255,179,0,0.16));
                             border: 2px solid var(--success);">
      <div style="font-size:3.6rem;">🎬✨</div>
      <h2 style="margin:8px 0 14px;">預覽結束！</h2>
      <p style="color:var(--text); font-size:1rem; line-height:1.6;">
        新使用者走到這一步會進到 <strong>📝 填資料</strong> 頁面，<br>
        系統會幫他用身高體重算出 BMR / TDEE / 目標卡路里。
      </p>
      <p style="color:var(--text-dim); font-size:.9rem; margin-top:16px; line-height:1.6;">
        因為你已經是老使用者，按下「返回主畫面」回到遊戲首頁就好 🎮
      </p>
    </div>
    """, unsafe_allow_html=True)

    if st.button("← 返回主畫面", type="primary", use_container_width=True,
                 key="onboarding_preview_done"):
        _clear_onboarding_state()
        st.rerun()


def _render_onboarding_welcome():
    """Step 1: 歡迎卡 + 兩個選項。"""
    st.markdown("""
    <div class="card" style="text-align:center; padding:36px 22px; margin: 18px 0;
                             background: linear-gradient(135deg, rgba(255,179,0,0.14), rgba(255,138,101,0.10));
                             border: 2px solid var(--gold);">
      <div style="font-size:3.6rem; margin-bottom:8px;">🎉</div>
      <h2 style="margin:8px 0 14px;">歡迎來到NutriGo！</h2>
      <p style="color:var(--text); font-size:1rem; margin: 12px 0; line-height:1.6;">
        在開始填資料前，先花 <strong style="color:var(--red-deep);">5 分鐘</strong>
        學什麼是 <strong style="color:var(--red-deep);">BMR / BMI / TDEE</strong>？
      </p>
      <p style="color:var(--text-dim); font-size:.9rem; line-height:1.6;">
        知道這些之後，你會更清楚為什麼系統需要你的身高體重，<br>
        而且還能拿到第一批 XP！🏆
      </p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶️ 先學 5 分鐘（推薦）",
                     type="primary", use_container_width=True,
                     key="onboarding_start_learn"):
            st.session_state.onboarding_step = "quiz"
            st.session_state.onboarding_quiz_idx = 0
            # 清掉每題的暫存（避免從上次卡關狀態繼續）
            for i in range(len(ONBOARDING_QUESTIONS)):
                st.session_state.pop(f"ob_q{i}_answered", None)
                st.session_state.pop(f"ob_q{i}_selected", None)
            st.rerun()
    with c2:
        if st.button("⏭️ 直接填資料",
                     use_container_width=True,
                     key="onboarding_skip_to_profile"):
            st.session_state.onboarding_step = "profile"
            st.rerun()


def _render_onboarding_quiz():
    """Step 2: 跑 4 題教學 quiz。"""
    idx = int(st.session_state.get("onboarding_quiz_idx", 0))
    total = len(ONBOARDING_QUESTIONS)

    if idx >= total:
        st.session_state.onboarding_step = "summary"
        st.rerun()
        return

    q = ONBOARDING_QUESTIONS[idx]
    pct = idx / total * 100

    # 進度條
    st.markdown(f"""
    <div style="margin-bottom:14px;">
      <div style="display:flex; justify-content:space-between;
                  font-size:.85rem; color:var(--text-dim); margin-bottom:4px;">
        <span>{q['topic']}</span>
        <span>第 {idx+1} / {total} 題</span>
      </div>
      <div class="status-xp-track">
        <div class="status-xp-fill" style="width:{pct:.0f}%"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="quiz-card" style="padding:24px 28px; margin-bottom:14px;">
      <h3 style="font-size:1.1rem; margin:0;">{q['question']}</h3>
    </div>
    """, unsafe_allow_html=True)

    answered = st.session_state.get(f"ob_q{idx}_answered", False)

    if not answered:
        choice = st.radio(
            "選擇答案",
            range(len(q["options"])),
            format_func=lambda i: q["options"][i],
            key=f"ob_q{idx}_radio",
            label_visibility="collapsed",
        )
        if st.button("確認答案", type="primary", use_container_width=True,
                     key=f"ob_q{idx}_confirm"):
            st.session_state[f"ob_q{idx}_answered"] = True
            st.session_state[f"ob_q{idx}_selected"] = int(choice)
            st.rerun()
    else:
        selected = int(st.session_state.get(f"ob_q{idx}_selected", -1))
        correct = (selected == q["answer"])
        if correct:
            st.success("✅ 答對了！")
        else:
            st.info(f"💡 正確答案：**{q['options'][q['answer']]}**")
        st.markdown(f"""
        <div style="background:rgba(255,179,0,0.12);
                    border-left: 4px solid var(--gold);
                    padding: 14px 18px; border-radius: 12px; margin: 12px 0;
                    font-size:.95rem; line-height: 1.6;">
          📖 {q['explanation']}
        </div>
        """, unsafe_allow_html=True)

        next_label = "看總結 →" if idx >= total - 1 else "下一題 →"
        if st.button(next_label, type="primary", use_container_width=True,
                     key=f"ob_q{idx}_next"):
            st.session_state.onboarding_quiz_idx = idx + 1
            st.rerun()


def _render_onboarding_summary():
    """Step 3: 知識總結卡 + 進入 profile 按鈕。"""
    st.markdown("""
    <div class="card" style="text-align:center; padding:32px 22px; margin: 18px 0;
                             background: linear-gradient(135deg, rgba(67,160,71,0.10), rgba(255,179,0,0.16));
                             border: 2px solid var(--success);">
      <div style="font-size:3.6rem;">🎓✨</div>
      <h2 style="margin:8px 0 18px;">太棒了，你學到了：</h2>
      <ul style="text-align:left; max-width:380px; margin: 0 auto 18px;
                 font-size:1rem; line-height:2.2; color: var(--text); padding-left: 4px;">
        <li>🔥 <strong>BMR</strong> — 你身體基本運作的熱量</li>
        <li>📏 <strong>BMI</strong> — 身材標準化指標</li>
        <li>⚡ <strong>TDEE</strong> — 一天總消耗 = BMR × 活動量</li>
        <li>📉 <strong>熱量赤字</strong> — 7700 卡 ≈ 1 kg 體重</li>
      </ul>
      <p style="color:var(--text-dim); margin-top: 14px; font-size:.92rem; line-height:1.6;">
        現在系統會用你的資料幫你算出個人化目標！<br>
        BMR / TDEE / 目標卡路里全自動算給你 🎯
      </p>
    </div>
    """, unsafe_allow_html=True)

    if st.button("📝 開始填資料", type="primary", use_container_width=True,
                 key="onboarding_to_profile"):
        st.session_state.onboarding_step = "profile"
        st.rerun()


def _render_onboarding_profile():
    """Step 4: 包裝 page_profile，加上 onboarding header + 體重提醒小卡。"""
    st.markdown("""
    <div style="text-align:center; padding: 14px 0 8px;">
      <div style="display:inline-block; background: linear-gradient(135deg, var(--gold), var(--orange));
                  color: #fff; padding: 6px 18px; border-radius: 20px;
                  font-weight: 800; font-size: .88rem; letter-spacing: 1px;">
        最後一步 — 填基本資料
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 體重隨時可改的提醒小卡（放在 profile 表單上方）
    st.markdown("""
    <div class="card" style="padding:14px 18px; margin: 12px 0 18px;
                             background: rgba(255,179,0,0.10);
                             border: 1px solid rgba(255,179,0,0.3);">
      <div style="display:flex; align-items:center; gap:12px;">
        <div style="font-size:1.6rem;">💧</div>
        <div style="font-size:.9rem; color:var(--text); line-height:1.5;">
          <strong>體重會變動，沒關係！</strong>
          填好之後還能<strong style="color:var(--red-deep);">隨時在「📊 數據」頁更新</strong>，
          系統會幫你追蹤體重曲線、看趨勢。
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    page_profile()


def render_top_status_bar():
    """頂部精簡狀態條：Lv pill + 名字 + XP bar + Hearts。

    取代舊版 sidebar 把所有狀態擠在左邊的設計。手機桌面通用。
    """
    ud = st.session_state.user_data or {}
    name = ud.get("name") or "玩家"
    xp = int(st.session_state.get("total_xp", 0) or 0)
    lv = get_level(xp)
    cur_xp, next_xp = get_next_level_xp(xp)
    pct = min((xp - cur_xp) / max(1, next_xp - cur_xp), 1.0) * 100
    hearts = int(st.session_state.get("game_hearts", 5) or 5)
    hearts = max(0, min(5, hearts))
    hearts_html = "❤️" * hearts + "🖤" * (5 - hearts)

    st.markdown(f"""
    <div class="top-status-bar">
      <div class="status-level-pill">Lv.{lv}</div>
      <span class="status-name">{name}</span>
      <div class="status-xp-section">
        <div class="status-xp-track">
          <div class="status-xp-fill" style="width:{pct:.1f}%"></div>
        </div>
        <div class="status-xp-text">{xp} / {next_xp} XP</div>
      </div>
      <div class="status-hearts">{hearts_html}</div>
    </div>
    """, unsafe_allow_html=True)


def render_section_nav() -> str:
    """4 顆 section button 取代 st.tabs。

    回當前 section key（'challenge' / 'diet' / 'exercise' / 'stats'）。
    預設 challenge — 讓「遊戲」是首頁主角。
    """
    section = st.session_state.get("home_section", "challenge")
    options = [
        ("challenge", "🎯 挑戰"),
        ("diet",      "🍽️ 飲食"),
        ("exercise",  "🏃 運動"),
        ("stats",     "📊 數據"),
    ]
    cols = st.columns(len(options))
    for i, (key, label) in enumerate(options):
        is_active = (section == key)
        with cols[i]:
            btn = st.button(
                label,
                key=f"section_nav_{key}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            )
            if btn and not is_active:
                st.session_state.home_section = key
                # scope="fragment" 讓 fragment 重跑就好（不重跑整個 main）
                try:
                    st.rerun(scope="fragment")
                except TypeError:
                    # 老版 Streamlit 沒 scope 參數 — fallback 全頁 rerun
                    st.rerun()
    return section


def render_challenge_section():
    """Challenge section 的內容 — hero 「下一關」CTA + 遊戲地圖 + Quiz。

    把舊版 ``tab_daily_challenge`` 升級為「首頁主角」：上方加 hero next-level 卡
    讓使用者一眼看到「下一個任務 + 開始按鈕」。
    """
    # 重用既有 tab_daily_challenge 的 quiz / map 邏輯
    tab_daily_challenge()


def render_sidebar_slim():
    """簡化版 sidebar — 主要狀態移到 top status bar，這裡只放設定 / 登出。"""
    # 優先顯示 logo 圖片（assets/logo.png）；沒有的話 fallback 到漸層文字
    if LOGO_PATH.exists():
        cols = st.columns([1, 4, 1])
        with cols[1]:
            st.image(str(LOGO_PATH), use_container_width=True)
    else:
        st.markdown("""
        <div style="text-align:center; margin: 4px 0 12px;">
          <span style="font-size:1.5rem; font-weight:900;
                       background:linear-gradient(135deg,#FF8A65,#FFB300);
                       -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                       font-family:'Noto Sans TC',sans-serif;
                       letter-spacing: 1px;">
            🔥 NutriGo
          </span>
        </div>""", unsafe_allow_html=True)

    if st.session_state.profile_complete:
        mood = get_dolphin_mood()
        st.markdown(_svg_dolphin(mood, size=72), unsafe_allow_html=True)
        msg = get_dolphin_message(mood)
        st.markdown(f'<div class="mascot-speech" style="text-align:center; '
                    f'font-size:.85rem; color:var(--text-dim); padding:8px 6px; '
                    f'line-height:1.5;">{msg}</div>', unsafe_allow_html=True)

    st.markdown("---")

    if st.button("⚙️ 個人設定", use_container_width=True, type="secondary",
                 key="sidebar_profile"):
        st.session_state["show_profile"] = True
        st.rerun()
    if st.button("📝 運動項目新增", use_container_width=True, type="secondary",
                 key="sidebar_exmgr"):
        st.session_state["show_exercise_mgr"] = True
        st.rerun()
    if st.button("🎓 重看引導教學", use_container_width=True, type="secondary",
                 key="sidebar_replay_onboarding",
                 help="重新看一次 BMR / TDEE 教學（不會改你的資料）"):
        _clear_onboarding_state()
        st.session_state["show_onboarding"] = True
        st.session_state["onboarding_step"] = "welcome"
        st.session_state["onboarding_quiz_idx"] = 0
        st.rerun()

    st.markdown("---")
    if st.button("登出", use_container_width=True, type="secondary",
                 key="sidebar_logout"):
        try:
            api_client.clear_tokens()
        except Exception:
            pass
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


def main():
    init_session_state()

    if not st.session_state.authenticated:
        page_auth()
        return

    check_ip_change()
    check_daily_reset()

    # 同步狀態：用 TTL 保護避免每個 button click 都打 4 個 API
    # 60 秒內最多只跑一次；按鈕動作完後該動作端會自己 explicit refresh
    if not st.session_state.get("today_log_id"):
        _maybe_refresh("today_log",
                       api_client.refresh_today_log_into_session, ttl_secs=60)
    _maybe_refresh("active_theme",
                   api_client.refresh_active_theme_into_session, ttl_secs=60)
    _maybe_refresh("game_state",
                   api_client.refresh_game_state_into_session, ttl_secs=60)

    # 簡化 sidebar — 主要狀態移到 top bar
    with st.sidebar:
        render_sidebar_slim()

    # 子頁面：個人設定 / 運動項目管理
    if st.session_state.get("show_profile"):
        if st.button("← 返回首頁", key="profile_back_top"):
            st.session_state.pop("show_profile", None)
            st.rerun()
        page_profile()
        return

    if st.session_state.get("show_exercise_mgr"):
        if st.button("← 返回首頁", key="exmgr_back_top"):
            st.session_state.pop("show_exercise_mgr", None)
            st.rerun()
        page_exercise_manager()
        return

    # 🎓 重看引導教學（preview 模式 — 老使用者也能體驗）
    if st.session_state.get("show_onboarding"):
        if st.button("← 退出預覽", key="onboarding_back_top",
                     type="secondary"):
            _clear_onboarding_state()
            st.rerun()
        st.caption("🎓 預覽模式 — 你已是老使用者，這只是讓你看流程，不會改到資料")
        page_onboarding(is_preview=True)
        return

    # Profile 沒填完 → 走 onboarding 流程（welcome → quiz → summary → profile）
    if not st.session_state.profile_complete:
        page_onboarding()
        return

    # ── Game-first 首頁 ──
    render_top_status_bar()         # 頂部 Lv/XP/Hearts 條
    render_theme_widget()           # 5 天主題 widget（修：之前根本沒被 call）

    # 把 section nav + content 包進 fragment，section 切換不會重跑整個
    # main()。Streamlit 1.37+ 的 @st.fragment 讓這個 function 內的互動只
    # 觸發 fragment 重跑（不影響 top status bar / theme widget）。
    _render_home_sections()


@st.fragment
def _render_home_sections():
    """Section nav + 對應 section 內容（fragment 加速切換）。"""
    section = render_section_nav()

    if section == "challenge":
        render_challenge_section()
    elif section == "diet":
        tab_diet_record()
    elif section == "exercise":
        tab_exercise_record()
    elif section == "stats":
        # 快速更新體重 widget（折疊起來，要用才展開，不擋主畫面）
        with st.expander("📏 更新今日體重", expanded=False):
            cur_weight = float(
                st.session_state.user_data.get("weight") or 70
            )
            wc1, wc2 = st.columns([2, 1])
            with wc1:
                new_weight = st.number_input(
                    "今日體重 (kg)",
                    min_value=30.0, max_value=300.0,
                    value=cur_weight,
                    step=0.1, format="%.1f",
                    key="quick_weight_input",
                )
            with wc2:
                st.markdown("<div style='height:28px;'></div>",
                            unsafe_allow_html=True)
                if st.button("💾 紀錄", type="primary",
                             use_container_width=True,
                             key="quick_weight_save"):
                    if abs(new_weight - cur_weight) < 0.01:
                        st.info("體重沒變動，不用紀錄 😊")
                    else:
                        try:
                            api_client.update_profile({"weight_kg": float(new_weight)})
                            try:
                                api_client.record_weight(float(new_weight))
                            except APIError:
                                pass
                            st.session_state.user_data["weight"] = float(new_weight)
                            api_client.refresh_today_log_into_session()
                            delta = new_weight - cur_weight
                            sign = "+" if delta > 0 else ""
                            st.success(
                                f"✅ 已更新體重 {new_weight:.1f} kg "
                                f"（{sign}{delta:.1f} kg）"
                            )
                        except APIError as exc:
                            st.error(f"更新失敗：{exc.detail}")

        render_top_dashboard()      # 儀表板（gauges + dolphin advisor）
        st.markdown("---")
        tab_calorie_deficit()       # 熱量赤字總覽


if __name__ == "__main__":
    main()
