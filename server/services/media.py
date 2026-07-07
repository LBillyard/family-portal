"""Family photos and videos — storage helpers."""

import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from server import database as db

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(__file__).parent.parent.parent / "data" / "uploads" / "media"
PHOTO_MAX_BYTES = 40 * 1024 * 1024
VIDEO_MAX_BYTES = 500 * 1024 * 1024

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

# WhatsApp (Twilio) media arrives with a MIME type, not a filename — map it to an ext.
CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/3gpp": ".mp4",
}


def ext_for_content_type(ct: str) -> str | None:
    return CONTENT_TYPE_EXT.get((ct or "").split(";")[0].strip().lower())


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
        cap = "500 MB" if ext in VIDEO_EXTENSIONS else "40 MB"
        raise ValueError(f"File too large (max {cap})")
    return ext, media_type_for_ext(ext)


def mime_for_path(path: Path) -> str:
    return MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")


def save_inbound_media(image_bytes: bytes, content_type: str, user: dict, source: str = "whatsapp") -> dict | None:
    """Save already-downloaded inbound media bytes into the family gallery.

    This is the ONE place bytes hit the gallery (used by the WhatsApp webhook and
    by snap-and-sort's fallback path). Best-effort: it NEVER raises — on an unknown
    content-type, an over-cap file, or any write/DB failure it logs and returns
    None so a photo is never lost to an exception. Returns the created media row on
    success, else None."""
    ext = ext_for_content_type(content_type)
    if not ext:
        logger.warning("save_inbound_media: unknown content-type %r — skipping", content_type)
        return None
    is_video = ext in VIDEO_EXTENSIONS
    cap = VIDEO_MAX_BYTES if is_video else PHOTO_MAX_BYTES
    if len(image_bytes) > cap:
        logger.warning("save_inbound_media: media too large (%d bytes) — skipping", len(image_bytes))
        return None
    try:
        ensure_media_dir()
        mid = uuid.uuid4().hex[:12]
        stored = f"{mid}_{source}{ext}"
        (MEDIA_DIR / stored).write_bytes(image_bytes)
        label = "video" if is_video else "photo"
        title = f"WhatsApp {label}" if source == "whatsapp" else f"{source} {label}"
        return db.create_media({
            "id": mid,
            "title": title,
            "media_type": media_type_for_ext(ext),
            "file_name": stored,
            "file_path": stored,
            "mime_type": (content_type or "").split(";")[0].strip() or None,
            "file_size": len(image_bytes),
            "user_id": user["id"],
            "source": source,
        })
    except Exception:
        logger.exception("save_inbound_media: failed to store media")
        return None


async def stream_upload_to_disk(upload_file, dest_path: Path, max_bytes: int) -> int:
    """Stream an UploadFile to disk in 1MB chunks (avoids buffering the whole file
    in RAM). Enforces max_bytes and cleans up the partial file on any failure —
    including ENOSPC (disk full). Returns the number of bytes written."""
    written = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await upload_file.read(1024 * 1024)  # 1MB
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    dest_path.unlink(missing_ok=True)
                    raise ValueError("File too large")
                out.write(chunk)
    except OSError as exc:
        dest_path.unlink(missing_ok=True)
        raise ValueError("Not enough storage space on the server") from exc
    return written


def storage_stats() -> dict:
    """Disk + media usage for the media directory's filesystem. `low` flags when the
    box is running out of room (<1GB free or >=90% used)."""
    ensure_media_dir()
    du = shutil.disk_usage(MEDIA_DIR)
    media_bytes = 0
    media_count = 0
    for e in os.scandir(MEDIA_DIR):
        if e.is_file():
            media_bytes += e.stat().st_size
            media_count += 1
    pct = round(du.used / du.total * 100, 1) if du.total else 0
    # "Low" is primarily about absolute free space (<1GB); the >=90%-used arm only
    # counts as low when the disk is also small (free < 5GB), so a big volume with
    # tens of GB free isn't false-flagged just for being 90% full.
    low = du.free < 1024**3 or (pct >= 90 and du.free < 5 * 1024**3)
    return {
        "disk_total": du.total,
        "disk_used": du.used,
        "disk_free": du.free,
        "media_bytes": media_bytes,
        "media_count": media_count,
        "disk_pct_used": pct,
        "low": low,
    }
