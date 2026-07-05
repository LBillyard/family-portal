"""Document vault — file storage helpers."""

import re
from pathlib import Path

UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
MAX_BYTES = 15 * 1024 * 1024  # 15 MB
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".doc", ".docx"}
VALID_CATEGORY_IDS = {
    "insurance", "passport", "mot", "legal", "medical", "finance", "property", "other",
}
MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

DOCUMENT_CATEGORIES = [
    {"id": "insurance", "label": "Insurance"},
    {"id": "passport", "label": "Passport & ID"},
    {"id": "mot", "label": "MOT & vehicle"},
    {"id": "legal", "label": "Legal & wills"},
    {"id": "medical", "label": "Medical"},
    {"id": "finance", "label": "Finance & tax"},
    {"id": "property", "label": "Property"},
    {"id": "other", "label": "Other"},
]


def ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\- ]", "_", base).strip().replace(" ", "_")
    return cleaned[:120] or "document"


def validate_upload(filename: str, size: int) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type not allowed. Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    if size > MAX_BYTES:
        raise ValueError("File too large (max 15 MB)")
    return ext


def validate_category(category: str) -> str:
    normalized = (category or "other").strip().lower()
    return normalized if normalized in VALID_CATEGORY_IDS else "other"


def mime_for_path(path: Path) -> str:
    return MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
