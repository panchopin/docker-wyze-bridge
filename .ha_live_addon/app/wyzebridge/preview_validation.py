import hashlib
import json
import time
from io import BytesIO
from pathlib import Path
from statistics import mean, pstdev

SNAPSHOT_HASH_REGISTRY = ".snapshot_hashes.json"


def preview_bytes_are_image(payload: bytes) -> bool:
    if not payload:
        return False

    header = payload[:16]
    return (
        header.startswith(b"\xff\xd8\xff")
        or header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith((b"GIF87a", b"GIF89a"))
        or (len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def _has_vertical_smear(payload: bytes) -> bool:
    try:
        from PIL import Image

        with Image.open(BytesIO(payload)) as image:
            frame = image.convert("L").resize((160, 90))
    except ImportError:
        return False
    except Exception:
        return True

    for top in range(0, frame.height - 20, 10):
        region = frame.crop((0, top, frame.width, min(frame.height, top + 30)))
        pixels = region.load()
        column_deviation = []
        row_deviation = []

        for x in range(region.width):
            column_deviation.append(pstdev(pixels[x, y] for y in range(region.height)))
        for y in range(region.height):
            row_deviation.append(pstdev(pixels[x, y] for x in range(region.width)))

        mean_column_deviation = mean(column_deviation)
        mean_row_deviation = mean(row_deviation)
        flat_column_ratio = sum(1 for value in column_deviation if value < 8) / len(column_deviation)
        if (
            mean_column_deviation <= 1.5
            and mean_row_deviation >= 15
            and flat_column_ratio >= 0.95
            and mean_row_deviation / (mean_column_deviation + 0.01) >= 20
        ):
            return True
    return False


def preview_bytes_are_valid_image(payload: bytes) -> bool:
    return preview_bytes_are_image(payload) and not _has_vertical_smear(payload)


def preview_file_is_image(path: str | Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            return preview_bytes_are_valid_image(handle.read())
    except OSError:
        return False


def preview_content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def preview_file_hash(path: str | Path) -> str | None:
    try:
        with Path(path).open("rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except OSError:
        return None


def preview_payload_matches_existing(path: str | Path, payload: bytes) -> bool:
    existing_hash = preview_file_hash(path)
    return existing_hash is not None and existing_hash == preview_content_hash(payload)


def snapshot_hash_registry_path(img_dir: str | Path) -> Path:
    return Path(img_dir) / SNAPSHOT_HASH_REGISTRY


def read_snapshot_hash_registry(img_dir: str | Path) -> dict:
    try:
        data = json.loads(snapshot_hash_registry_path(img_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def snapshot_hash_entry(img_dir: str | Path, camera: str) -> dict:
    entry = read_snapshot_hash_registry(img_dir).get(camera, {})
    return entry if isinstance(entry, dict) else {}


def record_preview_hash(
    path: str | Path,
    payload: bytes | None = None,
    *,
    camera: str | None = None,
    source: str = "",
) -> str | None:
    snapshot_path = Path(path)
    try:
        content = payload if payload is not None else snapshot_path.read_bytes()
    except OSError:
        return None

    digest = preview_content_hash(content)
    registry_path = snapshot_hash_registry_path(snapshot_path.parent)
    registry = read_snapshot_hash_registry(snapshot_path.parent)
    registry[camera or snapshot_path.stem] = {
        "sha256": digest,
        "bytes": len(content),
        "source": source,
        "recorded_at": int(time.time()),
    }

    try:
        tmp_path = registry_path.with_name(registry_path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(registry, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(registry_path)
    except OSError:
        return digest
    return digest
