"""Validate data exported by the host browser; no browser credentials or network."""
from common import MAX_BYTES, SafeError, canonical_url, clean_text, quality


def parse_capture(capture):
    if not isinstance(capture, dict) or capture.get("schema_version") != 1:
        raise SafeError("invalid_browser_capture")
    state = capture.get("state")
    if state != "ready":
        actions = {"verification_required": "complete_verification_in_browser",
                   "unavailable": "provide_other_authorized_source", "not_ready": "inspect_existing_browser_tab"}
        if state not in actions:
            raise SafeError("invalid_browser_state")
        return {"status": "needs_input" if state != "not_ready" else "failed",
                "error": "browser_" + state, "next_action": actions[state]}
    source = canonical_url(capture.get("source", ""))
    if not source:
        raise SafeError("browser_source_missing")
    raw = capture.get("body")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise SafeError("invalid_browser_body")
    evidence = capture.get("evidence", {})
    if (not isinstance(evidence, dict) or evidence.get("container") != "#js_content"
            or evidence.get("body_utf16_length") != len(raw.encode("utf-16-le")) // 2
            or not isinstance(evidence.get("end_marker_present"), bool)
            or type(evidence.get("table_count")) is not int or evidence["table_count"] < 0):
        raise SafeError("browser_capture_incomplete")
    body = clean_text(raw)
    headings = capture.get("headings", [])
    images = capture.get("images", [])
    if not isinstance(headings, list) or not isinstance(images, list) or len(images) > 1000:
        raise SafeError("invalid_browser_structure")
    for heading in headings:
        if (not isinstance(heading, dict) or type(heading.get("level")) is not int
                or not 1 <= heading["level"] <= 6 or not isinstance(heading.get("text"), str)
                or not heading["text"].strip() or clean_text(heading["text"]) not in body):
            raise SafeError("browser_heading_mismatch")
    for image in images:
        if (not isinstance(image, dict) or not isinstance(image.get("alt"), str)
                or not isinstance(image.get("loaded"), bool)):
            raise SafeError("invalid_browser_image")
    warnings = quality(body, len(images))
    if not evidence["end_marker_present"]:
        warnings.append("browser_end_unconfirmed")
    if evidence["table_count"]:
        warnings.append("table_layout_requires_review")
    if images:
        warnings.append("images_not_read")
        if any(not image["loaded"] for image in images):
            warnings.append("images_not_loaded")
    metadata = {key: clean_text(capture.get(key, "")) for key in ("title", "author", "account", "published_at")}
    return {"source": source, "body": body, "metadata": metadata, "warnings": warnings,
            "details": {"read_method": "browser", "headings": headings,
                        "images": [{"alt": image["alt"], "loaded": image["loaded"]} for image in images],
                        "browser_evidence": evidence}}
