"""Publish release announcements; secrets stay in Actions, never in the app."""
import base64
import io
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid

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


def render_image_notes(entries, after, target, folder, fonts):
    """White/blue editorial release sheets: six icon-led summaries per page."""
    from PIL import Image, ImageDraw, ImageFont
    def font(size,bold=False):return ImageFont.truetype(str(fonts/("Pretendard-Bold.otf" if bold else "Pretendard-Regular.otf")),size)
    navy="#07132e";blue="#0878ff";muted="#596b96";rule="#cbdfff"
    cards=[]
    for v,body in entries:
        bullets=[clean(line)[2:] for line in body.splitlines() if line.startswith("- ")]
        if not bullets:bullets=[clean(body).replace("\n"," ")]
        title="사용 경험 개선"
        for pattern,label in [("OCR|인식","화면 인식 개선"),("포커스","작업 흐름 안정화"),("업데이트","편리한 업데이트"),("버그 제보","더 쉬운 버그 제보"),("암호화|난독화","배포 정보 보호"),("단축키","프로젝트 작업 개선")]:
            if re.search(pattern,body):title=label
        cards.append((v,title,bullets))
    if not cards:raise ValueError("No changes to illustrate")
    count=(len(cards)+5)//6
    if count>10:raise ValueError("Summary exceeds Discord image limit")
    folder.mkdir(parents=True,exist_ok=True);paths=[]
    for page in range(count):
        image=Image.new("RGB",(1200,1700),"#fcfdff");draw=ImageDraw.Draw(image)
        def center(text,y,size,color=navy,bold=False):
            f=font(size,bold);draw.text(((1200-draw.textlength(text,font=f))/2,y),text,font=f,fill=color)
        f=font(82,True);left="Expert ";right="Looper";x=(1200-draw.textlength(left+right,font=f))/2
        draw.text((x,52),left,font=f,fill=navy);draw.text((x+draw.textlength(left,font=f),52),right,font=f,fill=blue)
        center("U P D A T E  "+target,157,26,muted,True)
        center("더 편리한 작업, 더 안정적인 반복.",238,48,navy,True)
        center(f"{after} 이후 · {target}까지 주요 변경사항",318,30,muted)
        draw.line((600,405,600,1450),fill=rule,width=2)
        for index,(v,title,bullets) in enumerate(cards[page*6:page*6+6]):
            col=index%2;row=index//2;x=52+col*590;y=418+row*340
            draw.text((x,y),f"{page*6+index+1:02d}",font=font(29,True),fill=blue)
            draw.ellipse((x,y+52,x+112,y+164),fill="#eaf4ff")
            # Simple consistent line icons, generated as part of the template.
            cx=x+56;cy=y+106
            draw.rounded_rectangle((cx-29,cy-25,cx+29,cy+25),radius=7,outline=blue,width=5)
            draw.line((cx-15,cy,cx-3,cy+12,cx+18,cy-14),fill=blue,width=5)
            draw.text((x+133,y+12),title,font=font(29,True),fill=navy)
            draw.text((x+133,y+57),"v"+v,font=font(22,True),fill=blue)
            yy=y+99
            for bullet in bullets[:3]:
                lines=wrap(draw,bullet,font(23),390)
                if len(lines)>2:lines=lines[:2];lines[-1]=lines[-1][:-1]+"…"
                for line in lines:draw.text((x+133,yy),line,font=font(23),fill=muted);yy+=30
                yy+=10
            draw.line((x,y+316,x+545,y+316),fill=rule,width=1)
        draw.rounded_rectangle((50,1490,1150,1590),radius=24,fill="#f0f7ff",outline=rule,width=2)
        center("작은 개선이 모여, 더 편안한 자동화를 만듭니다.",1507,27,navy,True)
        center("주요 항목 요약 · 전체 변경내역은 릴리스 안내에서 확인하세요.",1550,21,muted)
        center(f"Expert Looper · Windows                         {page+1} / {count}",1623,24,muted)
        path=folder/f"업데이트 안내 {target} {page+1}.png";image.save(path);paths.append(path)
    return paths


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


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
    tag=os.environ["RELEASE_TAG"];version(tag)
    release=github("/releases/tags/"+tag)
    if release["draft"]:raise ValueError("Draft releases are not announced")
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
    if kind=="fix":
        text=clean(release.get("body") or "변경 내용은 릴리스에서 확인해 주세요.")
        content=f"새 업데이트가 도착했어요! 🛠️\n**Expert Looper {target} · 버그 수정**\n{text[:1500]}\n\n더 편하게 사용할 수 있도록 계속 다듬고 있어요. 알려주신 의견에 감사드립니다!"
    else:
        if version(anchor)<version(target):
            images=render_image_notes(cumulative(notes,anchor,target),anchor,target,pathlib.Path("output"),pathlib.Path("fonts"))
        content=f"새로운 기능과 개선사항을 만나보세요! ✨\n**Expert Looper {target}**\n{anchor} 이후 변경사항을 이미지로 정리했어요. 중간 버그 수정도 포함했습니다.\n함께 더 편리한 루퍼를 만들어주셔서 감사합니다!\n상세 변경내역: https://github.com/{REPO}/blob/main/CHANGELOG.md"
    download=f"새 버전을 준비했어요! 📦\n**Expert Looper {target} 다운로드**\nhttps://github.com/{REPO}/releases/download/{tag}/ExpLooper.exe\n\n이미 사용 중이라면 **도움말 → 업데이트 확인**으로도 업데이트할 수 있어요.\n직접 교체할 때는 프로그램을 종료하고 기존 폴더의 실행파일만 교체해 주세요. Data 폴더는 그대로 유지해 주세요!"
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
                if channel=="changelog" and kind!="fix" and not files:raise ValueError("Image baseline is not older than release")
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
