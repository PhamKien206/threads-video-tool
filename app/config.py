"""
config.py — Đọc/ghi cấu hình (config.json ở thư mục gốc dự án).

Mọi module đều lấy cấu hình qua get_config() để không có nhiều "bản" cấu hình lệch nhau.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("TTV_CONFIG_PATH") or BASE_DIR / "config.json")
# Có thể đổi bằng biến môi trường (selftest dùng để chạy cô lập, không đụng thư viện thật)
LIBRARY_DIR = Path(os.environ.get("TTV_LIBRARY_DIR") or BASE_DIR / "library")
PROJECTS_DIR = Path(os.environ.get("TTV_PROJECTS_DIR") or BASE_DIR / "projects")
CACHE_DIR = BASE_DIR / "cache"
FONTS_DIR = BASE_DIR / "app" / "fonts"
PROMPTS_DIR = BASE_DIR / "app" / "prompts"

DEFAULT_CONFIG: dict = {
    # --- AI ---
    "llm_provider": "gemini",          # gemini | claude | openai | zai | openrouter
    "gemini_api_key": "",
    "claude_api_key": "",
    "openai_api_key": "",
    "zai_api_key": "",
    "openrouter_api_key": "",
    "openai_base_url": "",             # để trống = api.openai.com (điền để dùng dịch vụ tương thích OpenAI khác)
    "llm_model": "",                   # để trống = dùng model mặc định của nhà cung cấp
    "ollama_url": "http://localhost:11434",   # AI chạy trên máy (Ollama) — không cần key
    "ollama_model": "qwen3.5:4b",
    "ollama_vision_model": "",         # để trống = dùng chung ollama_model (qwen3.5 đọc được ảnh)
    "fallback_provider": "",           # nhà cung cấp dự phòng khi nhà cung cấp chính hết tiền/hết hạn mức ("" = tắt)
    "fallback_model": "",
    # --- Giọng đọc ---
    "tts_engine": "edge",              # edge | vieneu
    "tts_voice": "vi-VN-HoaiMyNeural",
    "tts_speed": "+15%",
    # --- Âm thanh ---
    "music_volume": 0.12,
    "sfx_volume": 0.40,
    # --- Video ---
    "max_duration": 90,
    "meme_density": "vừa",             # ít | vừa | nhiều
    "hide_author": False,              # che tên tác giả bài gốc
    "show_transition": True,
    "transition_text": "Và đây là bình luận của cư dân mạng:",
    "auto_mode": False,
    "watermark": False,
    "channel_name": "",
    "meme_video_audio": True,          # phát tiếng của meme dạng video (thay tiếng "bụp")
    # --- Thư mục (đường dẫn tương đối tính từ thư mục tool, hoặc đường dẫn đầy đủ như D:\\Gameplay) ---
    "background_dir": "nen_video",
    "meme_dir": "meme",
    "approved_dir": "video_da_duyet",
    "music_dir": "nhac_nen",
    "music_mode": "random",            # random = ngẫu nhiên mỗi video | none = không nhạc (chọn bài cụ thể ở bước Duyệt)
    # --- Threads ---
    "threads_cookie": "",
    "comment_min": 3,
    "comment_max": 6,
}

# Các key bí mật: không bao giờ trả nguyên văn xuống frontend.
SECRET_KEYS = {"gemini_api_key", "claude_api_key", "openai_api_key", "zai_api_key", "openrouter_api_key",
               "threads_cookie"}

_lock = threading.Lock()


def load_config() -> dict:
    """Đọc config.json, bổ sung các key mặc định còn thiếu."""
    merged = DEFAULT_CONFIG.copy()
    if not CONFIG_PATH.exists():
        save_config(merged)
        return merged
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"File config.json bị lỗi định dạng JSON: {e}. Sửa lại hoặc xóa file để tạo mới.")
    if not isinstance(data, dict):
        data = {}
    # Tương thích bản cũ: "llm_api_key" dùng chung cho mọi nhà cung cấp
    legacy = data.pop("llm_api_key", "")
    if legacy:
        provider = data.get("llm_provider", "gemini")
        data.setdefault(f"{provider}_api_key", legacy)
    merged.update(data)
    return merged


def save_config(data: dict) -> None:
    with _lock:
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)


def get_config() -> dict:
    """Luôn đọc lại từ đĩa (file nhỏ) để không bị lệch khi người dùng sửa tay."""
    return load_config()


def update_config(**kwargs: Any) -> dict:
    cfg = load_config()
    cfg.update(kwargs)
    save_config(cfg)
    return cfg


def mask_secret(val: str) -> str:
    if not val:
        return ""
    return "****" + val[-4:] if len(val) > 4 else "****"


def public_config() -> dict:
    """Cấu hình an toàn để gửi xuống frontend (key đã che)."""
    cfg = load_config()
    out = {}
    for k, v in cfg.items():
        if k in SECRET_KEYS:
            out[k] = mask_secret(v if isinstance(v, str) else "")
            out[f"{k}_set"] = bool(v)
        else:
            out[k] = v
    return out


def get_api_key(cfg: dict, provider: str | None = None) -> str:
    provider = (provider or cfg.get("llm_provider") or "gemini").lower()
    provider = {"gpt": "openai", "z.ai": "zai", "glm": "zai"}.get(provider, provider)
    return (cfg.get(f"{provider}_api_key") or "").strip()


MEDIA_KINDS = {"background": "background_dir", "meme": "meme_dir", "approved": "approved_dir", "music": "music_dir"}
_ISOLATED_SUBDIRS = {"background": "backgrounds", "meme": "memes", "approved": "approved", "music": "music"}


def media_dir(kind: str, cfg: dict | None = None) -> Path:
    """Thư mục video nền / meme / video đã duyệt theo cấu hình (tạo nếu chưa có)."""
    if kind not in MEDIA_KINDS:
        raise ValueError(f"Loại thư mục không hợp lệ: {kind}")
    if os.environ.get("TTV_LIBRARY_DIR"):  # selftest: chạy cô lập
        d = LIBRARY_DIR / _ISOLATED_SUBDIRS[kind]
    else:
        cfg = cfg or load_config()
        raw = str(cfg.get(MEDIA_KINDS[kind]) or DEFAULT_CONFIG[MEDIA_KINDS[kind]]).strip().strip('"')
        p = Path(os.path.expandvars(os.path.expanduser(raw)))
        d = p if p.is_absolute() else BASE_DIR / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def has_llm(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    if (cfg.get("llm_provider") or "").lower() == "ollama":
        return True          # AI trên máy: không cần key (lỗi kết nối sẽ báo khi gọi)
    return bool(get_api_key(cfg))
