"""Family photos and videos — storage helpers."""

import re
from pathlib import Path

MEDIA_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "media"
PHOTO_MAX_BYTES = 15 * 1024 * 1024
VIDEO_MAX_BYTES = 50 * 1024 * 1024

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
ALLOWED_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}


def ensure_media_dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\- ]", "_", base).strip().replace(" ", "_")
    return cleaned[:120] or "media"


def media_type_for_ext(ext: str) -> str:
    return "video" if ext in VIDEO_EXTENSIONS else "photo"


def validate_upload(filename: str, size: int) -> tuple[str, str]:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"File type not allowed. Photos: {', '.join(sorted(PHOTO_EXTENSIONS))}; "
            f"videos: {', '.join(sorted(VIDEO_EXTENSIONS))}"
        )
    max_bytes = VIDEO_MAX_BYTES if ext in VIDEO_EXTENSIONS else PHOTO_MAX_BYTES
    if size > max_bytes:
        cap = "50 MB" if ext in VIDEO_EXTENSIONS else "15 MB"
        raise ValueError(f"File too large (max {cap})")
    return ext, media_type_for_ext(ext)


def mime_for_path(path: Path) -> str:
    return MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
