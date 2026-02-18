# app.py
import base64
import json
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Literal

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

PINTEREST_NOTE = (
    "ℹ️ Pinterest API는 **OAuth Access Token(베어러 토큰)** 기반입니다. "
    "또한 `GET /v5/search/partner/pins`는 **베타이며 모든 앱에서 사용 불가**일 수 있어요. "
    "사용 불가(403 등)면 앱에서 Pinterest 웹검색으로 자동 대체합니다."
)

MODEL_CANDIDATES_DEFAULT = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]
IMAGE_MODEL_CANDIDATES_DEFAULT = ["gpt-image-1"]

Gender = Literal["male", "female"]


# -----------------------------
# Keyword DB (20개 추구미)
# -----------------------------
@dataclass(frozen=True)
class KeywordMeta:
    name: str
    vibe: str
    style_elements: List[str]


KEYWORD_DB: Dict[str, KeywordMeta] = {
    "미니멀": KeywordMeta(
        "미니멀",
        "군더더기 없는 실루엣과 절제된 디테일로 ‘깔끔한 인상’을 만드는 무드.",
        ["세미오버/스트레이트 핏", "뉴트럴(블랙/오프화이트/그레이)", "무지/노로고", "울·코튼·나일론", "단정한 레이어링"],
    ),
    "시크": KeywordMeta(
        "시크",
        "차분한 표정 + 날카로운 라인. 과한 장식 없이도 ‘도시적인 쿨함’이 느껴지는 분위기.",
        ["모노톤/딥톤", "슬림~세미오버 믹스", "레더/울/트윌", "미니멀 악세서리", "포인트 1개만"],
    ),
    "클래식": KeywordMeta(
        "클래식",
        "시간이 지나도 무너지지 않는 단정함과 균형감. ‘정석’에서 오는 신뢰감.",
        ["정돈된 핏", "네이비/베이지/아이보리", "셔츠/니트/코트", "가죽 슈즈", "규칙적인 비율"],
    ),
    "올드머니": KeywordMeta(
        "올드머니",
        "과시 대신 품질/정돈으로 완성하는 ‘조용한 고급’. 로고보다 소재/핏이 말해주는 타입.",
        ["캐시미어/울/코튼 고밀도", "베이지/크림/네이비", "클린한 실루엣", "심플 주얼리", "톤온톤"],
    ),
    "도시적": KeywordMeta(
        "도시적",
        "출근/약속/모임 어디든 어울리는 ‘세련된 현실감’. 선명한 라인과 정돈된 컬러가 핵심.",
        ["미니멀 셋업 감", "차콜/네이비/오프화이트", "구조적인 아우터", "깔끔한 신발", "매끈한 소재"],
    ),
    "내추럴": KeywordMeta(
        "내추럴",
        "힘 준 티 없이 편안한데 멋있는 ‘꾸안꾸’ 균형. 부드러운 소재와 여유 있는 핏.",
        ["루즈/와이드", "오프화이트/베이지/소프트톤", "코튼/린넨", "레이어드 티", "플랫/스니커즈"],
    ),
    "러블리": KeywordMeta(
        "러블리",
        "사랑스러운 디테일과 밝은 톤. 가까이 다가가기 쉬운 ‘말랑한 인상’이 포인트.",
        ["라이트 톤(핑크/아이보리)", "작은 패턴", "리본/셔링/니트", "부드러운 텍스처", "둥근 실루엣"],
    ),
    "청순": KeywordMeta(
        "청순",
        "투명하고 정돈된 분위기. 과한 포인트 없이 ‘깨끗한’ 느낌을 유지하는 방향.",
        ["오프화이트/크림", "과한 노출 X", "단정한 실루엣", "잔잔한 소재감", "미세한 포인트"],
    ),
    "페미닌": KeywordMeta(
        "페미닌",
        "곡선과 부드러운 디테일로 완성하는 우아한 분위기. 실루엣/소재가 관건.",
        ["허리선/라인 강조(과하지 않게)", "실키/쉬폰/니트", "뉴트럴+포인트 컬러", "스커트/원피스", "주얼리 밸런스"],
    ),
    "매니시": KeywordMeta(
        "매니시",
        "단단한 라인과 구조감. ‘멋부림’이 아닌 ‘태도’로 보이는 쿨함.",
        ["테일러드 자켓", "셔츠/타이(옵션)", "네이비/차콜", "로퍼/부츠", "각진 실루엣"],
    ),
    "스트릿": KeywordMeta(
        "스트릿",
        "자유로운 레이어링과 실루엣. ‘힙’한 무드가 자연스럽게 드러나는 스타일.",
        ["오버핏", "그래픽/로고(과하지 않게)", "데님/나일론", "캡/백팩", "스니커즈 중심"],
    ),
    "힙": KeywordMeta(
        "힙",
        "트렌드 감도를 ‘한 끗’으로 보여주는 스타일. 과잉보다 균형감이 중요.",
        ["포인트 1개", "실루엣 변주", "트렌디 컬러/소재", "액세서리 활용", "레이어링"],
    ),
    "Y2K": KeywordMeta(
        "Y2K",
        "2000년대 무드의 팝/키치 감성. 아이템 조합이 핵심이며 과하면 촌스러울 수 있음.",
        ["로우/미드 라이즈", "메탈릭/데님", "크롭/슬림", "미니백", "선글라스/헤어핀"],
    ),
    "키치": KeywordMeta(
        "키치",
        "장난기 있는 컬러/패턴/소품. ‘의도된 귀여운 과장’이 포인트.",
        ["비비드/파스텔 포인트", "유니크 패턴", "소품 플레이", "볼륨감", "믹스매치"],
    ),
    "빈티지": KeywordMeta(
        "빈티지",
        "낡은 듯 멋있는 질감/톤. ‘시간이 묻은’ 색과 소재가 핵심.",
        ["바랜 톤(브라운/카키)", "워싱 데님", "레트로 패턴", "가죽/스웨이드", "레이어드"],
    ),
    "스포티": KeywordMeta(
        "스포티",
        "가벼운 기능성과 활동성. 실용적이면서도 깔끔한 연출.",
        ["기능성 소재", "조거/트랙", "블록 컬러", "캡/스니커즈", "라이트 아우터"],
    ),
    "섹시": KeywordMeta(
        "섹시",
        "노출보다 ‘비율/라인/긴장감’으로 만드는 분위기. 과하면 저렴해 보일 수 있음.",
        ["실루엣 강조", "딥톤+포인트", "텍스처 대비", "포인트 아이템 1개", "정돈된 디테일"],
    ),
    "강렬": KeywordMeta(
        "강렬",
        "첫 인상에서 확실히 남는 대비/포인트 중심 무드. ‘명확한 컨셉’이 중요.",
        ["대비 컬러", "선명한 실루엣", "레더/메탈 포인트", "강한 액세서리", "주도적인 무드"],
    ),
    "단정": KeywordMeta(
        "단정",
        "정리된 헤어/핏/컬러. 튀지 않지만 신뢰감 있는 인상을 만드는 타입.",
        ["정돈된 핏", "뉴트럴/네이비", "셔츠/니트", "심플 슈즈", "깔끔한 소재"],
    ),
    "귀여움": KeywordMeta(
        "귀여움",
        "작은 디테일과 밝은 톤이 만드는 ‘친근함’. 과유불급(유아화 주의).",
        ["라운드 실루엣", "파스텔/밝은 톤", "니트/가디건", "작은 패턴", "소품 포인트"],
    ),
}

STYLE_KEYWORDS = list(KEYWORD_DB.keys())
DETAILED_KEYWORD_EXAMPLES = ["미니멀", "러블리", "섹시", "스트릿", "클래식"]


# -----------------------------
# Session State
# -----------------------------
def init_state():
    defaults = {
        "style_messages": [],
        "style_inputs": {
            "gender": "female",
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

        # 시각화 이미지들
        "outfit_images": [],  # [{title, b64, prompt, model}]
        "makeup_images": [],  # [{title, b64, prompt, model}]

        # OAuth 관련 상태
        "pinterest_oauth_state": None,
        "pinterest_access_token": None,
        "pinterest_refresh_token": None,
        "pinterest_token_expires_at": None,
        "pinterest_last_auth_error": None,

        # Pinterest 결과
        "last_pins": [],

        # 챗봇 코디 피드백용
        "chat_style_photo_bytes": None,
        "chat_style_photo_name": None,
        "chat_style_feedback": None,  # dict
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


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
    return ("model" in m) and ("does not exist" in m or "do not have access" in m or "not found" in m or "permission" in m)


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


def openai_vision_outfit_feedback_with_fallback(
    api_key: str,
    image_bytes: bytes,
    style_report: Dict[str, Any],
    style_inputs: Dict[str, Any],
    model_candidates: List[str],
) -> Tuple[Dict[str, Any], str]:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/jpeg;base64,{b64}"

    system_prompt = (
        "당신은 '스타일링 코치'입니다.\n"
        "사용자가 올린 '스타일링 사진'을 보고 패션 요소를 분석한 뒤, "
        "제공된 '추구미 리포트' 기준으로 피드백을 제공합니다.\n"
        "엄격한 규칙:\n"
        "- 개인 식별/나이/외모 평가/체형 비하/얼굴 분석 금지. 얼굴은 무시하고 의상/스타일만.\n"
        "- 브랜드/제품명 추천 금지(범용 아이템 표현만).\n"
        "- 과장 금지, 사진에서 확인 가능한 범위만.\n"
        "- 반드시 JSON으로만 답하세요.\n"
    )

    report_summary = {
        "type": style_report.get("type_name_ko"),
        "identity_one_liner": style_report.get("identity_one_liner"),
        "core_keywords": style_report.get("core_keywords"),
        "mini_report": style_report.get("mini_report"),
        "practice_guide": style_report.get("practice_guide"),
        "gender_split_directions": style_report.get("gender_split_directions"),
    }

    user_text = {
        "gender": style_inputs.get("gender", "female"),
        "selected_keywords": style_inputs.get("keywords", []),
        "text_like": style_inputs.get("text_like", ""),
        "text_dislike": style_inputs.get("text_dislike", ""),
        "text_constraints": style_inputs.get("text_constraints", ""),
        "style_report_summary": report_summary,
        "allowed_keywords": STYLE_KEYWORDS,
        "output_schema": {
            "detected": {
                "top_items": [],
                "silhouette_fit": "",
                "color_tone": "",
                "materials_textures": [],
                "styling_points": [],
                "risk_points": [],
            },
            "alignment": {"score_0_100": 0, "matches": [], "breaks": []},
            "feedback": {
                "one_liner": "",
                "keep_doing": [],
                "fix_today_level1": [],
                "routine_level2": [],
                "plan_level3": [],
                "avoid": [],
                "next_purchase_suggestions": [],
            },
            "warnings": "",
        },
        "instructions": [
            "detected.top_items는 상의/하의/아우터/신발/가방·악세서리 위주로 6~12개",
            "alignment.score_0_100은 추구미 리포트 기준 정합성",
            "breaks는 '왜 어긋나는지'를 구체적으로(톤/비율/질감/포인트 과잉 등)",
            "fix_today_level1은 3~5개(바로 적용, 3~10분 내)",
            "avoid는 5개 이상 + 대체 방향을 괄호로 간단히",
            "next_purchase_suggestions는 3~5개(범용 아이템명, 브랜드 금지)",
        ],
    }

    user_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": json.dumps(user_text, ensure_ascii=False)},
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

    model, resp = _try_models(api_key, build_payload, candidates, timeout=120)
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


def generate_image_with_fallback(
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
        payload = {"model": model, "prompt": prompt, "size": size}
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


def pinterest_build_authorize_url(client_id: str, redirect_uri: str, scopes: List[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return PINTEREST_AUTH_URL + "?" + urllib.parse.urlencode(params)


def pinterest_exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str, timeout: int = 20) -> Dict[str, Any]:
    headers = {
        "Authorization": pinterest_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    r = requests.post(PINTEREST_TOKEN_URL, headers=headers, data=data, timeout=timeout)
    if r.status_code != 200:
        try:
            err = r.json()
        except Exception:
            err = {"message": r.text}
        raise RuntimeError(f"토큰 교환 실패 ({r.status_code}): {err}")
    return r.json()


def pinterest_refresh_access_token(client_id: str, client_secret: str, refresh_token: str, timeout: int = 20) -> Dict[str, Any]:
    headers = {
        "Authorization": pinterest_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
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
    return {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json"}


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
    params = {"term": term, "country_code": country_code, "locale": locale, "limit": max(1, min(limit, 50))}
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


def render_selected_keyword_cards(selected_keywords: List[str]):
    if not selected_keywords:
        return
    st.markdown("### 🧷 선택한 키워드 요약(앱 내부 DB)")
    for k in selected_keywords:
        meta = KEYWORD_DB.get(k)
        if not meta:
            continue
        with st.expander(f"🔸 {meta.name}", expanded=False):
            st.markdown(f"- **핵심 분위기**: {meta.vibe}")
            st.markdown("- **대표 스타일 요소**")
            for e in meta.style_elements:
                st.markdown(f"  - {e}")


def format_outfit_feedback_md(feedback: Dict[str, Any]) -> str:
    if not feedback:
        return "피드백 데이터가 없어요."

    detected = feedback.get("detected", {}) or {}
    alignment = feedback.get("alignment", {}) or {}
    fb = feedback.get("feedback", {}) or {}

    lines = []
    one = fb.get("one_liner", "")
    score = alignment.get("score_0_100", None)

    if one:
        lines.append(f"### 🧾 사진 기반 코디 피드백\n**한 줄 총평:** {one}")
    else:
        lines.append("### 🧾 사진 기반 코디 피드백")

    if isinstance(score, int):
        lines.append(f"**추구미 정합성 점수:** **{score}/100**")

    items = detected.get("top_items", []) or []
    if items:
        lines.append("\n**보이는 아이템/구성(추정):**")
        lines += [f"- {x}" for x in items[:14]]

    if detected.get("silhouette_fit"):
        lines.append(f"\n**실루엣/핏:** {detected.get('silhouette_fit')}")
    if detected.get("color_tone"):
        lines.append(f"**컬러 톤:** {detected.get('color_tone')}")

    mats = detected.get("materials_textures", []) or []
    if mats:
        lines.append("\n**소재/텍스처 단서:**")
        lines += [f"- {x}" for x in mats[:8]]

    pts = detected.get("styling_points", []) or []
    if pts:
        lines.append("\n**스타일 포인트:**")
        lines += [f"- {x}" for x in pts[:8]]

    matches = (alignment.get("matches") or [])[:8]
    breaks = (alignment.get("breaks") or [])[:8]
    if matches:
        lines.append("\n**잘 맞는 부분(keep):**")
        lines += [f"- {x}" for x in matches]
    if breaks:
        lines.append("\n**어긋나는 부분(fix):**")
        lines += [f"- {x}" for x in breaks]

    keep = (fb.get("keep_doing") or [])[:6]
    if keep:
        lines.append("\n**계속 유지하면 좋은 것:**")
        lines += [f"- {x}" for x in keep]

    l1 = (fb.get("fix_today_level1") or [])[:6]
    if l1:
        lines.append("\n**Level 1 (오늘 3~10분 개선):**")
        lines += [f"- {x}" for x in l1]

    l2 = (fb.get("routine_level2") or [])[:6]
    if l2:
        lines.append("\n**Level 2 (주 2~3회 루틴):**")
        lines += [f"- {x}" for x in l2]

    l3 = (fb.get("plan_level3") or [])[:4]
    if l3:
        lines.append("\n**Level 3 (한 달 플랜):**")
        lines += [f"- {x}" for x in l3]

    avoid = (fb.get("avoid") or [])[:10]
    if avoid:
        lines.append("\n**Do-not (피해야 할 것):**")
        lines += [f"- {x}" for x in avoid]

    buy = (fb.get("next_purchase_suggestions") or [])[:6]
    if buy:
        lines.append("\n**다음 구매 후보(범용 아이템):**")
        lines += [f"- {x}" for x in buy]

    if feedback.get("warnings"):
        lines.append(f"\n⚠️ {feedback.get('warnings')}")

    return "\n".join(lines)


# -----------------------------
# Prompts
# -----------------------------
def style_report_prompt(style_inputs: Dict[str, Any]) -> Tuple[str, str]:
    system_prompt = (
        "당신은 '추구미 도우미(스타일 코치 + 리포트 작성자)'입니다.\n"
        "입력(성별/키워드/선호/비선호/제약/이미지 분석)을 바탕으로 추구미 리포트를 생성합니다.\n"
        "브랜드/제품명 추천 금지(방향성과 기준, 범용 아이템 명칭만).\n"
        "과장 금지, 현실적인 추천.\n"
        "반드시 JSON으로만 답하세요.\n\n"
        "필수 규칙(중요):\n"
        "1) type_name_ko/type_name_en은 '키워드 나열'처럼 보이지 않게, 사용자가 이해하기 쉬운 '말'로 지으세요.\n"
        "2) mini_report에서 best_contexts는 contexts_section 안에 따로 묶어서 작성하세요.\n"
        "3) gender_split_directions는 생성하되, 화면에는 선택 성별만 보이게 쓰기 쉬운 구조로.\n"
        "4) color_palette/avoid_colors는 name + hex(#RRGGBB).\n"
        "5) outfit_recommendations는 최소 3세트.\n"
        "6) 금지: 브랜드/제품명/로고.\n"
        "7) 메이크업 추천은 gender가 female일 때만 meaningful하게 작성하고, "
        "   male이면 makeup 항목을 비워두거나 간단히 '해당 없음' 수준으로 작성하세요.\n"
    )

    keyword_context = {
        "allowed_keywords": STYLE_KEYWORDS,
        "keyword_db": {k: {"vibe": v.vibe, "style_elements": v.style_elements} for k, v in KEYWORD_DB.items()},
        "detailed_example_keywords": DETAILED_KEYWORD_EXAMPLES,
    }

    user_prompt_obj = {
        "gender": style_inputs.get("gender", "female"),
        "selected_keywords": style_inputs.get("keywords", []),
        "text_like": style_inputs.get("text_like", ""),
        "text_dislike": style_inputs.get("text_dislike", ""),
        "text_constraints": style_inputs.get("text_constraints", ""),
        "uploaded_image_analysis": style_inputs.get("uploaded_image_analysis"),
        "keyword_context": keyword_context,
        "output_schema": {
            "type_name_ko": "",
            "type_name_en": "",
            "identity_one_liner": "",
            "core_keywords": [],
            "mini_report": {
                "mood_summary": "",
                "impression": "",
                "watch_out": "",
                "maintenance_difficulty": "낮음/중간/높음 중 하나",
                "contexts_section": {
                    "title": "어울리는 상황",
                    "best_contexts": ["구체적인 상황1", "구체적인 상황2", "구체적인 상황3", "구체적인 상황4"],
                    "why_it_works": "",
                },
            },
            "apply_strategy": "",
            "practice_guide": {
                "makeup": {"base": "", "points": {"eyes": "", "lips": ""}, "avoid": ""},  # female만 의미있게
                "fashion": {
                    "silhouette": "",
                    "color_palette": [{"name": "charcoal", "hex": "#2E2E2E"}],
                    "avoid_colors": [{"name": "neon green", "hex": "#39FF14"}],
                    "top5_items": [],
                },
                "behavior_lifestyle": {"gesture_tone": "", "speech_manner": "", "daily_habits": []},
            },
            "gender_split_directions": [
                {
                    "keyword": "",
                    "male": {"fit": "", "colors": "", "key_items": [], "mood": ""},
                    "female": {"fit": "", "colors": "", "key_items": [], "mood": ""},
                    "common_core": [],
                    "differentiation_points": [],
                }
            ],
            "outfit_recommendations": [
                {
                    "title": "",
                    "concept": "",
                    "tops": ["", "", ""],
                    "bottoms": ["", "", ""],
                    "outers": ["", ""],
                    "shoes": ["", ""],
                    "accessories": [],
                    "avoid": ["", "", "", "", ""],
                    "palette_refs": ["charcoal", "ivory"],
                }
            ],
        },
        "rules": [
            "브랜드/제품명/로고 언급 금지",
            "허용 키워드(allowed_keywords) 밖의 키워드는 core_keywords에 넣지 말 것",
            "gender_split_directions는 5개(가능하면 선택 키워드에서 우선)",
            "코디 추천은 최소 3세트, 구매 가능한 범용 아이템으로 구체화",
            "avoid는 최소 5개 항목",
            "mini_report.contexts_section.best_contexts는 최소 4개, 구체적으로",
        ],
    }

    return system_prompt, json.dumps(user_prompt_obj, ensure_ascii=False)


def pinterest_query_expander_prompt(chosen_keywords: List[str], gender: str) -> Tuple[str, str]:
    system_prompt = (
        "당신은 Pinterest 검색어 설계자입니다. "
        "사용자가 선택한 추구미 키워드로 '사람(인물) 이미지'가 잘 나오는 검색어를 만든다. "
        "Pinterest 검색에 강한 짧은 쿼리로 3~6개를 제안하라. "
        "한국어/영어 혼합 가능. "
        "성별 선택(남/여)을 자연스럽게 반영하라. "
        "반드시 JSON으로만 답하세요."
    )
    user_prompt = (
        f"성별: {gender}\n"
        f"키워드: {chosen_keywords}\n\n"
        'JSON 스키마: {"queries":[...], "negative_terms":[...], "note":"..."}\n'
        "- queries는 3~6개, 각 2~6단어\n"
        "- 사람/패션/룩 중심\n"
        "- 성별 힌트를 자연스럽게: (예: mens outfit, womens outfit, 남자 데일리룩, 여자 데일리룩)\n"
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

추가 규칙(사진 피드백이 함께 제공될 때):
- 사진 피드백의 'matches/breaks/avoid'를 우선 근거로 삼아 구체적으로 말할 것
- 외모 평가 금지, 의상/스타일 요소만
""".strip()


# -----------------------------
# Sidebar
# -----------------------------
with st.sidebar:
    st.header("⚙️ 설정")

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
        help="코디/메이크업 시각화 이미지 생성에 사용됩니다.",
    )
    image_model_candidates = [m.strip() for m in raw_image_models.split(",") if m.strip()] or IMAGE_MODEL_CANDIDATES_DEFAULT

    img_size_outfit = st.selectbox("코디 이미지 크기", ["1024x1024", "512x512"], index=0)
    img_size_makeup = st.selectbox("메이크업 이미지 크기", ["1024x1024", "512x512"], index=0)

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

    if st.button("🧹 초기화", use_container_width=True):
        st.session_state["style_messages"] = []
        st.session_state["style_report"] = None
        st.session_state["pinterest_cache"] = {}
        st.session_state["pinterest_last_term"] = ""
        st.session_state["pinterest_suggested_queries"] = []
        st.session_state["pinterest_negative_terms"] = []
        st.session_state["working_model"] = None
        st.session_state["working_image_model"] = None

        st.session_state["outfit_images"] = []
        st.session_state["makeup_images"] = []

        st.session_state["style_inputs"] = {
            "gender": "female",
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

        st.session_state["chat_style_photo_bytes"] = None
        st.session_state["chat_style_photo_name"] = None
        st.session_state["chat_style_feedback"] = None

        st.success("초기화 완료!")
        st.rerun()


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
st.title("🫧이미지 레시피 - 직접 설계하는 내 이미지")

# 0) 성별 선택
st.subheader("0) 성별 선택")
gender_label = st.radio(
    "추천 결과를 분리하기 위해 성별을 선택해 주세요",
    options=["여성", "남성"],
    index=0 if st.session_state["style_inputs"].get("gender") == "female" else 1,
    horizontal=True,
)
st.session_state["style_inputs"]["gender"] = "female" if gender_label == "여성" else "male"

# 1) 키워드 선택 (3~7)
st.subheader("1) 무드/스타일 선택 (3~7개)")
selected = st.multiselect(
    "끌리는 키워드를 골라주세요",
    STYLE_KEYWORDS,
    default=st.session_state["style_inputs"].get("keywords", []),
    max_selections=7,
)
st.session_state["style_inputs"]["keywords"] = selected
st.caption("※ 최소 3개, 최대 7개를 선택해 주세요.")
render_selected_keyword_cards(selected)

# 2) 추가 정보 입력
st.subheader("2) 추가 정보를 입력해주세요")
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
st.subheader("3) (선택) 이미지 업로드 — 추구미 분위기 분석")
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

# -----------------------------
# Pinterest
# -----------------------------
st.subheader("🧷 Pinterest 참고 이미지(인물 이미지 검색)")
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
            spx, upx = pinterest_query_expander_prompt(
                st.session_state["style_inputs"]["keywords"],
                gender=st.session_state["style_inputs"].get("gender", "female"),
            )
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

if not pins and term_to_search in st.session_state["pinterest_cache"]:
    pins = st.session_state["pinterest_cache"][term_to_search]

if pins:
    st.session_state["last_pins"] = pins

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
# 추구미 리포트 생성
# -----------------------------
st.subheader("🧾 추구미 분석 & 리포트")
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
                    st.session_state["makeup_images"] = []
                    st.success(f"리포트 생성 완료! (사용 모델: {used_model})")
                except Exception as e:
                    st.error(f"리포트 생성 오류: {e}")

    st.caption("조건: 키워드 3~7개 선택")
with colr2:
    st.caption("※ 사진 업로드가 있어도, 현재는 이미지 원본을 저장하지 않고 분석 결과(키워드/근거)만 참고합니다.")

if st.session_state.get("style_report"):
    r = st.session_state["style_report"]
    gender = st.session_state["style_inputs"].get("gender", "female")
    gender_label_k = "여성" if gender == "female" else "남성"

    st.markdown(f"## 💎 타입: **{r.get('type_name_ko','')}**  \n**{r.get('type_name_en','')}**")
    st.markdown(f"**한 문장 정체성:** {r.get('identity_one_liner','')}")
    st.markdown("**핵심 키워드:** " + ", ".join([f"`{k}`" for k in (r.get("core_keywords") or [])]))

    st.markdown("### 📌 미니 리포트")
    mini = r.get("mini_report", {}) or {}
    st.markdown(f"- 분위기 요약: {mini.get('mood_summary','')}")
    st.markdown(f"- 타인 인상: {mini.get('impression','')}")
    st.markdown(f"- 과도함 주의: {mini.get('watch_out','')}")
    st.markdown(f"- 유지 난이도: **{mini.get('maintenance_difficulty','')}**")

    contexts = (mini.get("contexts_section") or {})
    if contexts:
        st.markdown(f"### 🗓️ {contexts.get('title','어울리는 상황')}")
        best = contexts.get("best_contexts") or []
        if best:
            for x in best:
                st.markdown(f"- {x}")
        if contexts.get("why_it_works"):
            st.caption(contexts.get("why_it_works"))

    if r.get("apply_strategy"):
        st.markdown("### 🧩 적용 전략")
        st.write(r["apply_strategy"])

    st.markdown("### 🪞 실천 가이드 (방향성)")
    guide = r.get("practice_guide", {}) or {}
    m = guide.get("makeup", {}) or {}
    f = guide.get("fashion", {}) or {}
    b = guide.get("behavior_lifestyle", {}) or {}

    # ✅ 여성만 메이크업 섹션 표기
    if gender == "female":
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
    else:
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

    # 성별 분리 스타일링 방향성: 선택 성별만 표시
    st.divider()
    st.subheader(f"🧬 {gender_label_k} 기준 스타일링 방향성")
    gsd = r.get("gender_split_directions") or []
    if not gsd:
        st.caption("성별 분리 방향성 데이터가 없어요.")
    else:
        for block in gsd[:5]:
            kw = (block or {}).get("keyword", "")
            common = (block or {}).get("common_core", []) or []
            diff = (block or {}).get("differentiation_points", []) or []
            chosen = (block or {}).get(gender, {}) or {}

            with st.expander(f"🔸 {kw} — {gender_label_k} 기준", expanded=False):
                st.markdown(f"- **핏:** {chosen.get('fit','')}")
                st.markdown(f"- **색감:** {chosen.get('colors','')}")
                if chosen.get("key_items"):
                    st.markdown("- **주요 아이템:**\n" + "\n".join([f"  - {x}" for x in chosen.get("key_items", [])]))
                st.markdown(f"- **무드:** {chosen.get('mood','')}")

                if common:
                    st.markdown("**공통 핵심(성별 무관하게 유지할 것)**")
                    st.markdown("\n".join([f"- {x}" for x in common]))
                if diff:
                    st.markdown("**이 키워드에서 특히 조절할 포인트**")
                    st.markdown("\n".join([f"- {x}" for x in diff]))

    # -----------------------------
    # 예시 코디 + (별도) 코디 이미지 생성
    # -----------------------------
    st.divider()
    st.subheader("🧥 예시 코디 (텍스트)")
    outfit_recos = r.get("outfit_recommendations") or []
    if not outfit_recos:
        st.caption("코디 추천이 없어요.")
    else:
        for i, ex in enumerate(outfit_recos[:6], start=1):
            title = (ex or {}).get("title", f"코디 {i}")
            concept = (ex or {}).get("concept", "")
            tops = (ex or {}).get("tops", []) or []
            bottoms = (ex or {}).get("bottoms", []) or []
            outers = (ex or {}).get("outers", []) or []
            shoes = (ex or {}).get("shoes", []) or []
            acc = (ex or {}).get("accessories", []) or []
            avoid_list = (ex or {}).get("avoid", []) or []
            refs = (ex or {}).get("palette_refs", []) or []

            with st.expander(f"{i}) {title}", expanded=(i == 1)):
                if concept:
                    st.markdown("**1) 전체 스타일 컨셉(3줄 이내)**")
                    st.write(concept)

                st.markdown("**2) 상의 추천(3가지)**")
                st.markdown("\n".join([f"- {x}" for x in tops[:3]]))

                st.markdown("**3) 하의 추천(3가지)**")
                st.markdown("\n".join([f"- {x}" for x in bottoms[:3]]))

                st.markdown("**4) 아우터 추천(2가지)**")
                st.markdown("\n".join([f"- {x}" for x in outers[:2]]))

                st.markdown("**5) 신발 추천(2가지)**")
                st.markdown("\n".join([f"- {x}" for x in shoes[:2]]))

                st.markdown("**6) 가방/악세서리 추천**")
                if acc:
                    st.markdown("\n".join([f"- {x}" for x in acc]))
                else:
                    st.caption("악세서리 추천이 비어 있어요.")

                st.markdown("**7) 피해야 할 요소(최소 5개)**")
                if avoid_list:
                    st.markdown("\n".join([f"- {x}" for x in avoid_list[:10]]))
                else:
                    st.caption("피해야 할 요소가 비어 있어요.")

                if refs:
                    st.caption("팔레트 참고: " + ", ".join([str(x) for x in refs]))

        # ✅ 코디 이미지 생성(별도)
        st.markdown("### 🖼️ 추천 코디 이미지 생성")
        st.caption("선택한 코디를 ‘룩북 스타일’로 시각화합니다. (브랜드 로고/문구 없이)")
        titles = [(ex or {}).get("title", f"코디 {i+1}") for i, ex in enumerate(outfit_recos[:6])]
        pick_idx = st.selectbox("코디 선택", list(range(len(titles))), format_func=lambda x: titles[x], index=0, key="outfit_pick")

        cols_vis = st.columns([1, 1, 2])
        with cols_vis[0]:
            gen_outfit_btn = st.button("🧥 코디 이미지 생성", use_container_width=True)
        with cols_vis[1]:
            clear_outfit_imgs = st.button("🧹 코디 이미지 지우기", use_container_width=True)
        with cols_vis[2]:
            st.caption("※ 코디 이미지 생성과 메이크업 이미지 생성은 별개로 동작합니다.")

        if clear_outfit_imgs:
            st.session_state["outfit_images"] = []
            st.success("코디 이미지를 지웠어요.")
            st.rerun()

        if gen_outfit_btn:
            if not openai_key:
                st.warning("OpenAI API Key를 입력해 주세요.")
            else:
                ex = outfit_recos[pick_idx]
                title = (ex or {}).get("title", "outfit")
                concept = (ex or {}).get("concept", "")
                tops = (ex or {}).get("tops", []) or []
                bottoms = (ex or {}).get("bottoms", []) or []
                outers = (ex or {}).get("outers", []) or []
                shoes = (ex or {}).get("shoes", []) or []
                acc = (ex or {}).get("accessories", []) or []
                refs = (ex or {}).get("palette_refs", []) or []

                palette_map = {
                    c.get("name"): c.get("hex")
                    for c in (guide.get("fashion", {}) or {}).get("color_palette", [])
                    if isinstance(c, dict)
                }
                ref_hex = [f"{n}:{palette_map.get(n)}" for n in refs if palette_map.get(n)]
                items_join = ", ".join([*tops[:3], *bottoms[:3], *outers[:2], *shoes[:2], *acc[:6]])

                img_prompt = (
                    "Fashion lookbook photo, clean studio background, "
                    "full outfit worn by a faceless mannequin, no logos, no text.\n"
                    f"Gender styling target: {gender}\n"
                    f"Outfit title: {title}\n"
                    f"Concept: {concept}\n"
                    f"Items: {items_join if items_join else 'N/A'}\n"
                    f"Color references: {', '.join(ref_hex) if ref_hex else ', '.join(refs)}\n"
                    "High quality, realistic, editorial style, minimal, soft lighting."
                )

                with st.spinner("코디 이미지를 생성 중..."):
                    try:
                        b64_png, used_img_model = generate_image_with_fallback(
                            openai_key,
                            img_prompt,
                            image_model_candidates=image_model_candidates,
                            size=img_size_outfit,
                        )
                        st.session_state["outfit_images"].append(
                            {"title": title, "b64": b64_png, "prompt": img_prompt, "model": used_img_model}
                        )
                        st.success(f"생성 완료! (이미지 모델: {used_img_model})")
                    except Exception as e:
                        st.error(f"코디 이미지 생성 오류: {e}")

        if st.session_state.get("outfit_images"):
            st.markdown("#### 🧥 생성된 코디 이미지")
            cols = st.columns(3)
            for i, img in enumerate(st.session_state["outfit_images"][-6:]):
                with cols[i % 3]:
                    st.image(base64.b64decode(img["b64"]), caption=img.get("title", "outfit"), use_container_width=True)

    # -----------------------------
    # ✅ 메이크업 이미지 생성(별도) — 여성만
    # -----------------------------
    if gender == "female":
        st.divider()
        st.subheader("💄 추천 메이크업 이미지 생성")
        st.caption("리포트의 메이크업 가이드를 ‘뷰티 에디토리얼 참고 이미지’로 시각화합니다. (텍스트/로고 없음)")

        pts = (m.get("points") or {}) if isinstance(m, dict) else {}
        base_desc = (m.get("base") or "").strip()
        eye_desc = (pts.get("eyes") or "").strip()
        lip_desc = (pts.get("lips") or "").strip()
        avoid_desc = (m.get("avoid") or "").strip()

        makeup_title = "메이크업 룩(추천)"
        makeup_prompt = (
            "Beauty editorial close-up photo, anonymous model (no identity), "
            "clean background, soft lighting, no text, no logos.\n"
            "Makeup look description:\n"
            f"- Base: {base_desc}\n"
            f"- Eyes: {eye_desc}\n"
            f"- Lips: {lip_desc}\n"
            f"- Avoid: {avoid_desc}\n"
            "High quality, realistic, modern, tasteful, not exaggerated."
        )

        cols_mk = st.columns([1, 1, 2])
        with cols_mk[0]:
            gen_makeup_btn = st.button("💄 메이크업 이미지 생성", use_container_width=True)
        with cols_mk[1]:
            clear_makeup_imgs = st.button("🧹 메이크업 이미지 지우기", use_container_width=True)
        with cols_mk[2]:
            st.caption("※ 코디 이미지와 메이크업 이미지는 서로 독립적으로 생성/관리됩니다.")

        if clear_makeup_imgs:
            st.session_state["makeup_images"] = []
            st.success("메이크업 이미지를 지웠어요.")
            st.rerun()

        if gen_makeup_btn:
            if not openai_key:
                st.warning("OpenAI API Key를 입력해 주세요.")
            else:
                with st.spinner("메이크업 이미지를 생성 중..."):
                    try:
                        b64_png, used_img_model = generate_image_with_fallback(
                            openai_key,
                            makeup_prompt,
                            image_model_candidates=image_model_candidates,
                            size=img_size_makeup,
                        )
                        st.session_state["makeup_images"].append(
                            {"title": makeup_title, "b64": b64_png, "prompt": makeup_prompt, "model": used_img_model}
                        )
                        st.success(f"생성 완료! (이미지 모델: {used_img_model})")
                    except Exception as e:
                        st.error(f"메이크업 이미지 생성 오류: {e}")

        if st.session_state.get("makeup_images"):
            st.markdown("#### 💄 생성된 메이크업 이미지")
            cols = st.columns(3)
            for i, img in enumerate(st.session_state["makeup_images"][-6:]):
                with cols[i % 3]:
                    st.image(base64.b64decode(img["b64"]), caption=img.get("title", "makeup"), use_container_width=True)

st.divider()


# -----------------------------
# 챗봇: 사진으로 코디 피드백 + 대화
# -----------------------------
st.subheader("💬 추구미 챗봇에게 물어보기")
st.caption("선택 키워드/입력 내용을 바탕으로 ‘기준’과 ‘실천 팁’ 위주로 답해요. (브랜드 추천 없음)")

st.markdown("### 📸 사진으로 코디 피드백")
st.caption("내 코디 사진을 올리면, 이미 생성된 ‘추구미 리포트’ 기준으로 정합성/수정 포인트를 피드백해줘요. (얼굴/개인식별 분석 없음)")

chat_up = st.file_uploader("코디 사진 업로드 (jpg/png)", type=["jpg", "jpeg", "png"], key="chat_style_photo_uploader")
if chat_up is not None:
    cbytes = chat_up.read()
    st.session_state["chat_style_photo_bytes"] = cbytes
    st.session_state["chat_style_photo_name"] = chat_up.name
    st.image(cbytes, caption=f"업로드: {chat_up.name}", use_container_width=True)

cols_pf = st.columns([1, 1, 2])
with cols_pf[0]:
    run_photo_feedback = st.button("🧾 사진으로 피드백 받기", use_container_width=True)
with cols_pf[1]:
    clear_photo_feedback = st.button("🧹 사진/피드백 지우기", use_container_width=True)
with cols_pf[2]:
    st.caption("※ 사진 피드백은 ‘리포트가 있을 때’ 가장 정확합니다. 리포트 없이도 동작은 하지만 기준이 약해져요.")

if clear_photo_feedback:
    st.session_state["chat_style_photo_bytes"] = None
    st.session_state["chat_style_photo_name"] = None
    st.session_state["chat_style_feedback"] = None
    st.success("사진/피드백을 초기화했어요.")
    st.rerun()

if run_photo_feedback:
    if not openai_key:
        st.warning("OpenAI API Key를 입력해 주세요.")
    elif st.session_state.get("chat_style_photo_bytes") is None:
        st.warning("먼저 코디 사진을 업로드해 주세요.")
    else:
        with st.spinner("사진에서 스타일 요소를 분석하고, 리포트 기준으로 피드백을 생성 중..."):
            try:
                style_report = st.session_state.get("style_report") or {}
                fb_json, used_model = openai_vision_outfit_feedback_with_fallback(
                    openai_key,
                    st.session_state["chat_style_photo_bytes"],
                    style_report=style_report,
                    style_inputs=st.session_state["style_inputs"],
                    model_candidates=model_candidates,
                )
                st.session_state["chat_style_feedback"] = fb_json
                st.success(f"사진 피드백 생성 완료! (사용 모델: {used_model})")

                md = format_outfit_feedback_md(fb_json)
                st.session_state["style_messages"].append({"role": "assistant", "content": md})

            except Exception as e:
                st.error(f"사진 피드백 오류: {e}")

if st.session_state.get("chat_style_feedback"):
    st.markdown(format_outfit_feedback_md(st.session_state["chat_style_feedback"]))

st.divider()

for m in st.session_state["style_messages"]:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

chat_hint = "예: '지금 내 추구미에서 제일 자주 망하는 포인트 3개만 콕 집어줘.'"
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
            "gender": st.session_state["style_inputs"].get("gender", "female"),
            "selected_keywords": st.session_state["style_inputs"].get("keywords", []),
            "text_like": st.session_state["style_inputs"].get("text_like", ""),
            "text_dislike": st.session_state["style_inputs"].get("text_dislike", ""),
            "text_constraints": st.session_state["style_inputs"].get("text_constraints", ""),
            "uploaded_image_analysis": st.session_state["style_inputs"].get("uploaded_image_analysis"),
            "pinterest_hint": {
                "last_term": st.session_state.get("pinterest_last_term", ""),
                "pin_count": len(st.session_state.get("last_pins") or []),
            },
            "style_report_summary": {
                "type_name": (st.session_state.get("style_report") or {}).get("type_name_ko"),
                "identity_one_liner": (st.session_state.get("style_report") or {}).get("identity_one_liner"),
                "core_keywords": (st.session_state.get("style_report") or {}).get("core_keywords"),
                "mini": (st.session_state.get("style_report") or {}).get("mini_report"),
                "practice_guide": (st.session_state.get("style_report") or {}).get("practice_guide"),
            },
            "photo_feedback_summary": st.session_state.get("chat_style_feedback"),
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
