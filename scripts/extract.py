"""Extract inert article data from a public WeChat URL, local file, or text."""
import re
import sys
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from bs4 import BeautifulSoup

from common import MAX_BYTES, SafeError, article_id, canonical_url, clean_text, digest, quality, run


class ArticleRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Revalidate every hop; never follow links to other hosts or login endpoints.
        try:
            target = canonical_url(newurl)
        except SafeError:
            raise SafeError("redirect_blocked_provide_content") from None
        return super().redirect_request(req, fp, code, msg, headers, target)


def fetch(url):
    opener = build_opener(ProxyHandler({}), ArticleRedirects())
    request = Request(url, headers={"User-Agent": "wechat-article-notes/0.1"})
    try:
        with opener.open(request, timeout=20) as response:
            canonical = canonical_url(response.geturl())
            if response.headers.get_content_type() not in ("text/html", "application/xhtml+xml"):
                raise SafeError("unsupported_content_type")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SafeError("input_too_large")
            return raw.decode(response.headers.get_content_charset() or "utf-8"), canonical
    except SafeError:
        raise
    except Exception:
        raise SafeError("fetch_failed_provide_content") from None


def parse_html(raw):
    soup = BeautifulSoup(raw, "html.parser")
    for element in soup(["script", "style", "noscript", "iframe", "form", "template"]):
        element.decompose()

    def text_at(selector):
        node = soup.select_one(selector)
        return clean_text(node.get_text(" ", strip=True)) if node else ""

    def meta(key):
        node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        return node.get("content", "").strip() if node else ""

    metadata = {
        "title": text_at("#activity-name") or meta("og:title") or text_at("h1") or text_at("title"),
        "author": meta("author") or text_at("#js_author_name"),
        "account": text_at("#js_name"),
        "published_at": text_at("#publish_time") or meta("article:published_time"),
    }
    container = soup.select_one("#js_content")
    if container is None:
        container = soup.select_one("article")
    if container is None:
        return "", metadata, ["article_body_missing"]
    for node in container.select("nav, footer, aside, [hidden], [aria-hidden='true']"):
        node.decompose()
    images = len(container.find_all("img"))
    body = clean_text(container.get_text("\n", strip=True))
    warnings = quality(body, images)
    if container.find("table"):
        warnings.append("table_layout_requires_review")
    if images:
        warnings.append("images_not_read")
    return body, metadata, warnings


def extract(payload):
    kind = payload.get("kind")
    source = canonical_url(payload.get("source", ""))
    metadata = {key: "" for key in ("title", "author", "account", "published_at")}
    if kind == "url":
        source = canonical_url(payload["url"])
        raw, source = fetch(source)
        body, metadata, warnings = parse_html(raw)
    elif kind == "file":
        path = Path(payload["path"]).expanduser().resolve()
        if path.suffix.lower() not in (".html", ".htm", ".md", ".txt"):
            raise SafeError("unsupported_file_type")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise SafeError("input_too_large")
        raw = raw.decode("utf-8-sig")
        if path.suffix.lower() in (".html", ".htm"):
            body, metadata, warnings = parse_html(raw)
        else:
            body = clean_text(raw)
            warnings = quality(body)
    elif kind in ("text", "html"):
        raw = payload["text"]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
            raise SafeError("input_too_large")
        if kind == "html":
            body, metadata, warnings = parse_html(raw)
        else:
            body = clean_text(raw)
            warnings = quality(body)
    else:
        raise SafeError("unsupported_input_kind")
    for key in metadata:
        if key in payload:
            metadata[key] = clean_text(payload[key])
    if not metadata["title"]:
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        metadata["title"] = heading.group(1) if heading else ""
    body_hash = digest(body)
    blocked = any(w in warnings for w in ("insufficient_text", "image_dominant", "article_body_missing"))
    return {
        "status": "needs_input" if blocked else "success",
        "warnings": warnings,
        "article": {**metadata, "source": source, "body": body, "body_hash": body_hash,
                    "article_id": article_id(source, body_hash), "warnings": warnings},
    }


if __name__ == "__main__":
    sys.exit(run(extract))
