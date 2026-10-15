import importlib.util
import pathlib
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("release_copy", ROOT / "scripts/release_discord.py")
notice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notice)


class SimpleReleaseCopyChecks(unittest.TestCase):
    def test_progress_notice_explains_preparation_without_claiming_release(self):
        with patch.object(notice, "progress_notice", return_value={"id": "review-20261001", "items": [{}]}), \
             patch.object(notice, "get_file", return_value=None), \
             patch.object(notice, "render_progress", return_value=pathlib.Path("reviewed.png")), \
             patch.object(notice, "save_state", return_value={"sha": "fake"}), \
             patch.dict(notice.os.environ, {"DISCORD_CHANGELOG_WEBHOOK": "mock"}), \
             patch.object(notice, "send", return_value="123") as send:
            notice.announce_progress()
        self.assertIn("지금은 준비 중이라 아직 사용할 수 없습니다.", send.call_args.args[1])
        self.assertNotIn("검증 후 확정", send.call_args.args[1])

    def test_every_release_kind_keeps_reviewed_details_in_message(self):
        body = "<!-- expert-looper-release: improvement -->\n선택한 작업의 설정만 바뀝니다. 다른 작업의 설정은 그대로 남습니다."
        for kind in ("fix", "feature", "improvement"):
            with self.subTest(kind=kind):
                text = notice.release_notice({"body": body}, "0.12.0", kind, "0.11.0")
                self.assertIn("바뀐 점과 사용 방법", text)
                self.assertIn("다른 작업의 설정은 그대로 남습니다.", text)
                self.assertIn("새 버전으로 바꾸는 방법", text)
                self.assertIn("도움말 → 업데이트 확인", text)
                self.assertNotIn("바뀐 내용과 사용 순서를 이 글에서 함께 확인", text)
                self.assertNotIn("어떤 점이 편해지나요?", text)
                self.assertNotIn("expert-looper-release", text)
                self.assertIn("아직 사용할 수 없습니다", text)

    def test_download_has_ordered_steps_and_explains_data(self):
        text = notice.download_notice("v0.12.0", "0.12.0")
        self.assertIn("1.", text)
        self.assertIn("2.", text)
        self.assertIn("Data 폴더에는 저장한 작업과 설정이 들어 있습니다.", text)
        self.assertIn("삭제하지 마세요", text)
        self.assertIn("/v0.12.0/ExpLooper.exe", text)

    def test_unreviewed_or_clipped_details_still_rejected(self):
        for body in ("게임 기능입니다.", "설정이 바뀝니다...", "가" * 1501):
            with self.subTest(body=body[:12]), self.assertRaises(ValueError):
                notice.release_notice({"body": body}, "0.12.0", "feature", "0.11.0")

    def test_message_limit_includes_headings_and_links_without_clipping(self):
        body = "설정은 그대로 유지됩니다. " * 100
        self.assertLessEqual(len(body), 1500)
        with self.assertRaisesRegex(ValueError, "do not clip"):
            notice.release_notice({"body": body}, "0.12.0", "feature", "0." + "1" * 200 + ".0")

    def test_prompt_requires_simple_factual_copy_and_message_details(self):
        text = (ROOT / "docs/채널 안내 이미지 공통 프롬프트.md").read_text(encoding="utf-8-sig")
        for required in ("초등학생", "무엇이 바뀌었나요?", "어떻게 사용하나요?", "어떤 점이 편해지나요?",
                         "이미지에는 핵심", "Discord 글에는", "전문 용어", "확인되지 않은"):
            self.assertIn(required, text)
        for required in ("릴리스 메시지 작성 틀", "검은 화면", "찾은 부분", "효과", "사용 예"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
