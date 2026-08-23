from __future__ import annotations

import base64
import io
import ctypes
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageOps

ROOT = Path(os.getenv("MUSE_VAULT_HOME", Path(__file__).resolve().parents[1] / "data"))
CONFIG_PATH = ROOT / "ai-config.json"
TAG_LIMIT = 4
VISION_MAX_EDGE = 1280
VISION_MAX_BYTES = 1_500_000
# The previous 420-token ceiling truncated complete reverse-prompt JSON on
# detailed portraits. Keep the request bounded, but leave enough room for
# all nine required fields to close the JSON object.
VISION_MAX_TOKENS = 700
VISION_PROMPT = (
    "你是图片反向提示词分析器。只看输入图片，不猜身份；只返回一个完整、紧凑的 JSON 对象，不要 Markdown、解释或思考过程。"
    "字段必须有 summary、tags、entities、category、subcategory、visual_description、prompt_positive、prompt_negative、verification_checklist。"
    "prompt_positive 用简洁英文逗号短语，按媒介/风格、构图、主体、精确发型脸部、服装剪裁与面料、边缘物体、环境、光线、技术参数排序。"
    "服装必须区分 cap sleeves、sleeveless、spaghetti straps、off-shoulder、mandarin collar，禁止含糊写 exposed shoulder；发型使用 wispy air bangs、low bun 等具体词；明确 headless、裁切、视线、材质和光线。"
    "prompt_negative 用简洁英文逗号短语，按图片内容生成，且始终包含 bad anatomy、text、watermark、ambiguous clothing。"
    "verification_checklist 必须是一个字符串，只写三项中文短句并用分号分隔：空间边缘、服装剪裁、光线色温；看不清就写 uncertain，不要编造。"
    "summary 最多 60 字，visual_description 最多 220 字，prompt_positive 最多 650 个英文字符，prompt_negative 最多 220 个英文字符；tags 只返回 3-4 个中文概念标签，entities 最多 8 个，category 只用 图片/视频/文档/网页。"
    "不要重复字段或长篇解释，确保 JSON 在输出上限内完整闭合。"
)
TAG_ALIASES = {
    "人像摄影": "人像", "人物摄影": "人像", "人物": "人像",
    "长发女性": "女性", "短发女性": "女性", "长发女生": "女性", "少女": "女性",
    "户外写真": "户外", "户外人像": "户外", "日系人像": "日系", "日系写真": "日系",
    "清新自然": "清新", "清新治愈": "清新", "自然光摄影": "自然光",
    "绿色背景": "绿色", "红色主题": "红色", "红色气球": "红色", "红色花朵": "红色",
    "粉色花朵": "粉色", "浅色服装": "浅色", "小红书风格": "小红书",
    "推荐流": "推荐", "信息流": "信息流", "社交媒体": "社交",
    "网页截图": "网页", "App界面": "界面", "中文界面": "界面",
    "唯美风格": "唯美", "极简风格": "极简", "复古风格": "复古",
    "视觉风格": "风格", "氛围感": "氛围", "柔光": "柔光", "光影": "光影",
    "技术考试": "考试", "生活分享": "生活", "HCIA": "认证", "HCIP": "认证", "HCIE": "认证",
    "Pearson VUE": "考试", "JK制服": "人像", "仙气写真": "梦幻", "蝴蝶翅膀": "梦幻",
    "浅绿色礼服": "绿色", "绿色毛衣": "绿色", "白色连衣裙": "人像", "浅色服装": "人像",
    "蓝天白云": "户外", "侧脸": "人像", "窗边": "室内", "红色气球": "红色",
    "复古布景": "复古", "水花": "水景", "水面倒影": "水景", "内容推荐": "推荐",
}
TAG_CONCEPT_RULES = (
    ("人像", ("人像", "人物", "女性", "女生", "少女", "男士", "男子", "孕妇", "长发", "短发", "写真")),
    ("婚礼", ("婚纱", "婚礼", "新娘")),
    ("动物", ("动物", "宠物", "猫", "狗", "鸟")),
    ("花朵", ("花朵", "花卉", "樱花", "鲜花")),
    ("植物", ("植物", "绿植", "树木", "森林")),
    ("食物", ("食物", "美食", "饮品", "甜品")),
    ("建筑", ("建筑", "室内设计", "空间设计")),
    ("界面", ("界面", "app", "ui", "网站", "网页")),
    ("户外", ("户外", "室外", "天空", "海边", "公园")),
    ("室内", ("室内", "棚拍", "房间", "窗边")),
    ("城市", ("城市", "街道", "街景", "都市")),
    ("水景", ("水面", "水花", "湖", "海", "河流")),
    ("红色", ("红色", "红调")), ("蓝色", ("蓝色", "蓝调")), ("绿色", ("绿色", "绿调")),
    ("粉色", ("粉色", "粉调")), ("黑白", ("黑白", "单色")),
    ("清新", ("清新", "治愈")), ("复古", ("复古", "怀旧")), ("极简", ("极简", "简约")),
    ("日系", ("日系", "日式")), ("时尚", ("时尚", "潮流")), ("唯美", ("唯美", "优雅")),
    ("梦幻", ("梦幻", "仙气", "童话")), ("暗调", ("暗调", "低调")), ("明亮", ("明亮", "阳光")),
    ("技术", ("技术", "软件", "硬件", "网络")), ("科学", ("科学", "研究")),
    ("设计", ("设计", "视觉")), ("教育", ("教育", "学习", "教程")),
    ("商业", ("商业", "职场", "营销")), ("生活", ("生活", "日常")),
    ("旅行", ("旅行", "旅游")), ("摄影", ("摄影", "拍摄", "光影", "逆光")),
    ("AI", ("人工智能", "ai")), ("编程", ("编程", "代码", "开发")),
    ("认证", ("认证", "hcia", "hcip", "hcie")), ("考试", ("考试", "报名")),
    ("社交", ("社交", "社区", "小红书")), ("推荐", ("推荐", "信息流")),
)


def redact_sensitive_text(value: object) -> str:
    """Remove common credential shapes before errors reach logs or the UI."""
    text = str(value)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{6,}", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "sk-[REDACTED]", text)
    text = re.sub(
        r"(?i)((?:api[_-]?key|access[_-]?token|secret)\s*[=:]\s*[\"']?)[^\"'\s,}&]+",
        r"\1[REDACTED]",
        text,
    )
    return text


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect(value: str) -> str:
    if os.name != "nt":
        return base64.b64encode(value.encode("utf-8")).decode("ascii")
    raw = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "Muse Vault AI", None, None, None, 0, ctypes.byref(target)):
        raise OSError("Windows DPAPI could not protect the AI key")
    try:
        encrypted = ctypes.string_at(target.pbData, target.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _unprotect(value: str) -> str:
    encrypted = base64.b64decode(value)
    if os.name != "nt":
        return encrypted.decode("utf-8")
    buffer = ctypes.create_string_buffer(encrypted)
    source = DataBlob(len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise OSError("Windows DPAPI could not read the AI key")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _stored_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_ai_config() -> dict:
    stored = _stored_config()
    encrypted_key = stored.get("api_key_encrypted")
    stored_key = ""
    if encrypted_key:
        try:
            stored_key = _unprotect(encrypted_key)
        except (OSError, ValueError):
            stored_key = ""
    return {
        "base_url": os.getenv("MUSE_AI_BASE_URL", stored.get("base_url", "")).strip(),
        "model": os.getenv("MUSE_AI_MODEL", stored.get("model", "")).strip(),
        "api_key": os.getenv("MUSE_AI_API_KEY", stored_key).strip(),
    }


def public_ai_status() -> dict:
    config = load_ai_config()
    stored = _stored_config()
    return {
        "configured": bool(config["base_url"] and config["model"] and config["api_key"]),
        "base_url": config["base_url"],
        "model": config["model"],
        "api_key_configured": bool(config["api_key"]),
        "protocol": "openai-compatible",
        "validated": bool(stored.get("validated_models") is not None),
        "available_models": stored.get("validated_models", []),
    }


def compact_tags(values: list[str] | None, limit: int = TAG_LIMIT) -> list[str]:
    """Keep tags at concept level and collapse common near-duplicates."""
    result: list[str] = []
    for value in values or []:
        clean = " ".join(str(value).replace("#", "").split()).strip("，,。.!！？?、;；:：\"'“”")
        if not clean or len(clean) > 16:
            continue
        clean = TAG_ALIASES.get(clean, clean)
        lowered = clean.lower()
        concept = next((name for name, needles in TAG_CONCEPT_RULES if any(needle in lowered for needle in needles)), None)
        clean = concept or (clean if clean in {"清新", "复古", "极简", "日系", "时尚", "唯美", "梦幻", "暗调", "明亮", "技术", "科学", "设计", "教育", "商业", "生活", "旅行", "摄影", "AI", "编程", "认证", "考试", "社交", "推荐"} else "")
        if len(clean) < 2 or clean in result:
            continue
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def _validated_base_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI API 地址必须是有效的 http/https 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("AI API 地址不能包含账号密码、查询参数或片段")
    hostname = (parsed.hostname or "").lower()
    is_loopback = hostname == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if parsed.scheme != "https" and not is_loopback:
        raise ValueError("非本机 AI API 必须使用 https，避免 API Key 在网络中明文传输")
    return base


def _models_url(base_url: str) -> str:
    base = _validated_base_url(base_url)
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def _request_json(request: urllib.request.Request, timeout: int = 20) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = redact_sensitive_text(error.read(800).decode("utf-8", errors="replace"))
        raise RuntimeError(f"AI API 返回 {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"AI API 无法连接：{redact_sensitive_text(error.reason)}") from error


def available_models(base_url: str, api_key: str) -> list[str]:
    data = _request_json(urllib.request.Request(_models_url(base_url), headers={"Authorization": f"Bearer {api_key}"}))
    return [str(item["id"]) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]


def validate_ai_config(base_url: str, model: str, api_key: str) -> list[str]:
    base_url = _validated_base_url(base_url)
    if not model.strip():
        raise ValueError("模型名称不能为空")
    if not api_key.strip():
        raise ValueError("API Key 不能为空")
    try:
        models = available_models(base_url, api_key)
    except RuntimeError as error:
        # Some OpenAI-compatible gateways do not expose /models. The tiny
        # completion probe still verifies the endpoint and model ID.
        if "返回 404" not in str(error):
            raise
        probe = json.dumps({"model": model.strip(), "messages": [{"role": "user", "content": "Return only OK"}], "temperature": 0, "max_tokens": 4}, ensure_ascii=False).encode("utf-8")
        _request_json(urllib.request.Request(_chat_url(base_url), data=probe, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST"), timeout=30)
        return []
    if models and model.strip() not in models:
        choices = "、".join(models[:12])
        suffix = f"。可用模型：{choices}" if choices else ""
        raise ValueError(f"模型 {model.strip()} 不受该接口支持{suffix}")
    return models


def save_ai_config(base_url: str, model: str, api_key: str | None) -> dict:
    current = _stored_config()
    normalized_base_url = _validated_base_url(base_url)
    model_value = model.strip()
    if not model_value:
        raise ValueError("模型名称不能为空")
    supplied_key = (api_key or "").strip()
    previous_base_url = str(current.get("base_url") or "").rstrip("/")
    if previous_base_url and previous_base_url != normalized_base_url and not supplied_key:
        raise ValueError("AI API 地址已改变，请重新输入该地址对应的 API Key")
    effective_key = supplied_key
    if not effective_key and current.get("api_key_encrypted"):
        try:
            effective_key = _unprotect(current["api_key_encrypted"])
        except (OSError, ValueError):
            effective_key = ""
    if not effective_key:
        raise ValueError("API Key 不能为空")
    # Persist first: even when the endpoint is unreachable (offline demo,
    # firewall, temporary outage) the entered values must survive a restart.
    payload = {
        "base_url": normalized_base_url,
        "model": model_value,
        "api_key_encrypted": _protect(effective_key),
        "validated_models": current.get("validated_models", []),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    staged_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".writing")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        with staged_path.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged_path, CONFIG_PATH)
    finally:
        staged_path.unlink(missing_ok=True)
    # Optional online validation. A failure is reported as a warning and never
    # discards the saved configuration, so the user's input is always kept.
    try:
        models = validate_ai_config(normalized_base_url, model_value, effective_key)
        if models:
            payload["validated_models"] = models[:100]
            try:
                with staged_path.open("wb") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(staged_path, CONFIG_PATH)
            finally:
                staged_path.unlink(missing_ok=True)
        status = public_ai_status()
        status["validated"] = True
        status["available_models"] = models[:100]
        status["validation_warning"] = ""
    except Exception as error:
        status = public_ai_status()
        status["validated"] = False
        status["available_models"] = []
        status["validation_warning"] = redact_sensitive_text(error)
    return status


def _chat_url(base_url: str) -> str:
    base = _validated_base_url(base_url)
    return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"


def chat_completion(messages: list[dict], temperature: float = 0.1, max_tokens: int = 700) -> tuple[str, dict, str]:
    config = load_ai_config()
    if not (config["base_url"] and config["model"] and config["api_key"]):
        raise RuntimeError("AI API 尚未配置")
    body = json.dumps({
        "model": config["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max(64, min(int(max_tokens), 700)),
        "thinking": {"type": "disabled"},
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _chat_url(config["base_url"]),
        data=body,
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            detail = redact_sensitive_text(error.read(600).decode("utf-8", errors="replace"))
            if error.code in {408, 425, 429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(1 << attempt)
                continue
            raise RuntimeError(f"AI API 返回 {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            if attempt >= 2:
                raise RuntimeError(f"AI API 网络连接失败：{redact_sensitive_text(error)}") from error
            time.sleep(1 << attempt)
    message = data["choices"][0].get("message", {})
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not str(content).strip():
        raise RuntimeError("AI API 返回了空内容，请稍后自动重试")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return str(content), usage, config["model"]


def _json_result(value: str) -> dict:
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 没有返回 JSON 结果")
    return json.loads(value[start:end + 1])


def interpret_material_assistant_query(query: str) -> dict:
    """Turn one explicit assistant request into bounded retrieval/action fields.

    This function never performs an action. The API layer still creates a
    preview plan and requires a separate confirmation token before writes.
    """
    system = (
        "你是本机素材库的查询解析器。只返回一个 JSON 对象，不要解释。"
        "intent 只能是 search、add_tags、remove_tags、move_folder；"
        "material_type 只能是 image、video、document、page 或 null；"
        "color_family 只能是 blue、green、warm、pink、neutral 或 null；"
        "color_name 只能是 red、orange、yellow、green、cyan、blue、purple、pink、gray、black、white、warm、cool、neutral 或 null；"
        "brightness 只能是 dark、medium、bright 或 null。"
        "字段必须包含 intent、concepts、negative_concepts、material_type、color_family、color_name、brightness、tags、folder_name。"
        "concepts 只保留用户想找的对象、场景、风格或主题，最多 6 个；tags 最多 5 个。"
        "不要把删除素材理解成任何可执行动作；若用户要求删除素材，intent 必须返回 search。"
    )
    content, usage, model = chat_completion([
        {"role": "system", "content": system},
        {"role": "user", "content": query.strip()},
    ], temperature=0)
    raw = _json_result(content)
    allowed_intents = {"search", "add_tags", "remove_tags", "move_folder"}
    allowed_types = {"image", "video", "document", "page"}
    allowed_colors = {"blue", "green", "warm", "pink", "neutral"}
    allowed_color_names = {"red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink", "gray", "black", "white", "warm", "cool", "neutral"}
    allowed_brightness = {"dark", "medium", "bright"}

    def clean_list(value: object, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            clean = " ".join(str(item).split()).strip("，,。.!！？?、;；:：\"'“”")[:40]
            if clean and clean not in result:
                result.append(clean)
            if len(result) >= limit:
                break
        return result

    intent = str(raw.get("intent") or "search")
    result = {
        "intent": intent if intent in allowed_intents else "search",
        "concepts": clean_list(raw.get("concepts"), 6),
        "negative_concepts": clean_list(raw.get("negative_concepts"), 4),
        "material_type": raw.get("material_type") if raw.get("material_type") in allowed_types else None,
        "color_family": raw.get("color_family") if raw.get("color_family") in allowed_colors else None,
        "color_name": raw.get("color_name") if raw.get("color_name") in allowed_color_names else None,
        "brightness": raw.get("brightness") if raw.get("brightness") in allowed_brightness else None,
        "tags": clean_list(raw.get("tags"), 5),
        "folder_name": str(raw.get("folder_name") or "").strip()[:100] or None,
        "_usage": usage,
        "_model": model,
    }
    return result


def build_vision_preview(path: Path) -> bytes:
    """Return a bounded JPEG preview so vision requests cannot upload the original file."""
    with Image.open(path) as source:
        source.seek(0)
        original = ImageOps.exif_transpose(source).convert("RGB")
        for edge in (VISION_MAX_EDGE, 1024, 768, 640, 512, 384):
            image = original.copy()
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            for quality in (82, 72, 62, 52):
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True)
                payload = buffer.getvalue()
                if len(payload) <= VISION_MAX_BYTES:
                    return payload
    raise ValueError("图片无法压缩到 AI 请求的安全体积限制内")


def analyze_material(material: dict) -> dict:
    system = VISION_PROMPT if material.get("material_type") == "image" else (
        "你是本机素材库的整理代理。只根据用户提供的素材返回 JSON，不要输出解释。"
        "字段必须包含 summary、tags、entities、category、subcategory、visual_description。"
        "tags 只返回 3-4 个概念级中文标签，优先对象、主题、主色或风格；不要输出动作、服装、镜头参数、完整句子或近义重复词。category 只用 图片/视频/文档/网页。"
    )
    description = "\n".join([
        f"标题：{material.get('title', '')}",
        f"类型：{material.get('material_type', '')}",
        f"来源：{material.get('source_name', '')}",
        f"正文：{(material.get('text_content') or '')[:16000]}",
    ])
    user_content: str | list[dict] = description
    local_path = material.get("local_path")
    if material.get("material_type") == "image" and local_path and Path(local_path).exists():
        path = Path(local_path)
        # Vision calls use a bounded JPEG preview rather than the original
        # asset, keeping request size and provider billing predictable.
        encoded = base64.b64encode(build_vision_preview(path)).decode("ascii")
        user_content = [
            {"type": "text", "text": description[:1200]},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ]
    content, usage, model = chat_completion([
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ], max_tokens=VISION_MAX_TOKENS if material.get("material_type") == "image" else 700)
    result = _json_result(content)
    result["tags"] = compact_tags(result.get("tags", []))
    result["entities"] = [str(entity).strip()[:80] for entity in result.get("entities", []) if str(entity).strip()][:20]
    if material.get("material_type") == "image":
        result["prompt_positive"] = str(result.get("prompt_positive") or "")[:900]
        negative = str(result.get("prompt_negative") or "").strip()
        required_negative = "bad anatomy, text, watermark, ambiguous clothing"
        result["prompt_negative"] = ", ".join(dict.fromkeys((negative + ", " + required_negative).split(", ")))[:360]
        checklist = result.get("verification_checklist")
        if isinstance(checklist, list):
            checklist = "；".join(str(item).strip() for item in checklist if str(item).strip())
        result["verification_checklist"] = str(checklist or "")[:360]
        result["visual_description"] = str(result.get("visual_description") or result.get("prompt_positive") or "")[:2200]
    result["_usage"] = usage
    result["_model"] = model
    return result
