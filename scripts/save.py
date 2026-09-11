"""Configure an external vault and save notes without overwriting existing files."""
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, VERSION, SafeError, article_id, canonical_url, clean_text, digest, quality, run

SECTIONS = ("abstract", "claims", "evidence", "limitations", "analysis")
HEADINGS = ("摘要", "核心观点（作者主张）", "依据与案例（原文证据）", "局限与待核实", "智能体分析与启发")


def outside_repo(path):
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(ROOT):
        raise SafeError("private_path_inside_skill")
    # Also guard an installed copy living inside another Git checkout.
    for parent in ROOT.parents:
        if (parent / ".git").exists() and resolved.is_relative_to(parent):
            raise SafeError("private_path_inside_repository")
    return resolved


def config_path():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return outside_repo(base / "wechat-article-notes" / "config.json")


def vault_path(value):
    if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
        raise SafeError("vault_must_be_absolute")
    path = outside_repo(Path(value))
    if ROOT.is_relative_to(path):
        raise SafeError("vault_contains_skill")
    return path


def atomic_write(path, data, replace=False):
    if path.is_symlink():
        raise SafeError("symlink_target")
    fd, temporary = tempfile.mkstemp(prefix=".wan-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Atomic no-clobber publication; hard links are supported by NTFS and normal Unix filesystems.
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def vault_lock(vault):
    lock = vault / ".wechat-article-notes.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SafeError("vault_busy") from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def read_config():
    path = config_path()
    if not path.exists():
        raise SafeError("vault_not_configured")
    return vault_path(json.loads(path.read_text(encoding="utf-8"))["vault"])


def metadata_of(path):
    if path.is_symlink():
        raise SafeError("symlink_note")
    try:
        with path.open(encoding="utf-8") as stream:
            if stream.readline().strip() != "---":
                raise ValueError
            result = {}
            for _ in range(30):
                line = stream.readline(16384)
                if line.strip() == "---":
                    return result
                key, value = line.split(":", 1)
                result[key] = json.loads(value)
            raise ValueError
    except (ValueError, UnicodeError):
        raise SafeError("existing_note_metadata_changed") from None


def validate_note(payload):
    article = payload["article"]
    body = clean_text(article["body"])
    warnings = article.get("warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
        raise SafeError("invalid_warnings")
    warnings = sorted(set(warnings + quality(body)))
    if any(w in warnings for w in ("insufficient_text", "image_dominant", "article_body_missing")):
        raise SafeError("insufficient_content")
    if "possibly_truncated" in warnings and payload.get("allow_partial") is not True:
        raise SafeError("partial_content_requires_acknowledgment")
    source = canonical_url(article.get("source", ""))
    body_hash = digest(body)
    identity = article_id(source, body_hash)
    if article.get("body_hash") != body_hash or article.get("article_id") != identity:
        raise SafeError("article_integrity_mismatch")
    summary = payload["summary"]
    for key in SECTIONS:
        if not isinstance(summary.get(key), str) or not summary[key].strip():
            raise SafeError("missing_summary_section")
    tags = summary.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 20 or not all(
            isinstance(tag, str) and re.fullmatch(r"[\w\-/]{1,50}", tag) for tag in tags):
        raise SafeError("invalid_tags")
    metadata = {key: clean_text(article.get(key, "")) for key in ("title", "author", "account", "published_at")}
    if any(len(value) > 1024 for value in metadata.values()):
        raise SafeError("metadata_too_long")
    now = datetime.now(timezone.utc)
    metadata.update(article_id=identity, source=source, body_hash=body_hash,
                    organized_at=now.isoformat(), tags=tags, skill_version=VERSION,
                    warnings=warnings)
    content = "---\n" + "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()) + "\n---\n\n"
    content += "# " + (metadata["title"].replace("\n", " ") or "未命名文章") + "\n\n"
    if "possibly_truncated" in warnings:
        content += "> 此笔记基于部分原文整理，未覆盖缺失内容。\n\n"
    if "images_not_read" in warnings:
        content += "> 图片未读取；本文总结仅覆盖已提取的文字。\n\n"
    if "table_layout_requires_review" in warnings:
        content += "> 表格已转换为文本，表格关系需回到原文核对。\n\n"
    for key, heading in zip(SECTIONS, HEADINGS):
        content += f"## {heading}\n\n{summary[key].strip()}\n\n"
    content += "## 来源\n\n" + (f"[原文]({source})" if source else "用户提供的正文或本地文件（未提供公开链接）") + "\n\n默认未进行外部事实核查。\n"
    return metadata, content, now.strftime("%Y-%m-%d")


def save(payload):
    action = payload.get("action", "save")
    if action == "show-config":
        return {"status": "success", "vault": str(read_config())}
    if action == "configure":
        vault = vault_path(payload["vault"])
        vault.mkdir(parents=True, exist_ok=True)
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps({"vault": str(vault)}, ensure_ascii=False) + "\n", replace=True)
        return {"status": "success", "vault": str(vault)}
    if action != "save":
        raise SafeError("unknown_action")
    metadata, content, date = validate_note(payload)
    vault = read_config()
    if not vault.is_dir():
        raise SafeError("vault_unavailable")
    try:
        with vault_lock(vault):
            identity = metadata["article_id"]
            # Search metadata as well as names so a user's renamed note still deduplicates.
            for path in sorted(vault.glob("*.md")):
                if path.is_symlink():
                    continue
                try:
                    previous = metadata_of(path)
                except SafeError:
                    if identity[:16] in path.name:
                        return {"status": "conflict", "error": "existing_note_metadata_changed", "path": str(path)}
                    continue
                if previous.get("article_id") == identity and previous.get("body_hash") == metadata["body_hash"] and not payload.get("force_new", False):
                    return {"status": "duplicate", "path": str(path)}
            title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", metadata["title"]).strip(" .")[:60] or "未命名文章"
            base = f"{date}--{title}--{identity[:16]}"
            path = vault / f"{base}.md"
            version = 1
            while path.exists() or path.is_symlink():
                version += 1
                path = vault / f"{base}--v{version}.md"
            if path.resolve().parent != vault:
                raise SafeError("path_outside_vault")
            atomic_write(path, content)
            return {"status": "success", "path": str(path), "version": version}
    except SafeError as exc:
        if str(exc) == "vault_busy":
            return {"status": "conflict", "error": "vault_busy"}
        raise


if __name__ == "__main__":
    sys.exit(run(save))
