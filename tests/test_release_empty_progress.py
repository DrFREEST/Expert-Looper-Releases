import datetime
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("empty_progress", ROOT / "scripts/release_discord.py")
notice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notice)


class EmptyProgressChecks(unittest.TestCase):
    def test_empty_items_are_valid_but_id_dates_and_list_remain_checked(self):
        data = {"id": "20261015-progress-01", "reviewed_on": "2026-10-15", "valid_until": "2026-10-29", "items": []}
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "notice.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(notice.progress_notice(path, datetime.date(2026, 10, 15)), data)
            for field, value in (("items", {}), ("items", [None] * 4), ("id", "bad"),
                                 ("valid_until", "2026-10-30"), ("reviewed_on", "2026-10-16")):
                changed = dict(data, **{field: value})
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    notice.progress_notice(path, datetime.date(2026, 10, 15))

    def test_standalone_empty_stops_before_external_read_claim_or_send(self):
        with patch.object(notice, "progress_notice", return_value={"id": "20261015-progress-01", "items": []}), \
             patch.object(notice, "get_file") as get, patch.object(notice, "save_state") as save, \
             patch.object(notice, "send") as send, patch.object(notice, "render_progress") as render:
            with self.assertRaisesRegex(ValueError, "진행 안내 항목이 없어"):
                notice.announce_progress()
            for call in (get, save, send, render):
                call.assert_not_called()

    def test_release_without_progress_keeps_release_images_and_omits_future_claim(self):
        for kind in ("fix", "improvement"):
            with self.subTest(kind=kind):
                self.check_release(kind, False)

    def test_release_with_progress_keeps_reviewed_image_and_sentence(self):
        self.check_release("improvement", True)

    def check_release(self, kind, has_progress):
        release = {"id": 999, "tag_name": "v0.11.11", "body": "<!-- expert-looper-release: " + kind + " -->\n설정을 보호합니다.",
                   "draft": False, "html_url": "https://example.invalid/release"}
        progress = {"id": "20261015-progress-01", "items": [{"status": "진행 중", "title": "확인된 항목", "summary": "준비 중입니다."}] if has_progress else []}
        with patch.dict(notice.os.environ, {"NOTICE_KIND": "release", "RELEASE_TAG": "v0.11.11",
                                           "DISCORD_CHANGELOG_WEBHOOK": "mock-change", "DISCORD_DOWNLOAD_WEBHOOK": "mock-download"}), \
             patch.object(notice, "wait_release_feed", return_value=release), \
             patch.object(notice, "github", return_value=[release]), \
             patch.object(notice, "get_file", return_value=None), \
             patch.object(notice.pathlib.Path, "read_text", return_value=""), \
             patch.object(notice, "progress_notice", return_value=progress), \
             patch.object(notice, "render_progress", return_value=pathlib.Path("progress.png")) as render, \
             patch.object(notice, "render_image_notes", return_value=[pathlib.Path("release.png")]) as summary, \
             patch.object(notice, "save_state", return_value={"sha": "mock"}), \
             patch.object(notice, "send", return_value="123") as send:
            notice.main()
        self.assertEqual(send.call_count, 2)
        change = send.call_args_list[0].args
        expected = ([] if kind == "fix" else [pathlib.Path("release.png")]) + ([pathlib.Path("progress.png")] if has_progress else [])
        self.assertEqual(change[2], expected)
        self.assertEqual("함께 첨부한 개발 진행 이미지" in change[1], has_progress)
        self.assertEqual(render.call_count, int(has_progress))
        self.assertEqual(summary.call_count, int(kind != "fix"))
        self.assertIn("설정을 보호합니다.", change[1])
        self.assertIn("도움말 → 업데이트 확인", change[1])
        self.assertLess(len(change[1]), 2000)
        self.assertEqual(send.call_args_list[1].args[2], [])


if __name__ == "__main__":
    unittest.main()
