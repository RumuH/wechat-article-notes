"""Shared deterministic helpers. Never log private payloads or exception text."""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8 * 1024 * 1024


class SafeError(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def clean_text(value):
    if not isinstance(value, str):
        raise SafeError("invalid_text")
    return "\n\n".join(line.strip() for line in value.replace("\r", "").splitlines() if line.strip())


def canonical_url(value):
    if not value:
        return ""
    if not isinstance(value, str) or len(value) > 8192:
        raise SafeError("invalid_url")
    try:
        parts = urlsplit(value.strip())
        if (parts.scheme not in ("http", "https") or parts.hostname != "mp.weixin.qq.com"
                or parts.username or parts.password or parts.port not in (None, 80, 443)
                or not re.fullmatch(r"/s(?:/[A-Za-z0-9_-]+)?/?", parts.path)):
            raise SafeError("unsupported_url")
        # Retain only article identity, never temporary keys or tracking tokens.
        params = dict(parse_qsl(parts.query))
        identity = [(key, params[key]) for key in ("__biz", "mid", "idx", "sn") if params.get(key)]
        if parts.path.rstrip("/") == "/s" and not all(params.get(k) for k in ("__biz", "mid", "idx")):
            raise SafeError("missing_article_identity")
        return urlunsplit(("https", "mp.weixin.qq.com", parts.path.rstrip("/"), urlencode(identity), ""))
    except ValueError:
        raise SafeError("invalid_url") from None


def article_id(source, body_hash):
    if source:
        parts = urlsplit(source)
        params = dict(parse_qsl(parts.query))
        if all(params.get(k) for k in ("__biz", "mid", "idx")):
            return digest(json.dumps([params[k] for k in ("__biz", "mid", "idx")]))
        return digest(source)
    return body_hash


def quality(body, images=0):
    warnings = []
    if len(body) < 80:
        warnings.append("insufficient_text")
    if images and len(body) < images * 120:
        warnings.append("image_dominant")
    if re.search(r"(展开全文|剩余内容|登录后阅读全文|内容已截断|\[truncated\])", body, re.I):
        warnings.append("possibly_truncated")
    return warnings


def read_json():
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise SafeError("input_too_large")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise SafeError("invalid_payload")
    return value


def run(handler):
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = handler(read_json())
    except SafeError as exc:
        result = {"status": "failed", "error": str(exc)}
    except (ValueError, TypeError, KeyError):
        result = {"status": "failed", "error": "invalid_payload"}
    except Exception:
        result = {"status": "failed", "error": "operation_failed"}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] in ("failed", "conflict", "needs_input") else 0
