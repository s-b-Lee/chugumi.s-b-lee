# app.py
import base64
import json
import secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

# -----------------------------
# Page
# -----------------------------
st.set_page_config(
    page_title="🫧이미지 레시피 - 직접 설계하는 내 이미지",
    page_icon="✨",
    layout="wide",
)

# -----------------------------
# Constants
# -----------------------------
PINTEREST_BASE = "https://api.pinterest.com/v5"
PINTEREST_AUTH_URL = "https://www.pinterest.com/oauth/"
PINTEREST_TOKEN_URL = f"{PINTEREST_BASE}/oauth/token"

STYLE_KEYWORDS = [
    "세련됨",
    "우아함",
    "여성스러움",
    "중성적인",
    "절제된",
    "귀여움",
    "청순함",
    "강렬한",
    "섹시한",
    "무채색의",
    "시크함",
    "고급스러움",
    "섹시함",
    "러블리",
    "단아한",
    "단정한",
]

PRIVACY_NOTICE = (
    "⚠️ **고지**: 이 앱은 의료/심리 **진단**을 제공하지 않습니다. "
    "자해/자살 등 위기 상황이 있거나 안전이 우려되면, 즉시 112/119 또는 "
    "가까운 응급실/전문기관의 도움을 받으세요."
)

PINTEREST_NOTE = (
    "ℹ️ Pinterest API는 **OAuth Access Token(베어러 토큰)** 기반입니다. "
    "또한 `GET /v5/search/partner/pins`는 **베타이며 모든 앱에서 사용 불가**일 수 있어요. "
    "사용 불가(403 등)면 앱에서 Pinterest 웹검색으로 자동 대체합니다."
)

# 모델 후보: 접근 불가 모델이면 자동으로 다음 후보로 넘어감
MODEL_CANDIDATES_DEFAULT = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]

# 이미지 생성 후보(권한/정책에 따라 실패할 수 있어 fallback 처리)
IMAGE_MODEL_CANDIDATES_DEFAULT = ["gpt-image-1"]


# -----------------------------
# Session State
# -----------------------------
def init_state():
    defaults = {
        "style_messages": [],
        "style_inputs": {
            "keywords": [],
            "text_like": "",
            "text_dislike": "",
            "text_constraints": "",
            "uploaded_image_bytes": None,
            "uploaded_image_name": None,
            "uploaded_image_analysis": None,
        },
        "style_report": None,
        "pinterest_cache": {},
        "pinterest_last_term": "",
        "pinterest_suggested_queries": [],
        "pinterest_negative_terms": [],
        "working_model": None,
        "working_image_model": None,
        "outfit_images": [],  # [{title, b64, prompt, model}]

        # OAuth 관련 상태
        "pinterest_oauth_state": None,
        "pinterest_access_token": None,
        "pinterest_refresh_token": None,
        "pinterest_token_expires_at": None,  # epoch seconds
        "pinterest_last_auth_error": None,

        # ✅ 마지막 Pinterest 결과(분위기 분석/테마 적용에 활용)
        "last_pins": [],  # [{title, description, alt_text, ...}]
        # ✅ 추구미 진단 후 UI 테마 프로필
        "ui_profile": None,  # dict
        "ui_applied": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# -----------------------------
# UI Theming (✅ 추가: 진단 결과 기반 UI 스타일 적용)
# -----------------------------
def _safe_hex(hx: str, fallback: str) -> str:
    if not hx or not isinstance(hx, str):
        return fallback
    hx = hx.strip()
    if len(hx) == 7 and hx.startswith("#"):
        return hx
    return fallback


def _pick_first_hex(colors: List[Dict[str, str]], fallback: str) -> str:
    for c in colors or []:
        if isinstance(c, dict) and c.get("hex"):
            return _safe_hex(c["hex"], fallback)
    return fallback


def _lower_join(*parts: str) -> str:
    return " ".join([p for p in parts if p]).lower()


def _extract_color_votes_from_text(text: str) -> Dict[str, int]:
    """
    Pinterest title/alt_text/description에서 자주 등장하는 색 단서로 투표.
    아주 단순한 휴리스틱(가볍게 분위기 보조용).
    """
    t = (text or "").lower()
    votes: Dict[str, int] = {}

    def add(name: str, n: int = 1):
        votes[name] = votes.get(name, 0) + n

    # neutrals
    for w in ["black", "charcoal", "graphite", "gray", "grey", "white", "ivory", "cream", "beige", "camel", "taupe"]:
        if w in t:
            add(w, 1)

    # colors
    for w in ["navy", "blue", "sky", "denim", "red", "burgundy", "wine", "pink", "rose", "coral", "green", "olive", "khaki", "brown"]:
        if w in t:
            add(w, 1)

    # korean hints
    kr_map = {
        "블랙": "black",
        "오프화이트": "ivory",
        "아이보리": "ivory",
        "베이지": "beige",
        "카멜": "camel",
        "그레이": "gray",
        "회색": "gray",
        "네이비": "navy",
        "레드": "red",
        "버건디": "burgundy",
        "핑크": "pink",
        "로즈": "rose",
        "올리브": "olive",
        "카키": "khaki",
        "브라운": "brown",
        "갈색": "brown",
        "화이트": "white",
    }
    for k, v in kr_map.items():
        if k.lower() in t:
            add(v, 2)

    return votes


def _votes_to_style_bucket(votes: Dict[str, int]) -> str:
    """
    색 투표 결과로 대략적인 무드 버킷을 추정.
    - monochrome: black/white/gray 중심
    - soft: ivory/beige/pink/rose 중심
    - bold: red/burgundy/black 대비
    - classic: navy/camel/taupe 중심
    """
    if not votes:
        return ""

    score_mono = votes.get("black", 0) + votes.get("white", 0) + votes.get("gray", 0) + votes.get("grey", 0) + votes.get("charcoal", 0)
    score_soft = votes.get("ivory", 0) + votes.get("cream", 0) + votes.get("beige", 0) + votes.get("pink", 0) + votes.get("rose", 0) + votes.get("coral", 0)
    score_bold = votes.get("red", 0) + votes.get("burgundy", 0) + votes.get("wine", 0) + votes.get("black", 0)
    score_classic = votes.get("navy", 0) + votes.get("camel", 0) + votes.get("taupe", 0) + votes.get("beige", 0)

    best = max(
        [("monochrome", score_mono), ("soft", score_soft), ("bold", score_bold), ("classic", score_classic)],
        key=lambda x: x[1],
    )
    return best[0] if best[1] > 0 else ""


def derive_ui_profile(style_report: Dict[str, Any], pins: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    추구미 리포트 + Pinterest 참고(텍스트 기반)로 UI 테마/톤을 구성.
    실제 이미지 분석은 하지 않고, 리포트와 핀 메타(alt_text/title/description)로 분위기 보조 추정.
    """
    r = style_report or {}
    mini = r.get("mini_report") or {}
    guide = r.get("practice_guide") or {}
    fashion = (guide.get("fashion") or {}) if isinstance(guide, dict) else {}

    core = r.get("core_keywords") or []
    selected = (st.session_state.get("style_inputs") or {}).get("keywords", []) or []
    kset = set([str(x) for x in (core + selected) if x])

    # Pinterest 텍스트 기반 색 단서 수집
    votes: Dict[str, int] = {}
    for p in pins or []:
        t = _lower_join(p.get("title", ""), p.get("alt_text", ""), p.get("description", ""))
        v = _extract_color_votes_from_text(t)
        for kk, vv in v.items():
            votes[kk] = votes.get(kk, 0) + vv
    pin_bucket = _votes_to_style_bucket(votes)

    # 리포트 팔레트(가능하면 우선 사용)
    palette = fashion.get("color_palette") or []
    avoid = fashion.get("avoid_colors") or []
    pal_primary = _pick_first_hex(palette, "#6B7280")  # slate
    pal_secondary = _pick_first_hex(palette[1:] if len(palette) > 1 else [], "#E5E7EB")  # light gray

    # 키워드 기반 기본 버킷
    if {"무채색의", "시크함", "절제된", "중성적인"} & kset:
        base_bucket = "monochrome"
    elif {"러블리", "귀여움", "청순함", "단아한"} & kset:
        base_bucket = "soft"
    elif {"강렬한", "섹시한", "섹시함"} & kset:
        base_bucket = "bold"
    elif {"우아함", "고급스러움", "단정한"} & kset:
        base_bucket = "classic"
    else:
        base_bucket = "neutral"

    # Pinterest 보조 버킷이 있으면 약하게 반영(같으면 강화, 다르면 중립으로 완화)
    bucket = base_bucket
    if pin_bucket:
        if pin_bucket == base_bucket:
            bucket = base_bucket
        else:
            # 상충 시: 리포트 팔레트가 있으면 그쪽을 우선, 없으면 neutral로
            bucket = base_bucket if palette else "neutral"

    # 버킷별 UI 팔레트/톤(기본값)
    theme_map = {
        "monochrome": {
            "bg_a": "#0B0F19",
            "bg_b": "#111827",
            "card": "#0F172A",
            "text": "#E5E7EB",
            "muted": "#9CA3AF",
            "accent": pal_primary if palette else "#A3A3A3",
            "accent2": pal_secondary if palette else "#E5E7EB",
            "emoji": "🖤",
            "tone": "미니멀·시크",
        },
        "soft": {
            "bg_a": "#FFF7FB",
            "bg_b": "#FDF2F8",
            "card": "#FFFFFF",
            "text": "#111827",
            "muted": "#6B7280",
            "accent": pal_primary if palette else "#EC4899",
            "accent2": pal_secondary if palette else "#FBCFE8",
            "emoji": "🫧",
            "tone": "소프트·러블리",
        },
        "bold": {
            "bg_a": "#0B0F19",
            "bg_b": "#1F2937",
            "card": "#111827",
            "text": "#F9FAFB",
            "muted": "#9CA3AF",
            "accent": pal_primary if palette else "#EF4444",
            "accent2": pal_secondary if palette else "#FCA5A5",
            "emoji": "🔥",
            "tone": "강렬·포인트",
        },
        "classic": {
            "bg_a": "#FAFAF9",
            "bg_b": "#F5F5F4",
            "card": "#FFFFFF",
            "text": "#111827",
            "muted": "#6B7280",
            "accent": pal_primary if palette else "#0F766E",
            "accent2": pal_secondary if palette else "#99F6E4",
            "emoji": "✨",
            "tone": "클래식·고급",
        },
        "neutral": {
            "bg_a": "#F8FAFC",
            "bg_b": "#EEF2FF",
            "card": "#FFFFFF",
            "text": "#0F172A",
            "muted": "#475569",
            "accent": pal_primary if palette else "#6366F1",
            "accent2": pal_secondary if palette else "#C7D2FE",
            "emoji": "🪞",
            "tone": "균형·세련",
        },
    }
    t = theme_map.get(bucket, theme_map["neutral"])

    # 섹션 타이틀/이모지(조금 더 “분위기 맞춤”)
    emoji = t["emoji"]
    labels = {
        "title": f"{emoji} 이미지 레시피 - 내 분위기 맞춤 모드",
        "sec1": f"{emoji} 1) 무드/스타일 선택 (3~7개)",
        "sec2": f"{emoji} 2) 추가 정보를 입력해주세요",
        "sec3": f"{emoji} 3) (선택) 이미지 업로드 — 추구미 분위기 분석",
        "pinterest": f"{emoji} Pinterest 참고 이미지(인물 이미지 검색)",
        "report": f"{emoji} 추구미 분석 & 리포트",
        "guide": f"{emoji} 실천 가이드 (방향성)",
        "outfit": f"{emoji} 예시 코디 (텍스트 + 시각화)",
        "chat": f"{emoji} 추구미 챗봇에게 물어보기",
    }

    # 채팅 입력 힌트도 분위기 맞춤
    chat_hint = "예: '이 분위기를 유지하려면 오늘 딱 10분 안에 뭘 하면 좋아?'"
    if bucket == "monochrome":
        chat_hint = "예: '시크/절제 무드에서 과해 보이는 포인트 5가지만 콕 집어줘.'"
    elif bucket == "soft":
        chat_hint = "예: '청순/러블리 무드에서 촌스러움 피하는 기준을 체크리스트로 줘.'"
    elif bucket == "bold":
        chat_hint = "예: '강렬/섹시 무드에서 저렴해 보이지 않게 만드는 룰 3개 알려줘.'"
    elif bucket == "classic":
        chat_hint = "예: '우아/고급 무드에서 데일리로 무겁지 않게 만드는 조합을 알려줘.'"

    return {
        "bucket": bucket,
        "tone": t["tone"],
        "colors": {
            "bg_a": t["bg_a"],
            "bg_b": t["bg_b"],
            "card": t["card"],
            "text": t["text"],
            "muted": t["muted"],
            "accent": t["accent"],
            "accent2": t["accent2"],
        },
        "labels": labels,
        "chat_hint": chat_hint,
        "pin_bucket": pin_bucket,
        "pin_votes": votes,
        "has_palette": bool(palette),
        "avoid_colors": avoid,
    }


def apply_ui_profile_css(profile: Dict[str, Any]):
    c = (profile or {}).get("colors") or {}
    bg_a = _safe_hex(c.get("bg_a"), "#F8FAFC")
    bg_b = _safe_hex(c.get("bg_b"), "#EEF2FF")
    card = _safe_hex(c.get("card"), "#FFFFFF")
    text = _safe_hex(c.get("text"), "#0F172A")
    muted = _safe_hex(c.get("muted"), "#475569")
    accent = _safe_hex(c.get("accent"), "#6366F1")
    accent2 = _safe_hex(c.get("accent2"), "#C7D2FE")

    st.markdown(
        f"""
        <style>
          /* App background */
          .stApp {{
            background: linear-gradient(135deg, {bg_a} 0%, {bg_b} 100%) !important;
            color: {text} !important;
          }}

          /* Main container spacing */
          section.main > div.block-container {{
            padding-top: 2.0rem;
            padding-bottom: 4.0rem;
            max-width: 1200px;
          }}

          /* Cards-ish blocks */
          div[data-testid="stMetric"], div[data-testid="stExpander"] > details {{
            border-radius: 16px !important;
          }}

          /* Inputs */
          .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {{
            border-radius: 14px !important;
          }}

          /* Buttons */
          .stButton button {{
            border-radius: 14px !important;
            border: 1px solid rgba(148, 163, 184, 0.35) !important;
          }}
          .stButton button[kind="primary"] {{
            background: {accent} !important;
            border-color: {accent} !important;
            color: white !important;
          }}
          .stButton button:hover {{
            filter: brightness(0.98);
          }}

          /* Sidebar background */
          section[data-testid="stSidebar"] {{
            background: rgba(255,255,255,0.65);
            backdrop-filter: blur(10px);
          }}

          /* Chat bubbles */
          div[data-testid="stChatMessage"] {{
            border-radius: 18px !important;
          }}

          /* A subtle "card" utility class */
          .ch-card {{
            background: {card};
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 18px;
            padding: 14px 16px;
          }}
          .ch-muted {{
            color: {muted};
          }}
          .ch-badge {{
            display:inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            background: {accent2};
            border: 1px solid rgba(148, 163, 184, 0.25);
            font-size: 12px;
            margin-right: 6px;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# UI 프로필이 있으면 즉시 적용
if st.session_state.get("ui_profile"):
    apply_ui_profile_css(st.session_state["ui_profile"])


def L(key: str, fallback: str) -> str:
    """UI 프로필 기반 라벨 반환"""
    p = st.session_state.get("ui_profile") or {}
    labels = p.get("labels") or {}
    return labels.get(key, fallback)


# -----------------------------
# OpenAI REST helpers (Chat Completions) with fallback
# -----------------------------
def _post_chat_completions(api_key: str, payload: Dict[str, Any], timeout: int = 90) -> requests.Response:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return requests.post(url, headers=headers, json=payload, timeout=timeout, stream=bool(payload.get("stream")))


def _is_model_access_error(msg: str) -> bool:
    if not msg:
        return False
    m = msg.lower()
    return (
        "model" in m
        and ("does not exist" in m or "do not have access" in m or "not found" in m or "permission" in m)
    )


def _try_models(api_key: str, build_payload_fn, model_candidates: List[str], timeout: int) -> Tuple[str, Dict[str, Any]]:
    last_err_msg = ""
    for model in model_candidates:
        payload = build_payload_fn(model)
        try:
            r = _post_chat_completions(api_key, payload, timeout=timeout)
            if r.status_code == 200:
                return model, r.json()

            try:
                err = r.json()
                last_err_msg = err.get("error", {}).get("message", r.text)
            except Exception:
                last_err_msg = r.text

            if _is_model_access_error(last_err_msg):
                continue
            raise RuntimeError(last_err_msg)

        except requests.exceptions.Timeout:
            raise RuntimeError("요청 시간이 초과됐어요. 네트워크 상태를 확인하고 다시 시도해 주세요.")
        except requests.exceptions.RequestException:
            raise RuntimeError("네트워크 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")

    raise RuntimeError(
        "사용 가능한 모델을 찾지 못했어요. (모델 접근 권한/조직 정책/키 설정을 확인해 주세요)\n"
        f"- 마지막 오류: {last_err_msg}"
    )


def openai_stream_chat_with_fallback(
    api_key: str,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    model_candidates: List[str],
    temperature: float = 0.6,
) -> Tuple[str, str]:
    used_model = st.session_state.get("working_model")
    candidates = [used_model] + model_candidates if used_model else model_candidates

    def build_payload(model: str) -> Dict[str, Any]:
        return {
            "model": model,
            "temperature": temperature,
            "stream": True,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
        }

    last_err_msg = ""
    for model in candidates:
        payload = build_payload(model)
        placeholder = st.empty()
        full_text = ""

        try:
            with _post_chat_completions(api_key, payload, timeout=120) as r:
                if r.status_code != 200:
                    try:
                        err = r.json()
                        last_err_msg = err.get("error", {}).get("message", r.text)
                    except Exception:
                        last_err_msg = r.text

                    if _is_model_access_error(last_err_msg):
                        continue
                    raise RuntimeError(last_err_msg)

                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[len("data: ") :].strip()
                        if data == "[DONE]":
                            break
                        try:
                            j = json.loads(data)
                            delta = j["choices"][0]["delta"].get("content", "")
                            if delta:
                                full_text += delta
                                placeholder.markdown(full_text)
                        except Exception:
                            continue

                st.session_state["working_model"] = model
                return full_text, model

        except requests.exceptions.Timeout:
            raise RuntimeError("요청 시간이 초과됐어요. 네트워크 상태를 확인하고 다시 시도해 주세요.")
        except requests.exceptions.RequestException:
            raise RuntimeError("네트워크 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")

    raise RuntimeError("스트리밍에 사용할 수 있는 모델을 찾지 못했어요.\n" f"- 마지막 오류: {last_err_msg}")


def openai_json_with_fallback(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    model_candidates: List[str],
    temperature: float = 0.2,
    timeout: int = 60,
) -> Tuple[Dict[str, Any], str]:
    used_model = st.session_state.get("working_model")
    candidates = [used_model] + model_candidates if used_model else model_candidates

    def build_payload(model: str) -> Dict[str, Any]:
        return {
            "model": model,
            "temperature": temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    model, resp = _try_models(api_key, build_payload, candidates, timeout=timeout)
    st.session_state["working_model"] = model
    content = resp["choices"][0]["message"]["content"]
    return json.loads(content), model


def openai_vision_analyze_style_with_fallback(
    api_key: str,
    image_bytes: bytes,
    allowed_keywords: List[str],
    model_candidates: List[str],
) -> Tuple[Dict[str, Any], str]:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    system_prompt = (
        "당신은 '추구미(이미지 정체성)' 분석가입니다. "
        "사용자가 업로드한 이미지를 보고, 주어진 키워드 후보 중에서만 "
        "이미지의 분위기/스타일에 해당하는 키워드를 골라주세요. "
        "과장하지 말고, 보이는 근거를 짧게 설명하세요. "
        "개인 식별(누구인지, 나이 추정 등)은 하지 마세요. "
        "반드시 JSON으로만 답하세요."
    )

    user_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    f"허용 키워드 후보:\n{allowed_keywords}\n\n"
                    "요청:\n"
                    "1) 후보 중 3~7개 키워드를 선택\n"
                    "2) 근거를 한 단락으로 짧게\n"
                    "3) 이미지가 추구미 분석에 부적절/애매하면 경고문(warnings)에 한 줄\n\n"
                    "출력 JSON 스키마:\n"
                    '{ "keywords": [...], "rationale": "...", "warnings": "..." }'
                ),
            },
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }

    used_model = st.session_state.get("working_model")
    candidates = [used_model] + model_candidates if used_model else model_candidates

    def build_payload(model: str) -> Dict[str, Any]:
        return {
            "model": model,
            "temperature": 0.2,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                user_message,
            ],
        }

    model, resp = _try_models(api_key, build_payload, candidates, timeout=90)
    st.session_state["working_model"] = model
    content = resp["choices"][0]["message"]["content"]
    return json.loads(content), model


# -----------------------------
# OpenAI Images API (optional) with fallback
# -----------------------------
def _post_images(api_key: str, payload: Dict[str, Any], timeout: int = 120) -> requests.Response:
    url = "https://api.openai.com/v1/images/generations"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return requests.post(url, headers=headers, json=payload, timeout=timeout)


def _is_image_model_access_error(msg: str) -> bool:
    if not msg:
        return False
    m = msg.lower()
    return ("model" in m) and ("does not exist" in m or "do not have access" in m or "not found" in m)


def generate_outfit_image_with_fallback(
    api_key: str,
    prompt: str,
    image_model_candidates: List[str],
    size: str = "1024x1024",
) -> Tuple[str, str]:
    """
    Returns (b64_png, used_image_model)
    """
    used_model = st.session_state.get("working_image_model")
    candidates = [used_model] + image_model_candidates if used_model else image_model_candidates

    last_err = ""
    for model in candidates:
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
        }
        try:
            r = _post_images(api_key, payload, timeout=180)
            if r.status_code == 200:
                j = r.json()
                b64_png = j["data"][0].get("b64_json")
                if not b64_png:
                    raise RuntimeError("이미지 응답에서 b64_json을 찾지 못했어요.")
                st.session_state["working_image_model"] = model
                return b64_png, model

            try:
                err = r.json()
                last_err = err.get("error", {}).get("message", r.text)
            except Exception:
                last_err = r.text

            if _is_image_model_access_error(last_err):
                continue
            raise RuntimeError(last_err)

        except requests.exceptions.Timeout:
            raise RuntimeError("이미지 생성 요청 시간이 초과됐어요. 다시 시도해 주세요.")
        except requests.exceptions.RequestException:
            raise RuntimeError("이미지 생성 중 네트워크 오류가 발생했어요.")

    raise RuntimeError(f"이미지 생성 모델을 사용할 수 없어요.\n- 마지막 오류: {last_err}")


# -----------------------------
# Pinterest OAuth helpers
# -----------------------------
def pinterest_basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


def pinterest_build_authorize_url(
    client_id: str,
    redirect_uri: str,
    scopes: List[str],
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return PINTEREST_AUTH_URL + "?" + urllib.parse.urlencode(params)


def pinterest_exchange_code_for_token(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    timeout: int = 20,
) -> Dict[str, Any]:
    headers = {
        "Authorization": pinterest_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    r = requests.post(PINTEREST_TOKEN_URL, headers=headers, data=data, timeout=timeout)
    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise RuntimeError(f"토큰 교환 실패 ({r.status_code}): {err}")
    return r.json()


def pinterest_refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: int = 20,
) -> Dict[str, Any]:
    headers = {
        "Authorization": pinterest_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post(PINTEREST_TOKEN_URL, headers=headers, data=data, timeout=timeout)
    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise RuntimeError(f"토큰 갱신 실패 ({r.status_code}): {err}")
    return r.json()


def pinterest_get_valid_access_token(client_id: str, client_secret: str) -> Optional[str]:
    token = st.session_state.get("pinterest_access_token")
    if not token:
        return None

    exp_at = st.session_state.get("pinterest_token_expires_at")
    refresh = st.session_state.get("pinterest_refresh_token")

    if not exp_at:
        return token

    now = int(time.time())
    if now < int(exp_at) - 60:
        return token

    if not refresh:
        return token

    try:
        j = pinterest_refresh_access_token(client_id, client_secret, refresh)
        new_token = j.get("access_token")
        if new_token:
            st.session_state["pinterest_access_token"] = new_token
        if j.get("refresh_token"):
            st.session_state["pinterest_refresh_token"] = j["refresh_token"]
        if j.get("expires_in"):
            st.session_state["pinterest_token_expires_at"] = int(time.time()) + int(j["expires_in"])
        return st.session_state.get("pinterest_access_token")
    except Exception as e:
        st.session_state["pinterest_last_auth_error"] = str(e)
        return token


def pinterest_web_search_url(term: str) -> str:
    q = urllib.parse.quote(term)
    return f"https://www.pinterest.com/search/pins/?q={q}"


# -----------------------------
# Pinterest API helpers
# -----------------------------
def pinterest_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def pinterest_best_image_url(media: Optional[Dict[str, Any]]) -> Optional[str]:
    if not media or not isinstance(media, dict):
        return None
    images = media.get("images")
    if not isinstance(images, dict):
        return None
    for key in ["600x", "400x300", "1200x", "150x150"]:
        if key in images and isinstance(images[key], dict) and images[key].get("url"):
            return images[key]["url"]
    for v in images.values():
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
    return None


def pinterest_search_partner_pins(
    access_token: str,
    term: str,
    country_code: str = "KR",
    locale: str = "ko-KR",
    limit: int = 12,
    bookmark: Optional[str] = None,
) -> Dict[str, Any]:
    url = f"{PINTEREST_BASE}/search/partner/pins"
    params = {
        "term": term,
        "country_code": country_code,
        "locale": locale,
        "limit": max(1, min(limit, 50)),
    }
    if bookmark:
        params["bookmark"] = bookmark

    r = requests.get(url, headers=pinterest_headers(access_token), params=params, timeout=20)
    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise RuntimeError(f"Pinterest API 오류 ({r.status_code}): {err}")
    return r.json()


# -----------------------------
# UI helpers
# -----------------------------
def render_color_swatches(colors: List[Dict[str, str]], title: str = "컬러 팔레트"):
    if not colors:
        st.caption("표시할 컬러 정보가 없어요.")
        return

    st.markdown(f"**{title}**")
    cols = st.columns(min(6, len(colors)))
    for i, c in enumerate(colors):
        name = (c or {}).get("name", "") or "color"
        hx = (c or {}).get("hex", "") or "#CCCCCC"
        with cols[i % len(cols)]:
            st.markdown(
                f"""
                <div style="border:1px solid rgba(148,163,184,0.25); border-radius:14px; padding:10px;">
                  <div style="height:44px; border-radius:10px; background:{hx};"></div>
                  <div style="margin-top:8px; font-weight:700;">{name}</div>
                  <div style="font-size:12px; opacity:0.75;">{hx}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# -----------------------------
# Prompts
# -----------------------------
def style_report_prompt(style_inputs: Dict[str, Any]) -> Tuple[str, str]:
    system_prompt = (
        "당신은 '추구미 도우미'입니다. "
        "사용자의 선택 키워드/텍스트/이미지 분석(선택)을 바탕으로 추구미 리포트와 실천 가이드를 생성하세요. "
        "브랜드/제품 추천 금지(방향성만). "
        "과장하지 말고 구조적으로. 반드시 JSON으로만 답하세요.\n\n"
        "중요:\n"
        "- best_contexts(어울리는 상황)는 절대 'x' 같은 자리표시자가 아니라, 한국어로 구체적인 상황 4~7개를 제시하세요.\n"
        "- color_palette/avoid_colors는 각 색을 name + hex(#RRGGBB)로 제공하세요.\n"
        "- outfit_examples는 3개 이상 제공(각각 '타이틀', '아이템 리스트', '포인트', '추천 팔레트 색(위 팔레트에서 참조)' 포함).\n"
    )

    user_prompt = {
        "selected_keywords": style_inputs.get("keywords", []),
        "text_like": style_inputs.get("text_like", ""),
        "text_dislike": style_inputs.get("text_dislike", ""),
        "text_constraints": style_inputs.get("text_constraints", ""),
        "uploaded_image_analysis": style_inputs.get("uploaded_image_analysis"),
        "output_schema": {
            "type_name_ko": "",
            "type_name_en": "",
            "identity_one_liner": "",
            "core_keywords": [],
            "mini_report": {
                "mood_summary": "",
                "impression": "",
                "best_contexts": ["구체적인 상황1", "구체적인 상황2"],
                "watch_out": "",
                "maintenance_difficulty": "낮음/중간/높음 중 하나",
            },
            "apply_strategy": "",
            "practice_guide": {
                "makeup": {"base": "", "points": {"eyes": "", "lips": ""}, "avoid": ""},
                "fashion": {
                    "silhouette": "",
                    "color_palette": [{"name": "charcoal", "hex": "#2E2E2E"}],
                    "avoid_colors": [{"name": "neon green", "hex": "#39FF14"}],
                    "top5_items": [],
                },
                "behavior_lifestyle": {"gesture_tone": "", "speech_manner": "", "daily_habits": []},
            },
            "outfit_examples": [
                {"title": "", "items": ["", "", ""], "point": "", "palette_refs": ["charcoal", "ivory"]}
            ],
        },
        "rules": [
            "best_contexts는 최소 4개 이상, 구체적으로",
            "브랜드/제품명 금지",
            "색은 반드시 hex로",
        ],
    }

    return system_prompt, json.dumps(user_prompt, ensure_ascii=False)


def pinterest_query_expander_prompt(chosen_keywords: List[str]) -> Tuple[str, str]:
    system_prompt = (
        "당신은 Pinterest 검색어 설계자입니다. "
        "사용자가 선택한 추구미 키워드로 '사람(인물) 이미지'가 잘 나오는 검색어를 만든다. "
        "Pinterest 검색에 강한 짧은 쿼리로 3~6개를 제안하라. "
        "한국어/영어 혼합 가능. "
        "반드시 JSON으로만 답하세요."
    )
    user_prompt = (
        f"키워드: {chosen_keywords}\n\n"
        'JSON 스키마: {"queries":[...], "negative_terms":[...], "note":"..."}\n'
        "- queries는 3~6개, 각 2~6단어\n"
        "- 사람/패션/룩/메이크업 중심(예: 'neutral chic outfit', 'clean girl makeup')"
    )
    return system_prompt, user_prompt


def style_chat_system_prompt() -> str:
    return """
당신은 '추구미(이미지 정체성) 코치'입니다.

핵심 원칙:
- 두괄식, 과장 금지, 실행 가능한 제안 위주
- 브랜드/제품명 추천 금지(방향성, 기준, 체크리스트만)
- 사용자가 고른 키워드(3~7개)를 중심으로 정리
- 사용자가 싫다고 한 요소/제약조건을 우선 반영
- 답변은 한국어, 너무 길지 않게(문단 4~7개)

"단순한 해결책"을 피하기 위한 코칭 규칙(매 답변에 적용):
1) 사용자의 목표를 1문장으로 재정의(정확히 무엇을 '유지/강화/피하기'인지)
2) 실패하는 흔한 원인 2~3개를 먼저 짚기(예: 톤/질감/비율/포인트 과잉 등)
3) 바로 적용 가능한 해결책을 "레벨별"로 제시
   - Level 1: 오늘 당장 할 수 있는 3가지(시간 3분~10분)
   - Level 2: 주 2~3회 루틴 3가지(관리/연습)
   - Level 3: 한 달 플랜 2가지(체계화/일관성)
4) 답변에 반드시 포함할 구체 요소(최소 6개 이상):
   - (메이크업) 질감/광/윤곽/눈·입 밸런스 중 최소 2개
   - (헤어) 실루엣/정돈/볼륨 중 최소 1개
   - (패션) 핏/소재/컬러/레이어링 중 최소 2개
   - (태도) 말투·속도·시선·제스처 중 최소 1개
5) 마지막에 "확인 질문 1개"만(정밀도 올릴 때만)
6) 사용자가 '무엇을 조심해야 해?'라고 물으면:
   - 금지 리스트(Do-not) 5개 + 대체안(Instead) 5개를 반드시 제시

출력 형식(권장):
- 한 줄 요약(현재 추구미 방향)
- 핵심 기준 3개(지켜야 할 룰)
- 해결책 Level 1 / Level 2 / Level 3
- Do-not vs Instead (필요 시)
- 마지막 질문 1개(선택)
""".strip()


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("⚙️ 설정")

    # OpenAI
    openai_key = st.text_input("OpenAI API Key", type="password", value="")

    st.divider()
    st.subheader("🧷 Pinterest 연결(OAuth)")

    pinterest_client_id = st.text_input("Pinterest Client ID", value="")
    pinterest_client_secret = st.text_input("Pinterest Client Secret", type="password", value="")

    default_redirect_uri = "https://chugumis-b-lee-ver2.streamlit.app/"
    pinterest_redirect_uri = st.text_input(
        "Redirect URI (Developer Portal에 동일하게 등록)",
        value=default_redirect_uri,
        help="Pinterest 앱 설정의 Redirect URI와 100% 동일해야 합니다. 마지막 / 포함 여부까지 같아야 해요.",
    )

    raw_scopes = st.text_input(
        "OAuth Scopes (공백 구분)",
        value="pins:read",
        help="처음엔 최소 권한(pins:read)만 권장. 과다 요청은 Trial 심사에 불리할 수 있어요.",
    )
    pinterest_scopes = [s.strip() for s in raw_scopes.split(" ") if s.strip()]

    # 기존: 토큰 직접 입력도 유지
    pinterest_token_manual = st.text_input("Pinterest Access Token (Bearer) - 수동", type="password", value="")
    st.caption(PINTEREST_NOTE)

    st.divider()

    raw_models = st.text_input(
        "OpenAI 모델 후보(쉼표로 구분, 앞부터 우선 시도)",
        value=", ".join(MODEL_CANDIDATES_DEFAULT),
    )
    model_candidates = [m.strip() for m in raw_models.split(",") if m.strip()] or MODEL_CANDIDATES_DEFAULT

    raw_image_models = st.text_input(
        "이미지 생성 모델 후보(쉼표로 구분)",
        value=", ".join(IMAGE_MODEL_CANDIDATES_DEFAULT),
        help="예시 코디 이미지를 ‘시각화’ 버튼으로 생성합니다. 모델 접근 권한이 없으면 실패할 수 있어요.",
    )
    image_model_candidates = [m.strip() for m in raw_image_models.split(",") if m.strip()] or IMAGE_MODEL_CANDIDATES_DEFAULT

    img_size = st.selectbox("코디 이미지 크기", ["1024x1024", "512x512"], index=0)

    # ---- OAuth 콜백 처리 (query param) ----
    q = st.query_params
    got_code = q.get("code")
    got_state = q.get("state")
    got_error = q.get("error")

    col_auth1, col_auth2 = st.columns(2)
    with col_auth1:
        if st.button("🔐 Pinterest로 로그인", use_container_width=True):
            if not (pinterest_client_id and pinterest_redirect_uri):
                st.session_state["pinterest_last_auth_error"] = "Client ID / Redirect URI를 입력해 주세요."
            else:
                state = secrets.token_urlsafe(16)
                st.session_state["pinterest_oauth_state"] = state
                st.session_state["pinterest_last_auth_error"] = None
                auth_url = pinterest_build_authorize_url(
                    pinterest_client_id,
                    pinterest_redirect_uri,
                    pinterest_scopes,
                    state,
                )
                st.link_button("로그인/동의 화면 열기", auth_url)

    with col_auth2:
        if st.button("🔓 Pinterest 연결 해제", use_container_width=True):
            st.session_state["pinterest_access_token"] = None
            st.session_state["pinterest_refresh_token"] = None
            st.session_state["pinterest_token_expires_at"] = None
            st.session_state["pinterest_oauth_state"] = None
            st.session_state["pinterest_last_auth_error"] = None
            st.success("Pinterest 연결을 해제했어요.")

    if got_error:
        st.session_state["pinterest_last_auth_error"] = f"OAuth 오류: {got_error}"
    elif got_code:
        if not pinterest_client_secret:
            st.session_state["pinterest_last_auth_error"] = "Client Secret이 없어서 토큰 교환을 할 수 없어요."
        else:
            expected_state = st.session_state.get("pinterest_oauth_state")
            if expected_state and got_state and got_state != expected_state:
                st.session_state["pinterest_last_auth_error"] = "state 값이 일치하지 않아 요청을 거부했어요(보안)."
            else:
                try:
                    token_json = pinterest_exchange_code_for_token(
                        pinterest_client_id,
                        pinterest_client_secret,
                        got_code,
                        pinterest_redirect_uri,
                    )
                    st.session_state["pinterest_access_token"] = token_json.get("access_token")
                    st.session_state["pinterest_refresh_token"] = token_json.get("refresh_token")
                    if token_json.get("expires_in"):
                        st.session_state["pinterest_token_expires_at"] = int(time.time()) + int(token_json["expires_in"])
                    st.session_state["pinterest_last_auth_error"] = None

                    st.query_params.clear()
                    st.success("Pinterest OAuth 연결 완료!")
                except Exception as e:
                    st.session_state["pinterest_last_auth_error"] = str(e)

    if st.session_state.get("pinterest_access_token"):
        st.success("Pinterest: OAuth 연결됨 ✅")
    else:
        st.info("Pinterest: OAuth 미연결")

    if st.session_state.get("pinterest_last_auth_error"):
        st.error(st.session_state["pinterest_last_auth_error"])

    # ✅ UI 테마 리셋(진단 후 자동 적용을 되돌리고 싶을 때)
    if st.button("🎛️ UI 테마 기본으로", use_container_width=True):
        st.session_state["ui_profile"] = None
        st.session_state["ui_applied"] = False
        st.success("UI 테마를 기본으로 되돌렸어요.")
        st.rerun()

    if st.button("🧹 초기화", use_container_width=True):
        st.session_state["style_messages"] = []
        st.session_state["style_report"] = None
        st.session_state["outfit_images"] = []
        st.session_state["pinterest_cache"] = {}
        st.session_state["pinterest_last_term"] = ""
        st.session_state["pinterest_suggested_queries"] = []
        st.session_state["pinterest_negative_terms"] = []
        st.session_state["working_model"] = None
        st.session_state["working_image_model"] = None
        st.session_state["style_inputs"] = {
            "keywords": [],
            "text_like": "",
            "text_dislike": "",
            "text_constraints": "",
            "uploaded_image_bytes": None,
            "uploaded_image_name": None,
            "uploaded_image_analysis": None,
        }
        st.session_state["pinterest_access_token"] = None
        st.session_state["pinterest_refresh_token"] = None
        st.session_state["pinterest_token_expires_at"] = None
        st.session_state["pinterest_oauth_state"] = None
        st.session_state["pinterest_last_auth_error"] = None
        st.session_state["last_pins"] = []
        st.session_state["ui_profile"] = None
        st.session_state["ui_applied"] = False
        st.success("초기화 완료!")
        st.rerun()

    st.divider()
    st.markdown(PRIVACY_NOTICE)

# -----------------------------
# Token 선택 우선순위 (OAuth > 수동 입력)
# -----------------------------
pinterest_token_oauth = None
if pinterest_client_id and pinterest_client_secret:
    pinterest_token_oauth = pinterest_get_valid_access_token(pinterest_client_id, pinterest_client_secret)

pinterest_token = pinterest_token_oauth or (pinterest_token_manual.strip() or None)

# -----------------------------
# Main
# -----------------------------
st.title(L("title", "🫧이미지 레시피 - 직접 설계하는 내 이미지"))

# ✅ 진단 후 UI 적용 상태 배너
if st.session_state.get("ui_profile"):
    p = st.session_state["ui_profile"]
    st.markdown(
        f"""
        <div class="ch-card">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
            <div>
              <div style="font-size:18px; font-weight:800; margin-bottom:4px;">
                UI가 ‘{p.get('tone','맞춤')}’ 분위기로 적용됐어요
              </div>
              <div class="ch-muted" style="font-size:13px;">
                (리포트 + Pinterest 참고 텍스트 기반으로 톤을 맞췄어요)
              </div>
            </div>
            <div>
              <span class="ch-badge">bucket: {p.get('bucket','')}</span>
              <span class="ch-badge">pin-hint: {p.get('pin_bucket','') or 'n/a'}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")

# 1) 키워드 선택 (3~7)
st.subheader(L("sec1", "1) 무드/스타일 선택 (3~7개)"))
selected = st.multiselect(
    "끌리는 키워드를 골라주세요",
    STYLE_KEYWORDS,
    default=st.session_state["style_inputs"].get("keywords", []),
    max_selections=7,
)
st.session_state["style_inputs"]["keywords"] = selected
st.caption("※ 최소 3개, 최대 7개를 선택해 주세요.")

# 2) 추가 정보 입력
st.subheader(L("sec2", "2) 추가 정보를 입력해주세요"))
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.session_state["style_inputs"]["text_like"] = st.text_area(
        "내가 좋아하는 스타일을 구체적으로 적어보아요.",
        value=st.session_state["style_inputs"].get("text_like", ""),
        placeholder="예: 편해 보이는데 세련됐으면 / 피부 표현은 깨끗하게",
        height=120,
    )
with col_b:
    st.session_state["style_inputs"]["text_dislike"] = st.text_area(
        "이런 느낌은 싫어요",
        value=st.session_state["style_inputs"].get("text_dislike", ""),
        placeholder="예: 너무 꾸민 느낌 / 과한 펄",
        height=120,
    )
with col_c:
    st.session_state["style_inputs"]["text_constraints"] = st.text_area(
        "현실 제약/조건(선택)",
        value=st.session_state["style_inputs"].get("text_constraints", ""),
        placeholder="예: 학교에서 무난해야 함 / 예산 제한 / 관리 시간 적음",
        height=120,
    )

# 3) 이미지 업로드 — 추구미 분위기 분석
st.subheader(L("sec3", "3) (선택) 이미지 업로드 — 추구미 분위기 분석"))
up = st.file_uploader("좋다고 느꼈던 이미지가 있으면 올려주세요 (jpg/png)", type=["jpg", "jpeg", "png"])
if up is not None:
    img_bytes = up.read()
    st.session_state["style_inputs"]["uploaded_image_bytes"] = img_bytes
    st.session_state["style_inputs"]["uploaded_image_name"] = up.name
    st.image(img_bytes, caption=f"업로드: {up.name}", use_container_width=True)

    if st.button("🧠 업로드 이미지로 추구미 키워드 추정", use_container_width=True):
        if not openai_key:
            st.warning("OpenAI API Key를 입력하면 이미지 분석을 할 수 있어요.")
        else:
            with st.spinner("이미지 분위기를 분석 중..."):
                try:
                    analysis, used_model = openai_vision_analyze_style_with_fallback(
                        openai_key,
                        img_bytes,
                        STYLE_KEYWORDS,
                        model_candidates=model_candidates,
                    )
                    st.session_state["style_inputs"]["uploaded_image_analysis"] = analysis
                    st.success(f"이미지 기반 키워드 추정 완료! (사용 모델: {used_model})")
                except Exception as e:
                    st.error(f"이미지 분석 오류: {e}")

if st.session_state["style_inputs"].get("uploaded_image_analysis"):
    a = st.session_state["style_inputs"]["uploaded_image_analysis"]
    st.markdown("#### 🖼️ 이미지 분석 결과(참고)")
    st.markdown(f"- 추정 키워드: **{', '.join(a.get('keywords', []))}**")
    if a.get("rationale"):
        st.caption(a["rationale"])
    if a.get("warnings"):
        st.warning(a["warnings"])

    if st.button("➕ 이미지 키워드를 선택 키워드에 합치기", use_container_width=True):
        merged = list(dict.fromkeys(st.session_state["style_inputs"]["keywords"] + a.get("keywords", [])))
        st.session_state["style_inputs"]["keywords"] = merged[:7]
        st.rerun()

st.divider()

# Pinterest (OAuth/수동 토큰) + API 제한 시 웹검색 fallback
st.subheader(L("pinterest", "🧷 Pinterest 참고 이미지(인물 이미지 검색)"))
st.caption("선택한 추구미 키워드로 Pinterest에서 참고 이미지를 가져옵니다(권한/토큰 필요). API 제한 시 웹검색으로 대체합니다.")

colp1, colp2 = st.columns([2, 1])
with colp1:
    manual_term = st.text_input("직접 검색어(선택)", value=st.session_state.get("pinterest_last_term", ""))
with colp2:
    st.write("")
    st.write("")
    auto_expand = st.checkbox("🤖 AI로 검색어 추천", value=True)

if auto_expand and openai_key and st.session_state["style_inputs"]["keywords"]:
    if st.button("🔎 검색어 추천 만들기", use_container_width=True):
        try:
            spx, upx = pinterest_query_expander_prompt(st.session_state["style_inputs"]["keywords"])
            qq, used_model = openai_json_with_fallback(
                openai_key,
                spx,
                upx,
                model_candidates=model_candidates,
                temperature=0.2,
                timeout=60,
            )
            st.session_state["pinterest_suggested_queries"] = (qq.get("queries", []) or [])[:6]
            st.session_state["pinterest_negative_terms"] = (qq.get("negative_terms", []) or [])[:6]
            st.success(f"추천 검색어 생성 완료! (사용 모델: {used_model})")
        except Exception as e:
            st.error(f"검색어 추천 오류: {e}")

suggested_queries = st.session_state.get("pinterest_suggested_queries", [])
negative_terms = st.session_state.get("pinterest_negative_terms", [])

if suggested_queries:
    st.markdown("**추천 검색어:** " + " · ".join([f"`{q}`" for q in suggested_queries]))
if negative_terms:
    st.caption("제외(참고): " + ", ".join([f"`{q}`" for q in negative_terms]))

term_to_search = manual_term.strip()
if not term_to_search and suggested_queries:
    term_to_search = suggested_queries[0]

cols_btn = st.columns([1, 1, 2])
with cols_btn[0]:
    do_search = st.button("📌 Pinterest 검색", use_container_width=True)
with cols_btn[1]:
    clear_cache = st.button("🧽 Pinterest 캐시 비우기", use_container_width=True)
with cols_btn[2]:
    st.caption("※ /search/partner/pins는 베타라 403이면 API가 막힌 것이고, 웹검색 링크로 대체됩니다.")

if clear_cache:
    st.session_state["pinterest_cache"] = {}
    st.session_state["last_pins"] = []
    st.success("캐시를 비웠어요!")

pins = []
fallback_web = None

if do_search:
    if not term_to_search:
        st.warning("검색어를 입력하거나(또는 추천 검색어 생성) 진행해 주세요.")
    else:
        st.session_state["pinterest_last_term"] = term_to_search
        cache = st.session_state["pinterest_cache"]

        if term_to_search in cache:
            pins = cache[term_to_search]
        else:
            if not pinterest_token:
                fallback_web = pinterest_web_search_url(term_to_search)
                st.info("Pinterest 토큰이 없어서 웹검색 링크로 안내할게요.")
            else:
                with st.spinner("Pinterest에서 핀을 불러오는 중..."):
                    try:
                        data = pinterest_search_partner_pins(
                            pinterest_token,
                            term_to_search,
                            country_code="KR",
                            locale="ko-KR",
                            limit=12,
                        )
                        items = data.get("items", []) or []
                        norm = []
                        for it in items:
                            media = it.get("media") or {}
                            img_url = pinterest_best_image_url(media)
                            norm.append(
                                {
                                    "id": it.get("id"),
                                    "title": it.get("title") or "",
                                    "description": it.get("description") or "",
                                    "link": it.get("link") or "",
                                    "img": img_url,
                                    "alt_text": it.get("alt_text") or "",
                                }
                            )
                        pins = norm
                        cache[term_to_search] = pins
                        st.session_state["pinterest_cache"] = cache
                    except Exception as e:
                        fallback_web = pinterest_web_search_url(term_to_search)
                        st.warning(
                            "Pinterest API로 검색이 제한될 수 있어요(권한/베타/Trial 범위 등). "
                            "대신 Pinterest 웹검색 링크를 제공할게요."
                        )
                        st.caption(f"API 오류 상세: {e}")

# 캐시/결과 반영
if not pins and term_to_search in st.session_state["pinterest_cache"]:
    pins = st.session_state["pinterest_cache"][term_to_search]

if pins:
    st.session_state["last_pins"] = pins  # ✅ 진단 UI 반영에 사용

if fallback_web:
    st.link_button("🔎 Pinterest 웹에서 검색하기", fallback_web)

if pins:
    st.markdown(f"#### 결과: `{term_to_search}`")
    c1, c2, c3 = st.columns(3)
    cols = [c1, c2, c3]
    for i, p in enumerate(pins):
        with cols[i % 3]:
            if p.get("img"):
                link = p.get("link") or "https://www.pinterest.com/"
                title = (p.get("title") or "").strip() or "Pinterest Pin"
                st.markdown(
                    f"""
                    <a href="{link}" target="_blank" style="text-decoration:none;">
                        <img src="{p["img"]}" style="width:100%; border-radius:14px; margin-bottom:6px;" />
                    </a>
                    <div style="font-weight:700; margin-bottom:8px;">{title}</div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.info("이미지 URL이 없는 핀이에요.")
            with st.expander("상세"):
                if p.get("description"):
                    st.write(p["description"])
                if p.get("alt_text"):
                    st.caption(p["alt_text"])
                if p.get("link"):
                    st.link_button("Pinterest에서 열기", p["link"])

st.divider()

# -----------------------------
# 추구미 리포트 생성 (✅ 완료 후 UI를 '분위기 맞춤 모드'로 자동 전환)
# -----------------------------
st.subheader(L("report", "🧾 추구미 분석 & 리포트"))
can_run = 3 <= len(st.session_state["style_inputs"]["keywords"]) <= 7

colr1, colr2 = st.columns([1, 2])
with colr1:
    if st.button("✨ 추구미 분석", use_container_width=True, disabled=not can_run):
        if not openai_key:
            st.warning("OpenAI API Key를 입력해 주세요.")
        else:
            with st.spinner("추구미 리포트를 생성 중..."):
                try:
                    sys_p, user_p = style_report_prompt(st.session_state["style_inputs"])
                    report, used_model = openai_json_with_fallback(
                        openai_key,
                        sys_p,
                        user_p,
                        model_candidates=model_candidates,
                        temperature=0.4,
                        timeout=90,
                    )
                    st.session_state["style_report"] = report
                    st.session_state["outfit_images"] = []
                    st.success(f"리포트 생성 완료! (사용 모델: {used_model})")

                    # ✅ 리포트 + Pinterest 참고(최근 검색 결과)로 UI 프로필 생성/적용
                    pins_for_mood = st.session_state.get("last_pins", []) or []
                    ui_profile = derive_ui_profile(report, pins_for_mood)
                    st.session_state["ui_profile"] = ui_profile
                    st.session_state["ui_applied"] = True

                    # CSS 즉시 적용을 위해 리런
                    st.rerun()

                except Exception as e:
                    st.error(f"리포트 생성 오류: {e}")

    st.caption("조건: 키워드 3~7개 선택")
with colr2:
    st.caption("※ 사진 업로드가 있어도, 현재는 이미지 원본을 저장하지 않고 분석 결과(키워드/근거)만 참고합니다.")

if st.session_state.get("style_report"):
    r = st.session_state["style_report"]

    st.markdown(f"## 💎 타입: **{r.get('type_name_ko','')}**  \n**{r.get('type_name_en','')}**")
    st.markdown(f"**한 문장 정체성:** {r.get('identity_one_liner','')}")
    st.markdown("**핵심 키워드:** " + ", ".join([f"`{k}`" for k in (r.get("core_keywords") or [])]))

    st.markdown("### 📌 미니 리포트")
    mini = r.get("mini_report", {}) or {}
    st.markdown(f"- 분위기 요약: {mini.get('mood_summary','')}")
    st.markdown(f"- 타인 인상: {mini.get('impression','')}")

    best = mini.get("best_contexts") or []
    if best:
        st.markdown("- 어울리는 상황:")
        for x in best:
            st.markdown(f"  - {x}")
    else:
        st.caption("어울리는 상황 정보가 없어요(리포트 생성 시 포함되도록 프롬프트를 강화해두었습니다).")

    st.markdown(f"- 과도함 주의: {mini.get('watch_out','')}")
    st.markdown(f"- 유지 난이도: **{mini.get('maintenance_difficulty','')}**")

    if r.get("apply_strategy"):
        st.markdown("### 🧩 적용 전략")
        st.write(r["apply_strategy"])

    st.markdown(f"### {L('guide', '🪞 실천 가이드 (방향성)')}")
    guide = r.get("practice_guide", {}) or {}
    m = guide.get("makeup", {}) or {}
    f = guide.get("fashion", {}) or {}
    b = guide.get("behavior_lifestyle", {}) or {}

    cga, cgb = st.columns(2)
    with cga:
        st.markdown("#### 💄 메이크업")
        st.markdown(f"- 베이스: {m.get('base','')}")
        pts = m.get("points", {}) or {}
        st.markdown(f"- 눈: {pts.get('eyes','')}")
        st.markdown(f"- 입술: {pts.get('lips','')}")
        st.markdown(f"- 피하면 좋은 요소: {m.get('avoid','')}")
    with cgb:
        st.markdown("#### 👗 패션")
        st.markdown(f"- 실루엣: {f.get('silhouette','')}")

        palette = f.get("color_palette") or []
        avoid = f.get("avoid_colors") or []
        if palette:
            render_color_swatches(palette, title="추천 컬러 팔레트")
        if avoid:
            render_color_swatches(avoid, title="피하면 좋은 컬러")

        if f.get("top5_items"):
            st.markdown("- 기본 아이템 Top5:\n" + "\n".join([f"  - {x}" for x in f.get("top5_items", [])]))

    st.markdown("#### 🧍 행동/라이프스타일")
    st.markdown(f"- 제스처/톤: {b.get('gesture_tone','')}")
    st.markdown(f"- 말투/매너: {b.get('speech_manner','')}")
    if b.get("daily_habits"):
        st.markdown("- 작은 습관:\n" + "\n".join([f"  - {x}" for x in b.get("daily_habits", [])]))

    st.divider()
    st.subheader(L("outfit", "🧥 예시 코디 (텍스트 + 시각화)"))

    outfit_examples = r.get("outfit_examples") or []
    if not outfit_examples:
        st.caption("예시 코디가 없어요(리포트 생성 프롬프트에서 생성하도록 유도해두었습니다).")
    else:
        for i, ex in enumerate(outfit_examples[:6], start=1):
            title = (ex or {}).get("title", f"코디 {i}")
            items = (ex or {}).get("items", []) or []
            point = (ex or {}).get("point", "")
            refs = (ex or {}).get("palette_refs", []) or []

            with st.expander(f"{i}) {title}", expanded=(i == 1)):
                if items:
                    st.markdown("**구성 아이템**")
                    st.markdown("\n".join([f"- {it}" for it in items]))
                if point:
                    st.markdown(f"**포인트**: {point}")
                if refs:
                    st.caption("팔레트 참고: " + ", ".join([str(x) for x in refs]))

        st.markdown("#### 🎨 코디 시각화(이미지 생성)")
        st.caption("선택한 예시 코디를 ‘룩북 스타일’로 간단히 시각화합니다. (브랜드 로고/문구 없이)")

        titles = [(ex or {}).get("title", f"코디 {i+1}") for i, ex in enumerate(outfit_examples[:6])]
        pick_idx = st.selectbox("시각화할 코디 선택", list(range(len(titles))), format_func=lambda x: titles[x], index=0)

        if st.button("🖼️ 선택 코디를 이미지로 보기", use_container_width=True):
            if not openai_key:
                st.warning("OpenAI API Key를 입력해 주세요.")
            else:
                ex = outfit_examples[pick_idx]
                title = (ex or {}).get("title", "outfit")
                items = (ex or {}).get("items", []) or []
                point = (ex or {}).get("point", "")
                refs = (ex or {}).get("palette_refs", []) or []

                palette_map = {
                    c.get("name"): c.get("hex")
                    for c in (guide.get("fashion", {}) or {}).get("color_palette", [])
                    if isinstance(c, dict)
                }
                ref_hex = [f"{n}:{palette_map.get(n)}" for n in refs if palette_map.get(n)]

                img_prompt = (
                    "Fashion lookbook product photo, clean studio background, "
                    "full outfit laid out or worn by a faceless mannequin, no logos, no text.\n"
                    f"Outfit title: {title}\n"
                    f"Items: {', '.join(items) if items else 'N/A'}\n"
                    f"Styling point: {point}\n"
                    f"Color references: {', '.join(ref_hex) if ref_hex else ', '.join(refs)}\n"
                    "High quality, realistic, editorial style, minimal, soft lighting."
                )

                with st.spinner("코디 이미지를 생성 중..."):
                    try:
                        b64_png, used_img_model = generate_outfit_image_with_fallback(
                            openai_key,
                            img_prompt,
                            image_model_candidates=image_model_candidates,
                            size=img_size,
                        )
                        st.session_state["outfit_images"].append(
                            {"title": title, "b64": b64_png, "prompt": img_prompt, "model": used_img_model}
                        )
                        st.success(f"생성 완료! (이미지 모델: {used_img_model})")
                    except Exception as e:
                        st.error(f"이미지 생성 오류: {e}")

        if st.session_state.get("outfit_images"):
            st.markdown("#### 🖼️ 생성된 코디 이미지")
            cols = st.columns(3)
            for i, img in enumerate(st.session_state["outfit_images"][-6:]):
                with cols[i % 3]:
                    st.image(base64.b64decode(img["b64"]), caption=img.get("title", "outfit"), use_container_width=True)

st.divider()

# -----------------------------
# 추구미 챗봇(대화)
# -----------------------------
st.subheader(L("chat", "💬 추구미 챗봇에게 물어보기"))
st.caption("선택 키워드/입력 내용을 바탕으로 ‘기준’과 ‘실천 팁’ 위주로 답해요. (브랜드 추천 없음)")

for m in st.session_state["style_messages"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

chat_hint = (st.session_state.get("ui_profile") or {}).get(
    "chat_hint",
    "예: '세련+절제+무채색 느낌을 유지하려면 메이크업에서 뭘 제일 조심해야 해?'",
)
user_msg = st.chat_input(chat_hint)

if user_msg:
    st.session_state["style_messages"].append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    if not openai_key:
        with st.chat_message("assistant"):
            st.warning("사이드바에 OpenAI API Key를 입력하면 추구미 챗봇 답변을 받을 수 있어요.")
    else:
        ctx = {
            "selected_keywords": st.session_state["style_inputs"].get("keywords", []),
            "text_like": st.session_state["style_inputs"].get("text_like", ""),
            "text_dislike": st.session_state["style_inputs"].get("text_dislike", ""),
            "text_constraints": st.session_state["style_inputs"].get("text_constraints", ""),
            "uploaded_image_analysis": st.session_state["style_inputs"].get("uploaded_image_analysis"),
            "pinterest_hint": {
                "last_term": st.session_state.get("pinterest_last_term", ""),
                "pin_count": len(st.session_state.get("last_pins") or []),
                "pin_color_votes": (st.session_state.get("ui_profile") or {}).get("pin_votes", {}),
            },
            "style_report_summary": {
                "type_name": (st.session_state.get("style_report") or {}).get("type_name_ko"),
                "core_keywords": (st.session_state.get("style_report") or {}).get("core_keywords"),
                "mini": (st.session_state.get("style_report") or {}).get("mini_report"),
            },
            "note": "브랜드/제품 추천 금지. 방향성과 기준, 체크리스트만.",
        }
        system_prompt = style_chat_system_prompt() + "\n\n[사용자 컨텍스트]\n" + json.dumps(ctx, ensure_ascii=False)

        with st.chat_message("assistant"):
            try:
                assistant_text, used_model = openai_stream_chat_with_fallback(
                    openai_key,
                    system_prompt,
                    st.session_state["style_messages"],
                    model_candidates=model_candidates,
                    temperature=0.6,
                )
                st.session_state["style_messages"].append({"role": "assistant", "content": assistant_text})
                st.caption(f"사용 모델: {used_model}")
            except Exception as e:
                st.error(f"챗봇 오류: {e}")
