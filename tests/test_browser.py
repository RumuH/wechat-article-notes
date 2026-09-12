"""Synthetic browser handoff tests; no real reading history in fixtures."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import SafeError
from extract import extract
from save import validate_note


class BrowserCaptureTests(unittest.TestCase):
    def setUp(self):
        body = "一、合成实验\n" + "这是虚构测试正文，讨论阅读习惯与研究限制。" * 8 + "\n二、结论\n样本有限，无法推广。🙂"
        self.request = {"kind": "browser", "capture": {
            "schema_version": 1, "state": "ready", "source": "https://mp.weixin.qq.com/s/SYNTHETIC_EXAMPLE",
            "title": "合成文章", "author": "虚构作者", "account": "虚构公众号", "published_at": "2026-01-01",
            "body": body, "headings": [{"level": 2, "text": "一、合成实验"}, {"level": 2, "text": "二、结论"}],
            "images": [{"alt": "合成图示", "loaded": False}],
            "evidence": {"container": "#js_content", "body_utf16_length": len(body.encode("utf-16-le")) // 2,
                         "end_marker_present": True, "table_count": 0}}}

    def test_url_failure_routes_to_browser(self):
        with patch("extract.fetch", side_effect=SafeError("redirect_blocked_provide_content")):
            result = extract({"kind": "url", "url": self.request["capture"]["source"]})
        self.assertEqual(result["next_action"], "read_browser")
        with patch("extract.fetch", return_value=("<body>验证</body>", self.request["capture"]["source"])):
            self.assertEqual(extract({"kind": "url", "url": self.request["capture"]["source"]})["next_action"], "read_browser")

    def test_full_browser_handoff_and_note_validation(self):
        result = extract(self.request)
        self.assertEqual(result["status"], "success")
        article = result["article"]
        self.assertEqual(article["read_method"], "browser")
        self.assertEqual(article["title"], "合成文章")
        self.assertIn("🙂", article["body"])
        self.assertEqual(len(article["headings"]), 2)
        self.assertIn("images_not_loaded", article["warnings"])
        self.assertIn("images_not_read", article["warnings"])
        metadata, content, _ = validate_note({"article": article, "summary": {
            "abstract": "虚构阅读实验。", "claims": "作者建议记录问题。", "evidence": "原文未给出量化依据。",
            "limitations": "样本有限。", "analysis": "智能体分析：需要更多验证。", "tags": ["测试"]}})
        self.assertEqual(metadata["source"], article["source"])
        self.assertIn("图片未读取", content)

    def test_transport_truncation_and_invented_headings_rejected(self):
        broken = copy.deepcopy(self.request)
        broken["capture"]["body"] = broken["capture"]["body"][:40]
        with self.assertRaisesRegex(SafeError, "browser_capture_incomplete"):
            extract(broken)
        broken = copy.deepcopy(self.request)
        broken["capture"]["headings"][0]["text"] = "没有读取到的章节"
        with self.assertRaisesRegex(SafeError, "browser_heading_mismatch"):
            extract(broken)

    def test_verification_only_when_observed_in_browser(self):
        for state, action in (("verification_required", "complete_verification_in_browser"),
                              ("not_ready", "inspect_existing_browser_tab"),
                              ("unavailable", "provide_other_authorized_source")):
            result = extract({"kind": "browser", "capture": {"schema_version": 1, "state": state}})
            self.assertEqual(result["next_action"], action)
            self.assertNotIn("article", result)

    def test_mismatched_source_and_evidence(self):
        for key, value in (("source", "https://example.invalid/article"), ("schema_version", 2), ("evidence", {})):
            broken = copy.deepcopy(self.request)
            broken["capture"][key] = value
            with self.assertRaises(SafeError):
                extract(broken)

    def test_missing_end_marker_and_tables(self):
        self.request["capture"]["evidence"].update(end_marker_present=False, table_count=1)
        result = extract(self.request)
        self.assertIn("browser_end_unconfirmed", result["warnings"])
        self.assertIn("table_layout_requires_review", result["warnings"])

    def test_loaded_images_still_require_visual_reading(self):
        self.request["capture"]["images"][0]["loaded"] = True
        result = extract(self.request)
        self.assertNotIn("images_not_loaded", result["warnings"])
        self.assertIn("images_not_read", result["warnings"])

    def test_browser_capture_cli_round_trip(self):
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract.py")],
                              input=json.dumps(self.request).encode("utf-8"), capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, b"")
        result = json.loads(proc.stdout)
        self.assertEqual(result["article"]["headings"], self.request["capture"]["headings"])
        self.assertTrue(result["article"]["body"].endswith("无法推广。🙂"))


if __name__ == "__main__":
    unittest.main()
