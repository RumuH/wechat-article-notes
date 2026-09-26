import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import SafeError, canonical_url
from audit_release import scan
from extract import ArticleRedirects, extract, fetch
from save import atomic_write, config_path, save

FIXTURE = ROOT / "tests" / "fixtures" / "synthetic.html"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.original_env = os.environ.copy()
        self.env = patch.dict(os.environ, {"APPDATA": str(self.base / "config"), "XDG_CONFIG_HOME": str(self.base / "config")})
        self.env.start()
        self.vault = self.base / "vault"
        self.article = extract({"kind": "file", "path": str(FIXTURE)})["article"]
        self.summary = {"abstract": "虚构实验讨论记录问题的用途。", "claims": "作者认为记录问题可能有帮助（原文 P1）。",
                        "evidence": "12 人，持续两周，自我报告（原文 P2）。", "limitations": "无对照组，不能推广（原文 P2–P3）。",
                        "analysis": "智能体判断：适合作为个人尝试的思路，不能当作已验证结论。", "tags": ["阅读", "虚构实验"]}
        self.payload = {"action": "save", "article": self.article, "summary": self.summary}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def configure(self):
        return save({"action": "configure", "vault": str(self.vault)})

    def test_html_metadata_and_inert_content(self):
        self.assertEqual(self.article["title"], "虚构阅读实验")
        self.assertEqual(self.article["author"], "虚构作者")
        self.assertNotIn("must never execute", self.article["body"])
        self.assertNotIn("页面广告", self.article["body"])
        self.assertIn("上传", self.article["body"])
        self.assertEqual(list(self.base.iterdir()), [])

    def test_missing_body_and_verification(self):
        for html in ("<title>文章</title>", "<body>请完成安全验证</body>"):
            result = extract({"kind": "html", "text": html})
            self.assertEqual(result["status"], "needs_input")
            self.assertEqual(result["article"]["body"], "")

    def test_images_and_truncation(self):
        image = extract({"kind": "html", "text": '<article><img src="x">很短</article>'})
        self.assertEqual(image["status"], "needs_input")
        self.assertIn("image_dominant", image["warnings"])
        result = extract({"kind": "text", "text": self.article["body"] + "\n[truncated]"})
        self.assertIn("possibly_truncated", result["warnings"])
        self.configure()
        request = {**self.payload, "article": result["article"]}
        with self.assertRaisesRegex(SafeError, "partial_content"):
            save(request)
        path = Path(save({**request, "allow_partial": True})["path"])
        self.assertIn("基于部分原文", path.read_text(encoding="utf-8"))

    def test_long_plain_and_missing_metadata(self):
        result = extract({"kind": "text", "text": "长文内容。" * 15000})
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["article"]["body"]), 75000)
        self.assertEqual(result["article"]["author"], "")
        self.assertEqual(result["article"]["title"], "")

    def test_markdown_and_utf8_bom(self):
        path = self.base / "article.md"
        path.write_text("# 测试标题\n" + self.article["body"], encoding="utf-8-sig")
        result = extract({"kind": "file", "path": str(path)})
        self.assertEqual(result["article"]["title"], "测试标题")
        self.assertNotIn(str(path), json.dumps(result, ensure_ascii=False))

    def test_url_sanitization_and_identity(self):
        url = "https://mp.weixin.qq.com/s?__biz=synthetic&mid=123&idx=1&sn=example&key=PRIVATE&pass_ticket=PRIVATE&scene=1"
        clean = canonical_url(url)
        self.assertNotIn("PRIVATE", clean)
        self.assertNotIn("scene", clean)
        a = extract({"kind": "text", "text": self.article["body"], "source": clean})["article"]
        b = extract({"kind": "text", "text": self.article["body"], "source": clean.replace("sn=example", "sn=changed")})["article"]
        self.assertEqual(a["article_id"], b["article_id"])

    def test_invalid_url_and_redirect(self):
        for url in ("https://example.invalid/s/x", "file:///private", "https://mp.weixin.qq.com/login", "https://mp.weixin.qq.com/s", "https://user:password@mp.weixin.qq.com/s/x", "https://mp.weixin.qq.com:9443/s/x"):
            with self.assertRaises(SafeError):
                canonical_url(url)
        with self.assertRaises(SafeError):
            ArticleRedirects().redirect_request(None, None, 302, "", {}, "https://example.invalid/s/x")

    def test_network_failure_is_sanitized(self):
        with patch("extract.build_opener", side_effect=RuntimeError("PRIVATE")):
            # CLI catches all unexpected errors as a fixed category.
            with self.assertRaises(RuntimeError):
                fetch("https://mp.weixin.qq.com/s/synthetic")

    def test_network_success_type_and_size_limits(self):
        from email.message import Message
        from io import BytesIO
        response = BytesIO(FIXTURE.read_bytes())
        response.headers = Message()
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.geturl = lambda: "https://mp.weixin.qq.com/s/synthetic"
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with patch("extract.build_opener", return_value=opener):
            result = extract({"kind": "url", "url": "https://mp.weixin.qq.com/s/synthetic"})
        self.assertEqual(result["status"], "success")
        with patch("extract.MAX_BYTES", 20):
            with self.assertRaisesRegex(SafeError, "input_too_large"):
                extract({"kind": "file", "path": str(FIXTURE)})
        opener = unittest.mock.Mock()
        opener.open.side_effect = RuntimeError("PRIVATE")
        with patch("extract.build_opener", return_value=opener):
            with self.assertRaisesRegex(SafeError, "^fetch_failed_provide_content$"):
                fetch("https://mp.weixin.qq.com/s/synthetic")

    def test_vault_configuration_boundaries(self):
        for path in (ROOT / "notes", ROOT / ".." / ROOT.name / "notes", ROOT.parent):
            with self.assertRaises(SafeError):
                save({"action": "configure", "vault": str(path)})
        with self.assertRaises(SafeError):
            save({"action": "configure", "vault": "relative"})
        self.configure()
        self.assertEqual(save({"action": "show-config"})["vault"], str(self.vault))

    def test_action_is_required_even_with_configured_vault(self):
        request = {key: value for key, value in self.payload.items() if key != "action"}
        for configured in (False, True):
            if configured:
                self.configure()
            with self.assertRaisesRegex(SafeError, "^action_required$"):
                save(request)
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_export_without_vault_or_configuration(self):
        path = self.base / "exports" / "阅读笔记.md"
        result = save({**self.payload, "action": "export", "path": str(path)})
        self.assertEqual(result, {"status": "success", "path": str(path), "mode": "export"})
        text = path.read_text(encoding="utf-8")
        self.assertIn("## 摘要", text)
        self.assertIn("## 来源", text)
        self.assertFalse(config_path().exists())
        self.assertFalse(self.vault.exists())
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_export_leaves_configured_vault_untouched(self):
        self.configure()
        note = Path(save(self.payload)["path"])
        before_note = note.read_bytes()
        before_config = config_path().read_bytes()
        for name in ("first.md", "second.md"):
            with patch("save.read_config", side_effect=AssertionError("export must not read configuration")):
                result = save({**self.payload, "action": "export", "path": str(self.base / name)})
            self.assertEqual(result["status"], "success")
        self.assertEqual(config_path().read_bytes(), before_config)
        self.assertEqual(note.read_bytes(), before_note)
        self.assertEqual(list(self.vault.iterdir()), [note])

    def test_export_conflict_and_validation(self):
        path = self.base / "existing.md"
        path.write_text("private edits", encoding="utf-8")
        request = {**self.payload, "action": "export", "path": str(path)}
        result = save(request)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["error"], "export_file_exists")
        self.assertEqual(path.read_text(encoding="utf-8"), "private edits")
        for value, error in (("relative.md", "export_path_must_be_absolute"),
                             (str(self.base / "note.txt"), "export_path_must_be_markdown"),
                             (str(ROOT / "note.md"), "private_path_inside_skill")):
            with self.assertRaisesRegex(SafeError, error):
                save({**request, "path": value})
        broken = copy.deepcopy(request)
        broken["path"] = str(self.base / "invalid" / "note.md")
        broken["article"]["body"] += "changed"
        with self.assertRaisesRegex(SafeError, "integrity"):
            save(broken)
        self.assertFalse((self.base / "invalid").exists())

    def test_export_atomic_collision_and_symlink(self):
        path = self.base / "note.md"
        request = {**self.payload, "action": "export", "path": str(path)}
        with patch("save.os.link", side_effect=FileExistsError):
            self.assertEqual(save(request)["error"], "export_file_exists")
        self.assertEqual(list(self.base.iterdir()), [])
        target = self.base / "target.md"
        target.write_text("private", encoding="utf-8")
        try:
            path.symlink_to(target)
        except OSError:
            self.skipTest("OS does not permit symlinks")
        with self.assertRaisesRegex(SafeError, "symlink_target"):
            save(request)
        self.assertEqual(target.read_text(encoding="utf-8"), "private")

    def test_yaml_dedup_and_private_edits(self):
        self.configure()
        result = save(self.payload)
        path = Path(result["path"])
        text = path.read_text(encoding="utf-8")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(metadata["article_id"], self.article["article_id"])
        self.assertEqual(metadata["tags"], ["阅读", "虚构实验"])
        self.assertNotIn(self.article["body"], text)
        self.assertNotIn(str(FIXTURE), text)
        path.write_text(text + "\n私人备注\n", encoding="utf-8")
        duplicate = save(self.payload)
        self.assertEqual(duplicate["status"], "duplicate")
        self.assertIn("私人备注", path.read_text(encoding="utf-8"))
        newer = save({**self.payload, "force_new": True})
        self.assertNotEqual(newer["path"], str(path))
        self.assertEqual(newer["version"], 2)

    def test_changed_body_and_renamed_note(self):
        self.configure()
        article = extract({"kind": "text", "text": self.article["body"], "source": "https://mp.weixin.qq.com/s/synthetic"})["article"]
        first = Path(save({**self.payload, "article": article})["path"])
        moved = first.with_name("renamed.md")
        first.rename(moved)
        self.assertEqual(save({**self.payload, "article": article})["status"], "duplicate")
        changed = extract({"kind": "text", "text": article["body"] + "追加文字", "source": article["source"]})["article"]
        self.assertEqual(save({**self.payload, "article": changed})["status"], "success")
        self.assertTrue(moved.exists())

    def test_metadata_conflict_and_lock(self):
        self.configure()
        path = Path(save(self.payload)["path"])
        path.write_text("private edits without metadata", encoding="utf-8")
        self.assertEqual(save(self.payload)["status"], "conflict")
        lock = self.vault / ".wechat-article-notes.lock"
        lock.touch()
        self.assertEqual(save(self.payload)["error"], "vault_busy")
        lock.unlink()

    def test_path_traversal_title(self):
        self.configure()
        article = {**self.article, "title": '../..\\outside:question?*\nnext'}
        path = Path(save({**self.payload, "article": article})["path"])
        self.assertEqual(path.parent, self.vault)

    def test_validation_and_atomic_failure(self):
        self.configure()
        broken = copy.deepcopy(self.payload)
        broken["article"]["body"] += "changed"
        with self.assertRaisesRegex(SafeError, "integrity"):
            save(broken)
        with self.assertRaises(SafeError):
            save({**self.payload, "summary": {}})
        with self.assertRaisesRegex(SafeError, "invalid_boolean"):
            save({**self.payload, "force_new": "false"})
        with patch("save.os.link", side_effect=OSError("PRIVATE")):
            with self.assertRaises(OSError):
                save(self.payload)
        self.assertEqual(list(self.vault.iterdir()), [])
        path = self.vault / "existing.md"
        path.write_text("private", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            atomic_write(path, "replacement")
        self.assertEqual(path.read_text(encoding="utf-8"), "private")

    def test_symlink_vault_boundary(self):
        link = self.base / "alias"
        try:
            link.symlink_to(ROOT, target_is_directory=True)
        except OSError:
            self.skipTest("OS does not permit symlinks")
        with self.assertRaises(SafeError):
            save({"action": "configure", "vault": str(link)})

    def test_cli_batch_failure_isolation_and_safe_errors(self):
        requests = [{"kind": "file", "path": str(self.base / "PRIVATE.txt")}, {"kind": "file", "path": str(FIXTURE)}]
        results = []
        for request in requests:
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "extract.py")], input=json.dumps(request).encode(), capture_output=True, env=self.original_env)
            self.assertEqual(proc.stderr, b"")
            self.assertNotIn(b"PRIVATE", proc.stdout)
            results.append(json.loads(proc.stdout))
        self.assertEqual([r["status"] for r in results], ["failed", "success"])

    def test_save_cli_and_missing_configuration(self):
        def command(payload):
            return subprocess.run([sys.executable, str(ROOT / "scripts" / "save.py")],
                                  input=json.dumps(payload).encode(), capture_output=True)
        missing = command({"action": "show-config"})
        self.assertEqual(json.loads(missing.stdout)["error"], "vault_not_configured")
        configured = command({"action": "configure", "vault": str(self.vault)})
        self.assertEqual(configured.returncode, 0)
        saved = command(self.payload)
        self.assertEqual(saved.returncode, 0)
        self.assertEqual(saved.stderr, b"")
        self.assertTrue(Path(json.loads(saved.stdout)["path"]).is_file())

    def test_export_cli_and_missing_action(self):
        request = {**self.payload, "action": "export", "path": str(self.base / "note.md")}
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "save.py")],
                              input=json.dumps(request).encode(), capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, b"")
        self.assertEqual(json.loads(proc.stdout)["mode"], "export")
        self.assertFalse(config_path().exists())
        del request["action"]
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "save.py")],
                              input=json.dumps(request).encode(), capture_output=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(json.loads(proc.stdout)["error"], "action_required")

    def test_release_scanner_detects_without_logging_data(self):
        synthetic = b"ghp_" + b"x" * 36
        self.assertIn("github_token", scan(synthetic))
        self.assertIn("private_key", scan(b"-----BEGIN " + b"PRIVATE KEY-----"))
        self.assertIn("windows_user_path", scan(b"C:" + bytes([92]) + b"Users" + bytes([92]) + b"synthetic"))
        self.assertEqual(scan(b"Synthetic documentation with no credentials."), [])


if __name__ == "__main__":
    unittest.main()
