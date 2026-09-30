import base64
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location("announce",pathlib.Path(__file__).parents[1]/"scripts/release_discord.py")
announce=importlib.util.module_from_spec(spec);spec.loader.exec_module(announce)


class Checks(unittest.TestCase):
    def test_kind(self):
        self.assertEqual(announce.classify({"tag_name":"v0.12.0","body":"새 기능"},"0.11.1"),"feature")
        self.assertEqual(announce.classify({"tag_name":"v0.11.2","body":"버그 수정"},"0.11.1"),"fix")
        self.assertEqual(announce.classify({"tag_name":"v0.11.2","body":"인식 속도 개선"},"0.11.1"),"improvement")
        self.assertEqual(announce.classify({"tag_name":"v0.12.0","body":"<!-- expert-looper-release: fix -->"},"0.11.1"),"fix")
    def test_cumulative_includes_intermediate_fixes(self):
        notes={"0.8.20":"old","0.8.21":"fix","0.9.0":"feature","0.9.1":"future"}
        self.assertEqual([v for v,_ in announce.cumulative(notes,"0.8.20","0.9.0")],["0.8.21","0.9.0"])
    def run_mock(self,fail_changelog=False):
        states={};sent=[]
        release={"id":1,"tag_name":"v0.11.2","body":"- 버그 수정","draft":False,"html_url":"https://github.com/release"}
        def gh(path,*args): return release if path.startswith("/releases/tags") else [release,{**release,"id":0,"tag_name":"v0.11.1"}]
        def get(path):return {"content":base64.b64encode(json.dumps(states[path]).encode()).decode()} if path in states else None
        def save(path,data,old=None):states[path]=data;return {"sha":"fake"}
        def send(url,text,images):
            if url=="changelog" and fail_changelog:raise TimeoutError()
            sent.append((url,text,images));return "123"
        with patch.dict(os.environ,{"RELEASE_TAG":"v0.11.2","DISCORD_CHANGELOG_WEBHOOK":"changelog","DISCORD_DOWNLOAD_WEBHOOK":"download"}),patch.object(announce,"github",side_effect=gh),patch.object(announce,"get_file",side_effect=get),patch.object(announce,"save_state",side_effect=save),patch.object(announce,"send",side_effect=send):
            if fail_changelog:
                with self.assertRaises(RuntimeError):announce.main()
                with self.assertRaises(RuntimeError):announce.main()
            else:announce.main();announce.main()
        return states,sent
    def test_two_channels_no_duplicate(self):
        states,sent=self.run_mock();self.assertEqual(len(sent),2)
        self.assertNotIn("releases/download",sent[0][1]);self.assertIn("v0.11.2/ExpLooper.exe",sent[1][1])
        self.assertNotIn(".release-notifications/image-anchor.json",states)
    def test_uncertain_send_not_retried_other_channel_still_sent(self):
        states,sent=self.run_mock(True);self.assertEqual(len(sent),1);self.assertEqual(sent[0][0],"download")
        self.assertEqual(states[".release-notifications/1-changelog.json"]["status"],"pending")


if __name__=="__main__":unittest.main()
