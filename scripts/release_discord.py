"""Publish release announcements; secrets stay in Actions, never in the app."""
import base64
import hashlib
import io
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import datetime
import time
from PIL import Image
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

UPDATE_PUBLIC_KEY = pathlib.Path(__file__).resolve().parents[1] / 'assets/update-public-key.pem'
if not UPDATE_PUBLIC_KEY.is_file():
    UPDATE_PUBLIC_KEY = pathlib.Path(__file__).resolve().parents[1] / 'src/ExpLooper/Assets/update-public-key.pem'


def verified_update_payload(envelope):
    """Authenticate exact payload bytes with the app's pinned RSA-PSS trust root."""
    try:
        if not isinstance(envelope, dict):
            raise ValueError('Invalid envelope')
        payload = base64.b64decode(envelope['Payload'], validate=True)
        signature = base64.b64decode(envelope['Signature'], validate=True)
        if not 1 <= len(payload) <= 1_000_000:
            raise ValueError('Update payload size exceeds limit')
        key = serialization.load_pem_public_key(UPDATE_PUBLIC_KEY.read_bytes())
        if not isinstance(key, rsa.RSAPublicKey):
            raise ValueError('RSA public key required')
        key.verify(signature, payload, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                                  salt_length=hashes.SHA256().digest_size), hashes.SHA256())
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError('Invalid update payload')
        return result
    except (InvalidSignature, KeyError, TypeError, ValueError, UnicodeError) as error:
        raise ValueError('Update manifest signature or payload is invalid') from None


REPO = "DrFREEST/Expert-Looper-Releases"
INITIAL_IMAGE_VERSION = "0.8.20"


def version(value):
    if not re.fullmatch(r"v?0\.\d+\.\d+", value): raise ValueError("Invalid version")
    return tuple(map(int, value.lstrip("v").split(".")))


def classify(release, previous):
    explicit = re.search(r"<!-- expert-looper-release: (fix|feature|improvement) -->", release.get("body") or "")
    if explicit: return explicit[1]
    if version(release["tag_name"])[:2] > version(previous)[:2]: return "feature"
    if re.search(r"기능 추가|새 기능|개선|최적화|성능 향상",release.get("body") or ""):return "improvement"
    return "fix"


def history(markdown):
    return {m[1]: m[2].strip() for m in re.finditer(r"(?ms)^## (0\.\d+\.\d+)[^\n]*\n(.*?)(?=^## |\Z)", markdown)}


def cumulative(notes, after, target):
    return [(v, notes[v]) for v in sorted(notes,key=version) if version(after) < version(v) <= version(target)]


def clean(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def wrap(draw, text, font, width):
    lines=[]; line=""
    for char in text:
        if draw.textlength(line+char,font=font)>width:
            lines.append(line);line=""
        line+=char
    if line:lines.append(line)
    return lines or [""]


def public_notice_text(text):
    """Reject domain-specific copy and clipped sentences before any delivery."""
    if re.search(r"전리품|장면\s*넘기기|부활|어비스|마비노기|게임", text, re.I):
        raise ValueError("Use general-purpose Windows automation wording")
    if "…" in text or "..." in text:
        raise ValueError("Use complete sentences; split items or pages instead of ellipsis")
    return text


def release_notice(release, target, kind, anchor, *, has_progress=True):
    """Keep reviewed facts in the message; the image is only a quick summary."""
    details = public_notice_text(clean(release.get("body") or "이번 버전의 변경 설명이 없습니다. 아래 변경 내용 링크에서 확인해 주세요."))
    if len(details) > 1500:
        raise ValueError("Rewrite complete concise release sentences before delivery")
    label = {"fix": "잘못 동작하던 부분을 고쳤습니다", "feature": "새 기능을 추가했습니다",
             "improvement": "기존 기능을 다듬었습니다"}[kind]
    text = (
        f"**Expert Looper {target} 업데이트 안내**\n{label}.\n\n"
        f"**바뀐 점과 사용 방법**\n{details}\n\n"
        "**새 버전으로 바꾸는 방법**\n프로그램의 **도움말 → 업데이트 확인**을 눌러 새 버전으로 바꿔 주세요.\n\n"
    )
    if kind != "fix":
        text += f"첨부 이미지에는 {anchor} 이후 바뀐 내용의 핵심을 담았습니다. 중간에 고친 내용도 포함했습니다.\n"
    text += f"전체 변경 내용: https://github.com/{REPO}/blob/main/CHANGELOG.md"
    if has_progress:
        text += "\n\n함께 첨부한 개발 진행 이미지는 준비 중인 작업입니다. 아직 사용할 수 없습니다. 업데이트 날짜는 정해지지 않았습니다."
    if len(text) > 2000:
        raise ValueError("Rewrite complete release details to fit the message; do not clip")
    return text


def download_notice(tag, target):
    return (
        f"**Expert Looper {target} 받기**\n\n"
        "**이미 사용하고 있나요?**\n1. 프로그램 위쪽의 **도움말**을 누르세요.\n"
        "2. **업데이트 확인**을 누르고 화면의 안내를 따라 주세요.\n\n"
        "**처음 사용하거나 파일을 직접 바꾸나요?**\n"
        f"1. 아래 링크를 눌러 프로그램 파일을 받으세요.\nhttps://github.com/{REPO}/releases/download/{tag}/ExpLooper.exe\n"
        "2. 실행 중인 Expert Looper를 종료하세요. 기존 폴더의 ExpLooper.exe 파일만 새 파일로 바꾸세요.\n"
        "처음 사용한다면 받은 파일을 원하는 폴더에 넣고 실행하세요.\n\n"
        "**저장한 작업을 지켜 주세요.**\nData 폴더에는 저장한 작업과 설정이 들어 있습니다. 삭제하지 마세요. 그대로 두세요."
    )


def content_hash(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def approved_images(kind, identity, content, root=pathlib.Path("channel-images")):
    """Use reviewed AI output only. Never fall back to a code-rendered template."""
    if kind not in {"release", "progress"} or not re.fullmatch(r"[a-zA-Z0-9_.-]+", identity):
        raise ValueError("Invalid image identity")
    public_notice_text(json.dumps(content, ensure_ascii=False))
    root = root.resolve()
    manifest_path = (root / (kind + "-" + identity + ".json")).resolve()
    if not manifest_path.is_relative_to(root) or manifest_path.stat().st_size > 65536:
        raise ValueError("Image review manifest must stay inside channel-images and be bounded")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict): raise ValueError("Invalid image review manifest")
    if (manifest.get("style_id") != "expert-looper-ai-reference-v1"
            or manifest.get("reference_sha256") != "5e0bc380f4b938736bf5279c3a2936f1242fbf0d3d8b81106625aa0997addde8"
            or manifest.get("kind") != kind or manifest.get("identity") != identity
            or manifest.get("content_sha256") != content_hash(content)
            or manifest.get("reviewed") is not True
            or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("prompt_source_sha", ""))):
        raise ValueError("AI image review is missing or stale")
    assets = manifest.get("images", [])
    if not isinstance(assets, list) or not 1 <= len(assets) <= 9:
        raise ValueError("Review 1-9 image pages before delivery")
    result = []
    for entry in assets:
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or not re.fullmatch(r"[A-Za-z0-9_./ -]+", entry["path"])
                or pathlib.Path(entry["path"]).is_absolute()):
            raise ValueError("Invalid image asset path")
        path = (root / entry["path"]).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != ".png":
            raise ValueError("Image path must stay inside channel-images")
        if path.stat().st_size > 8 * 1024 * 1024: raise ValueError("Image exceeds attachment size limit")
        data = path.read_bytes()
        if (not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 8 * 1024 * 1024
                or hashlib.sha256(data).hexdigest() != entry.get("sha256")):
            raise ValueError("AI image asset changed since review")
        try:
            with Image.open(io.BytesIO(data)) as png:
                if png.format != 'PNG' or png.width * png.height > 16_000_000 or png.width > 8192 or png.height > 8192:
                    raise ValueError('Image dimensions exceed review limits')
                png.verify()
            # verify() validates chunks; load() also forces complete pixel decoding.
            with Image.open(io.BytesIO(data)) as png:
                png.load()
        except Exception as error:
            raise ValueError('AI image is not a complete valid PNG') from error
        if path in result: raise ValueError("Duplicate image page")
        result.append(path)
    return result


def render_image_notes(entries, after, target, folder, fonts):
    # Compatibility entry point for the existing notification workflow.
    return approved_images("release", target, {"after": after, "target": target, "entries": entries})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def progress_notice(path=pathlib.Path("개발 진행 안내.json"), today=None):
    """Publish reviewed public summaries only, never private issue bodies."""
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    today=today or datetime.datetime.now(datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=9))).date()
    if not re.fullmatch(r"[a-z0-9-]{8,64}",data.get("id","")):raise ValueError("Invalid bulletin identity")
    reviewed=datetime.date.fromisoformat(data["reviewed_on"])
    expires=datetime.date.fromisoformat(data["valid_until"])
    if not reviewed<=today<=expires or (expires-reviewed).days>14:raise ValueError("Progress summary needs review")
    items=data.get("items",[])
    if not isinstance(items,list) or not 0<=len(items)<=3:raise ValueError("Progress summary needs 0..3 items")
    for item in items:
        if item.get("status") not in ("진행 중","업데이트 예정"):raise ValueError("Invalid progress state")
        if not isinstance(item.get("title"),str) or not 1<=len(item["title"])<=28:raise ValueError("Invalid progress title")
        if not isinstance(item.get("summary"),str) or not 1<=len(item["summary"])<=100:raise ValueError("Invalid progress summary")
        if any(c in item["title"]+item["summary"] for c in "\r\n"):raise ValueError("Use single-line summaries")
    return data


def render_progress(data, folder, fonts):
    images = approved_images("progress", data["id"], data)
    if len(images) != 1:
        raise ValueError("Progress bulletin requires one reviewed page")
    return images[0]


def announce_progress():
    data=progress_notice()
    if not data["items"]:
        print("진행 안내 항목이 없어 전송하지 않습니다.")
        raise ValueError("진행 안내 항목이 없어 전송하지 않습니다.")
    state_path=".release-notifications/progress-"+data["id"]+".json"
    existing=get_file(state_path)
    if existing:
        state=json.loads(base64.b64decode(existing["content"]))
        if state["status"]!="sent":raise ValueError("Pending delivery requires operator verification")
        return
    image=render_progress(data,pathlib.Path("output"),pathlib.Path("fonts"))
    content="**Expert Looper · 개발 진행 안내**\n만들고 있는 기능과 앞으로 바뀔 내용을 이미지로 정리했습니다.\n지금은 준비 중이라 아직 사용할 수 없습니다. 시험을 마친 뒤 업데이트 날짜를 안내하겠습니다."
    claim=save_state(state_path,{"status":"pending","bulletin":data["id"]})
    message_id=send(os.environ["DISCORD_CHANGELOG_WEBHOOK"],content,[image])
    save_state(state_path,{"status":"sent","bulletin":data["id"],"messageId":message_id},claim)


def github(path, method="GET", data=None):
    headers={"Authorization":"Bearer "+os.environ["GITHUB_TOKEN"].strip(),"User-Agent":"ExpertLooper-Releases","Accept":"application/vnd.github+json"}
    body=None
    if data is not None:body=json.dumps(data).encode();headers["Content-Type"]="application/json"
    req=urllib.request.Request("https://api.github.com/repos/"+REPO+path,data=body,headers=headers,method=method)
    with urllib.request.build_opener(NoRedirect).open(req,timeout=30) as response:return json.load(response)


def get_file(path):
    try:return github("/contents/"+path+"?ref=main")
    except urllib.error.HTTPError as e:
        if e.code==404:return None
        raise


class FeedNotReady(ValueError):
    pass


def release_feed_ready(tag):
    """Read-only readiness check. Publishing precedes the feed PUT, so a short lag is normal."""
    expected = tag.lstrip('v')
    release = github('/releases/tags/' + tag)
    if release.get('draft') or release.get('tag_name') != tag or not release.get('published_at'):
        raise FeedNotReady('Release is not published yet')
    assets = release.get('assets', [])
    selected = {}
    for name in ('ExpLooper.exe', 'update.json'):
        matches = [a for a in assets if a.get('name') == name]
        if len(matches) != 1 or matches[0].get('state') != 'uploaded' or matches[0].get('size', 0) <= 0:
            raise FeedNotReady('Published release assets are not ready')
        if matches[0].get('browser_download_url') != f'https://github.com/{REPO}/releases/download/{tag}/{name}':
            raise ValueError('Unexpected published asset URL')
        selected[name] = matches[0]
    current = get_file('update.json')
    if not current: raise FeedNotReady('Update feed is not available yet')
    envelope = json.loads(base64.b64decode(current['content']))
    payload = verified_update_payload(envelope)
    if payload.get('Version') != expected:
        if version(payload.get('Version', '')) < version(expected):
            raise FeedNotReady('Update feed still advertises the preceding release')
        raise ValueError('Update feed already advertises a newer release')
    if (payload.get('Url') != selected['ExpLooper.exe']['browser_download_url']
            or payload.get('Size') != selected['ExpLooper.exe']['size']
            or not re.fullmatch(r'[A-Fa-f0-9]{64}', payload.get('Sha256', ''))):
        raise ValueError('Update feed does not identify the published executable')
    digest = selected['ExpLooper.exe'].get('digest')
    if digest and digest.lower() != 'sha256:' + payload['Sha256'].lower():
        raise ValueError('Update feed and published executable hash differ')
    return release


def wait_release_feed(tag, attempts=4, delay=10):
    for attempt in range(attempts):
        try: return release_feed_ready(tag)
        except urllib.error.HTTPError as error:
            if error.code not in (404, 429, 500, 502, 503, 504): raise
        except (FeedNotReady, urllib.error.URLError, TimeoutError):
            pass
        if attempt + 1 < attempts: time.sleep(delay)
    raise FeedNotReady('Release feed readiness timed out; no announcement sent')


def save_state(path,data,old=None):
    body={"message":"Record release notification state","branch":"main","content":base64.b64encode(json.dumps(data).encode()).decode()}
    if old:body["sha"]=old["sha"]
    return github("/contents/"+path,"PUT",body)["content"]


def send(webhook,content,images):
    uri=urllib.parse.urlparse(webhook.strip())
    if uri.scheme!="https" or uri.hostname not in ("discord.com","discordapp.com") or uri.username or uri.port not in (None,443) or not re.fullmatch(r"/api/webhooks/\d+/[\w-]+",uri.path):raise ValueError("Invalid webhook configuration")
    boundary=uuid.uuid4().hex;body=io.BytesIO()
    def part(name,data,filename=None):
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"".encode())
        if filename:body.write(f'; filename="{filename}"\r\nContent-Type: image/png'.encode())
        body.write(b"\r\n\r\n"+data+b"\r\n")
    payload={"content":content,"allowed_mentions":{"parse":[]}}
    part("payload_json",json.dumps(payload).encode())
    for i,path in enumerate(images):part(f"files[{i}]",path.read_bytes(),path.name)
    body.write(f"--{boundary}--\r\n".encode())
    request=urllib.request.Request("https://discord.com"+uri.path+"?wait=true",data=body.getvalue(),headers={"Content-Type":"multipart/form-data; boundary="+boundary,"User-Agent":"ExpertLooper-Releases"})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=60) as response:return json.load(response)["id"]


def main():
    if os.environ.get("NOTICE_KIND","release")=="progress":return announce_progress()
    tag=os.environ["RELEASE_TAG"];version(tag)
    release=wait_release_feed(tag)
    all_releases=[]
    for page in range(1,101):
        batch=github(f"/releases?per_page=100&page={page}");all_releases.extend(batch)
        if len(batch)<100:break
    prior=[r for r in all_releases if not r["draft"] and re.fullmatch(r"v?0\.\d+\.\d+",r["tag_name"]) and version(r["tag_name"])<version(tag)]
    previous=max(prior,key=lambda r:version(r["tag_name"]))["tag_name"] if prior else "0.0.0"
    kind=classify(release,previous);target=tag.lstrip("v")
    anchor_file=get_file(".release-notifications/image-anchor.json")
    anchor=json.loads(base64.b64decode(anchor_file["content"]))["version"] if anchor_file else INITIAL_IMAGE_VERSION
    notes=history(pathlib.Path("CHANGELOG.md").read_text(encoding="utf-8"))
    for r in all_releases:
        if re.fullmatch(r"v?0\.\d+\.\d+",r["tag_name"]) and not r["draft"]:notes[r["tag_name"].lstrip("v")]=clean(r.get("body") or "")
    images=[];url=release["html_url"]
    content = release_notice(release, target, kind, anchor, has_progress=False)
    download = download_notice(tag, target)
    errors=[]
    for channel,secret,text,files in (("changelog","DISCORD_CHANGELOG_WEBHOOK",content,images),("download","DISCORD_DOWNLOAD_WEBHOOK",download,[])):
        try:
            state_path=f".release-notifications/{release['id']}-{channel}.json"
            existing=get_file(state_path)
            if existing:
                state=json.loads(base64.b64decode(existing["content"]))
                if state["status"]!="sent":raise ValueError("Pending delivery requires operator verification")
                message_id=state["messageId"]
            else:
                if channel=="changelog":
                    if kind != "fix":
                        if version(anchor) >= version(target): raise ValueError("Image baseline is not older than release")
                        files=render_image_notes(cumulative(notes,anchor,target),anchor,target,pathlib.Path("output"),pathlib.Path("fonts"))
                    progress_data=progress_notice()
                    if progress_data["items"]:
                        progress=render_progress(progress_data,pathlib.Path("output"),pathlib.Path("fonts"))
                        files=[*files,progress]
                        text=release_notice(release,target,kind,anchor,has_progress=True)
                    if len(files)>10:raise ValueError("Combined summary exceeds Discord attachment limit")
                claim=save_state(state_path,{"status":"pending","version":target,"kind":kind})
                # Never blindly retry an uncertain POST; inspect the channel first.
                message_id=send(os.environ[secret],text,files)
                save_state(state_path,{"status":"sent","version":target,"kind":kind,"messageId":message_id},claim)
            if channel=="changelog" and kind!="fix" and version(anchor)<version(target):
                save_state(".release-notifications/image-anchor.json",{"version":target,"messageId":message_id},anchor_file)
            print(channel+" notification completed (or already sent).")
        except Exception as error:errors.append(type(error).__name__)
    if errors:raise RuntimeError("One or more notification channels need verification")


if __name__=="__main__":
    try:main()
    except Exception as error:
        # Exception URLs may contain credentials; never print raw exceptions.
        print("Release notification failed: "+type(error).__name__+"; inspect pending state before retry.")
        raise SystemExit(1)
