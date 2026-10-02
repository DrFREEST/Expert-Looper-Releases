import base64
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
import datetime
import hashlib
import copy
import io
from PIL import Image
from unittest.mock import patch
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

spec=importlib.util.spec_from_file_location("announce",pathlib.Path(__file__).parents[1]/"scripts/release_discord.py")
announce=importlib.util.module_from_spec(spec);spec.loader.exec_module(announce)

def release_fixture():
    return {"id":1,"tag_name":"v0.11.2","body":"- 버그 수정","draft":False,"published_at":"2026-10-01T00:00:00Z",
            "html_url":"https://github.com/release", "assets":[
                {"name":name,"size":123,"state":"uploaded","browser_download_url":f"https://github.com/{announce.REPO}/releases/download/v0.11.2/{name}"}
                for name in ('ExpLooper.exe','update.json')]}

TEST_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PUBLIC_KEY = TEST_SIGNING_KEY.public_key().public_bytes(serialization.Encoding.PEM,
                                                           serialization.PublicFormat.SubjectPublicKeyInfo)

def feed_fixture(version='0.11.2'):
    payload={'Version':version,'Size':123,'Sha256':'a'*64,'Url':f'https://github.com/{announce.REPO}/releases/download/v{version}/ExpLooper.exe'}
    encoded=json.dumps(payload).encode()
    signature=TEST_SIGNING_KEY.sign(encoded,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())
    envelope={'Payload':base64.b64encode(encoded).decode(),'Signature':base64.b64encode(signature).decode()}
    return {'content':base64.b64encode(json.dumps(envelope).encode()).decode()}


class Checks(unittest.TestCase):
    def setUp(self):
        self.key_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.key_folder.cleanup)
        key_path = pathlib.Path(self.key_folder.name) / 'public.pem'
        key_path.write_bytes(TEST_PUBLIC_KEY)
        self.key_patch = patch.object(announce, 'UPDATE_PUBLIC_KEY', key_path)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    def test_manifest_tamper_missing_signature_and_wrong_key_block_all_side_effects(self):
        valid = json.loads(base64.b64decode(feed_fixture()['content']))
        cases = []
        changed = copy.deepcopy(valid)
        data = json.loads(base64.b64decode(changed['Payload']))
        data['Sha256'] = 'b' * 64
        changed['Payload'] = base64.b64encode(json.dumps(data).encode()).decode()
        cases.append(changed)
        for value in ('', 'not-base64!', base64.b64encode(b'forged').decode()):
            changed = copy.deepcopy(valid); changed['Signature'] = value; cases.append(changed)
        changed = copy.deepcopy(valid); del changed['Signature']; cases.append(changed)
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        changed = copy.deepcopy(valid)
        changed['Signature'] = base64.b64encode(other.sign(base64.b64decode(valid['Payload']),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())).decode()
        cases.append(changed)
        for envelope in cases:
            feed = {'content':base64.b64encode(json.dumps(envelope).encode()).decode()}
            with self.subTest(envelope=envelope), patch.dict(os.environ, {'NOTICE_KIND':'release','RELEASE_TAG':'v0.11.2'}), \
                 patch.object(announce,'github',return_value=release_fixture()), \
                 patch.object(announce,'get_file',return_value=feed), patch.object(announce,'send') as send, \
                 patch.object(announce,'save_state') as save, patch.object(announce.time,'sleep') as sleep:
                with self.assertRaises(ValueError): announce.main()
                send.assert_not_called(); save.assert_not_called(); sleep.assert_not_called()

    def test_kind(self):
        self.assertEqual(announce.classify({"tag_name":"v0.12.0","body":"새 기능"},"0.11.1"),"feature")
        self.assertEqual(announce.classify({"tag_name":"v0.11.2","body":"버그 수정"},"0.11.1"),"fix")
        self.assertEqual(announce.classify({"tag_name":"v0.11.2","body":"인식 속도 개선"},"0.11.1"),"improvement")
        self.assertEqual(announce.classify({"tag_name":"v0.12.0","body":"<!-- expert-looper-release: fix -->"},"0.11.1"),"fix")
    def test_cumulative_includes_intermediate_fixes(self):
        notes={"0.8.20":"old","0.8.21":"fix","0.9.0":"feature","0.9.1":"future"}
        self.assertEqual([v for v,_ in announce.cumulative(notes,"0.8.20","0.9.0")],["0.8.21","0.9.0"])
    def run_mock(self,fail_changelog=False,missing_images=False):
        states={};sent=[]
        release=release_fixture()
        if missing_images: release['body']='인식 속도 개선'
        def gh(path,*args): return release if path.startswith("/releases/tags") else [release,{**release,"id":0,"tag_name":"v0.11.1"}]
        def get(path):return feed_fixture() if path=='update.json' else ({"content":base64.b64encode(json.dumps(states[path]).encode()).decode()} if path in states else None)
        def save(path,data,old=None):states[path]=data;return {"sha":"fake"}
        def send(url,text,images):
            if url=="changelog" and fail_changelog:raise TimeoutError()
            sent.append((url,text,images));return "123"
        with patch.dict(os.environ,{"NOTICE_KIND":"release","RELEASE_TAG":"v0.11.2","DISCORD_CHANGELOG_WEBHOOK":"changelog","DISCORD_DOWNLOAD_WEBHOOK":"download"}),patch.object(announce,"github",side_effect=gh),patch.object(announce,"get_file",side_effect=get),patch.object(announce,"save_state",side_effect=save),patch.object(announce,"send",side_effect=send),patch.object(announce,"progress_notice",return_value={}),patch.object(announce,"render_progress",return_value=pathlib.Path("progress.png")):
            if missing_images:
                with patch.object(announce,'render_image_notes',side_effect=FileNotFoundError('AI assets absent')):
                    with self.assertRaises(RuntimeError):announce.main()
                    with self.assertRaises(RuntimeError):announce.main()
            elif fail_changelog:
                with self.assertRaises(RuntimeError):announce.main()
                with self.assertRaises(RuntimeError):announce.main()
            else:announce.main();announce.main()
        return states,sent
    def test_two_channels_no_duplicate(self):
        states,sent=self.run_mock();self.assertEqual(len(sent),2)
        self.assertNotIn("releases/download",sent[0][1]);self.assertIn("v0.11.2/ExpLooper.exe",sent[1][1])
        self.assertNotIn(".release-notifications/image-anchor.json",states)
        self.assertEqual(sent[0][2],[pathlib.Path("progress.png")])
        self.assertEqual(sent[1][2],[])
    def test_uncertain_send_not_retried_other_channel_still_sent(self):
        states,sent=self.run_mock(True);self.assertEqual(len(sent),1);self.assertEqual(sent[0][0],"download")
        self.assertEqual(states[".release-notifications/1-changelog.json"]["status"],"pending")

    def test_missing_ai_assets_do_not_block_download(self):
        states,sent=self.run_mock(missing_images=True)
        self.assertEqual([row[0] for row in sent],['download'])
        self.assertNotIn('.release-notifications/1-changelog.json',states)
        self.assertEqual(states['.release-notifications/1-download.json']['status'],'sent')

    def test_progress_validation(self):
        data={"id":"review-20261001","reviewed_on":"2026-10-01","valid_until":"2026-10-07",
              "items":[{"status":"진행 중","title":"집계 개선","summary":"검증 중입니다."}]}
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/"notice.json"
            path.write_text(json.dumps(data),encoding="utf-8")
            self.assertEqual(announce.progress_notice(path,datetime.date(2026,10,1)),data)
            for day in (datetime.date(2026,9,30),datetime.date(2026,10,8)):
                with self.assertRaises(ValueError):announce.progress_notice(path,day)
            data["items"][0]["status"]="배포 완료"
            path.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ValueError):announce.progress_notice(path,datetime.date(2026,10,1))

    def test_progress_only_once_and_pending_not_retried(self):
        for fail in (False,True):
            states={};sends=[]
            def get(path):return {"content":base64.b64encode(json.dumps(states[path]).encode()).decode()} if path in states else None
            def save(path,data,old=None):states[path]=data;return {"sha":"fake"}
            def send(url,text,files):
                sends.append((url,text,files))
                if fail:raise TimeoutError()
                return "321"
            with patch.dict(os.environ,{"NOTICE_KIND":"progress","DISCORD_CHANGELOG_WEBHOOK":"changelog"}),patch.object(announce,"github",side_effect=AssertionError("No release or download request")),patch.object(announce,"progress_notice",return_value={"id":"review-20261001"}),patch.object(announce,"render_progress",return_value=pathlib.Path("progress.png")),patch.object(announce,"get_file",side_effect=get),patch.object(announce,"save_state",side_effect=save),patch.object(announce,"send",side_effect=send):
                if fail:
                    with self.assertRaises(TimeoutError):announce.main()
                    with self.assertRaises(ValueError):announce.main()
                else:announce.main();announce.main()
            self.assertEqual(len(sends),1)
            self.assertEqual(sends[0][0],"changelog")
            self.assertEqual(sends[0][2],[pathlib.Path("progress.png")])
            self.assertIn("아직 배포되지",sends[0][1])

    def test_feed_lag_retries_reads_then_allows(self):
        with patch.object(announce,'github',return_value=release_fixture()),patch.object(announce,'get_file',side_effect=[None,feed_fixture('0.11.1'),feed_fixture()]),patch.object(announce.time,'sleep') as sleep:
            self.assertEqual(announce.wait_release_feed('v0.11.2')['id'],1)
            self.assertEqual(sleep.call_count,2)

    def test_unready_feed_never_sends_or_claims(self):
        with patch.dict(os.environ,{'NOTICE_KIND':'release','RELEASE_TAG':'v0.11.2'}),patch.object(announce,'github',return_value=release_fixture()),patch.object(announce,'get_file',return_value=None),patch.object(announce.time,'sleep') as sleep,patch.object(announce,'send') as send,patch.object(announce,'save_state') as save:
            with self.assertRaises(announce.FeedNotReady):announce.main()
            self.assertEqual(sleep.call_count,3);send.assert_not_called();save.assert_not_called()

    def test_feed_asset_mismatch_or_newer_not_retried(self):
        for change,feed in [('url',feed_fixture()),('digest',feed_fixture()),('newer',feed_fixture('0.11.3'))]:
            release=release_fixture()
            if change=='url':release['assets'][0]['browser_download_url']='https://example.org/ExpLooper.exe'
            if change=='digest':release['assets'][0]['digest']='sha256:'+'b'*64
            with patch.object(announce,'github',return_value=release),patch.object(announce,'get_file',return_value=feed),patch.object(announce.time,'sleep') as sleep:
                with self.assertRaises(ValueError):announce.wait_release_feed('v0.11.2')
                sleep.assert_not_called()

    def test_missing_published_asset_blocks(self):
        release=release_fixture();release['assets'].pop()
        with patch.object(announce,'github',return_value=release),patch.object(announce,'get_file') as get:
            with self.assertRaises(announce.FeedNotReady):announce.release_feed_ready('v0.11.2')
            get.assert_not_called()

    def test_ai_image_review_assets_and_public_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            buffer=io.BytesIO();Image.new('RGB',(4,4),'white').save(buffer,format='PNG');data=buffer.getvalue()
            (root/'page.png').write_bytes(data)
            content={'summary':'인식 결과를 다시 확인합니다.'}
            manifest={'kind':'release','identity':'0.11.2','style_id':'expert-looper-ai-reference-v1',
                      'reference_sha256':'5e0bc380f4b938736bf5279c3a2936f1242fbf0d3d8b81106625aa0997addde8',
                      'prompt_source_sha':'a'*40,'content_sha256':announce.content_hash(content),'reviewed':True,
                      'images':[{'path':'page.png','sha256':hashlib.sha256(data).hexdigest()}]}
            path=root/'release-0.11.2.json'
            def write(value):path.write_text(json.dumps(value),encoding='utf-8')
            write(manifest)
            self.assertEqual(announce.approved_images('release','0.11.2',content,root),[root/'page.png'])
            for text in ['개선됩니다...','개선됩니다…','게임의 부활 동작을 변경합니다.','장면 넘기기 인식을 개선합니다.']:
                with self.assertRaises(ValueError):announce.approved_images('release','0.11.2',{'summary':text},root)
            for key,value in [('reviewed',False),('content_sha256','b'*64),('prompt_source_sha','bad'),('reference_sha256','c'*64),('images',[])]:
                broken=copy.deepcopy(manifest);broken[key]=value;write(broken)
                with self.assertRaises(ValueError):announce.approved_images('release','0.11.2',content,root)
            for entry in [{'path':'../outside.png','sha256':'a'*64},{'path':'page.png','sha256':'a'*64},{'path':'bad\r\nname.png','sha256':'a'*64}]:
                broken=copy.deepcopy(manifest);broken['images']=[entry];write(broken)
                with self.assertRaises(ValueError):announce.approved_images('release','0.11.2',content,root)
            write([])
            with self.assertRaises(ValueError):announce.approved_images('release','0.11.2',content,root)
            path.write_text('{bad-json',encoding='utf-8')
            with self.assertRaises(ValueError):announce.approved_images('release','0.11.2',content,root)
            for damaged in [b'\x89PNG\r\n\x1a\ntruncated',data[:40]]:
                (root/'page.png').write_bytes(damaged)
                broken=copy.deepcopy(manifest);broken['images'][0]['sha256']=hashlib.sha256(damaged).hexdigest();write(broken)
                with self.assertRaisesRegex(ValueError,'complete valid PNG'):announce.approved_images('release','0.11.2',content,root)


if __name__=="__main__":unittest.main()
