import os
import re
import time
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
CHANNEL_ID = "UCM246zZ4qNNmFQ2WHnP_CRA"
UPLOADS_PLAYLIST = "UUM246zZ4qNNmFQ2WHnP_CRA"
CACHE_TTL = 1800
playlist_cache = {"ts": 0, "entries": []}
info_cache = {}
INFO_TTL = 3600
cache_lock = threading.Lock()
THAI_MONTHS = {"มกราคม":1,"กุมภาพันธ์":2,"มีนาคม":3,"เมษายน":4,"พฤษภาคม":5,"มิถุนายน":6,"กรกฎาคม":7,"สิงหาคม":8,"กันยายน":9,"ตุลาคม":10,"พฤศจิกายน":11,"ธันวาคม":12}
def parse_time(time_str):
 parts = list(map(int, time_str.split(':')))
 if len(parts)==2: return parts[0]*60+parts[1]
 elif len(parts)==3: return parts[0]*3600+parts[1]*60+parts[2]
 return 0
def format_duration(seconds):
 if seconds<=0: return "—"
 mins=seconds//60; secs=seconds%60
 if mins>=60:
  hrs=mins//60; mins=mins%60
  return f"{hrs} ชม. {mins} นาที {secs} วิ" if secs else f"{hrs} ชม. {mins} นาที"
 return f"{secs} วิ" if mins==0 else f"{mins} นาที {secs} วิ"
def parse_timestamps_from_text(text):
 if not text: return []
 regex=r'(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2})'
 matches=list(re.finditer(regex, text))
 if len(matches)<2: return []
 items=[]
 for i in range(len(matches)):
  cur=matches[i]; nxt=matches[i+1] if i+1<len(matches) else None
  ts=cur.end(); te=nxt.start() if nxt else len(text)
  raw=text[ts:te].strip().split('\n')[0].strip()
  clean=re.sub(r'^[0-9\.\s\-–—:]+','',raw); clean=re.sub(r'[\-–—\s]+$','',clean).strip(); clean=re.sub(r'^\W+','',clean).strip()
  if not clean or len(clean)<2: clean=f"ตอนที่ {i+1}"
  if len(clean)>80: clean=clean[:80].strip()
  st=parse_time(cur.group(1)); et=parse_time(nxt.group(1)) if nxt else None
  dur=format_duration(et-st) if et and et>st else ("จนจบคลิป" if et is None else "—")
  items.append({"title":clean,"rawTime":cur.group(1),"time":st,"duration":dur})
 return items

def parse_story_list(text, total_duration):
    """Parse numbered story list like '1. บ้านขลังวิญญาณ - พี่แฉะ | 2. ประสบการณ์...' -> chapters equal-split"""
    if not text:
        return []
    _need_time = bool(total_duration)
    # Try split by | then by newline
    candidates = []
    # The full-day desc is usually "1. ... | 2. ... | 3. ..." on one line
    parts = re.split(r'\s*\|\s*', text)
    for part in parts:
        m = re.match(r'\s*\d+\.\s*(.+)', part.strip())
        if m:
            t = m.group(1).strip()
            # clean trailing " |" artifacts
            t = re.sub(r'\s+', ' ', t).strip()
            if len(t) >= 2:
                candidates.append(t)
    # Fallback: split by newline if | gave <2
    if len(candidates) < 2:
        candidates = []
        for line in text.splitlines():
            m = re.match(r'\s*\d+\.\s*(.+)', line.strip())
            if m:
                t = m.group(1).strip()
                if len(t) >= 2:
                    candidates.append(t)
    # Also try pattern "1. title - person" without | but with newline
    if len(candidates) < 2:
        return []
    # Filter: must look like story (have "-" or Thai, not just metadata)
    # Keep as is — but drop very long garbage
    filtered = []
    for c in candidates:
        if len(c) > 120:
            c = c[:120].strip()
        # skip if it's just "ฟังรายการสด" footer
        if "ฟังรายการสด" in c or "Fanpage" in c or "youtube.com" in c.lower():
            continue
        filtered.append(c)
    if len(filtered) < 2:
        return []
    n = len(filtered)
    if _need_time:
        seg = total_duration // n
    else:
        seg = 0
    chapters = []
    for i, title in enumerate(filtered):
        st = i * seg
        # last one goes to end
        if i == n-1:
            dur = total_duration - st
        else:
            dur = seg
        raw = f"{st//3600:02d}:{st%3600//60:02d}:{st%60:02d}" if st>=3600 else f"{st//60:02d}:{st%60:02d}" if _need_time else ""
        dur_str = format_duration(dur) if dur else "—"
        chapters.append({"title": title, "rawTime": raw, "time": st, "duration": dur_str, "estimated": True})
    return chapters
def extract_video_id(url):
 if not url: return ""
 url=url.strip()
 if re.match(r'^[A-Za-z0-9_-]{11}$',url): return url
 m=re.search(r'(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|live\/|shorts\/))([^#&?\/]+)',url)
 if m: return m.group(1)
 m2=re.search(r'([A-Za-z0-9_-]{11})',url)
 return m2.group(1) if m2 else url
def fetch_playlist_entries(limit=400,force=False):
 # adaptive cache: if cached limit < requested limit, refetch
 with cache_lock:
  if not force and playlist_cache["entries"] and (time.time()-playlist_cache["ts"]<CACHE_TTL):
   cached_limit = playlist_cache.get("limit", 0)
   if cached_limit >= limit:
    return playlist_cache["entries"]
   else:
    print(f"[*] cache {cached_limit} < need {limit} -> refetch")
 print(f"[+] fetch {UPLOADS_PLAYLIST} limit={limit}")
 opts={'quiet':True,'skip_download':True,'playlistend':limit,'extract_flat':True,'ignoreerrors':True,'no_warnings':True}
 try:
  with yt_dlp.YoutubeDL(opts) as ydl:
   info=ydl.extract_info(f"https://www.youtube.com/playlist?list={UPLOADS_PLAYLIST}",download=False)
   entries=[e for e in (info.get('entries') or []) if e and e.get('id')]
   print(f"[✓] fetched {len(entries)}")
   with cache_lock: playlist_cache["ts"]=time.time(); playlist_cache["entries"]=entries; playlist_cache["limit"]=limit
   return entries
 except Exception as e:
  print(f"[!] fetch failed: {e}")
  with cache_lock:
   if playlist_cache["entries"]: return playlist_cache["entries"]
  raise
@app.route('/api/get-episodes-by-month', methods=['POST'])
def get_episodes_by_month():
 data=request.json or {}
 try: year=int(data.get('year',2026)); month=int(data.get('month',10))
 except: year,month=2026,10
 sort_order=data.get('sort','asc'); target_prefix=f"{year:04d}-{month:02d}"
 print(f"\n[+] ดึงคลิป {target_prefix} ({sort_order})")
 try:
  # adaptive limit: recent months need 600, older need more (Jan-Apr 2026 needs ~2500)
  now = datetime.now()
  try:
   diff = (now.year - year)*12 + (now.month - month)
  except: diff = 0
  if diff <= 2: need = 700
  elif diff <= 4: need = 1500
  elif diff <= 8: need = 2500
  else: need = 3500
  print(f"[*] adaptive need={need} for {year}-{month:02d} (diff {diff} months)")
  entries=fetch_playlist_entries(limit=need)
  episodes=[]
  # flat entries have no upload_date — parse date from title (Thai + Eng)
  eng_months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
  thai_name_for_month = [k for k,v in THAI_MONTHS.items() if v==month]
  thai_name = thai_name_for_month[0] if thai_name_for_month else ""
  for e in entries:
   vid=e.get('id')
   if not vid: continue
   title=(e.get('title') or "").strip()
   # ✅ FULL-DAY ONLY: ฟังย้อนหลัง / ฟังสด / "THE GHOST RADIO | 27 กันยายน" (no •)
   if "•" in title:
       continue
   if ("ฟังย้อนหลัง" not in title) and ("ฟังสด" not in title):
       # allow standalone full title like "THE GHOST RADIO | 27 กันยายน 2569" but still no •
       if not (title.startswith("THE GHOST RADIO") and "|" in title):
           continue
   # try parse published date from title
   pub=""
   # Thai: "3 ตุลาคม 2569" or "27 กันยายน 2569"
   if thai_name and thai_name in title:
    m=re.search(r'(\d{1,2})\s*'+thai_name+r'\s*(\d{4})', title)
    if m:
     d=int(m.group(1)); y=int(m.group(2))
     if y>2400: y-=543
     pub=f"{y:04d}-{month:02d}-{d:02d}"
   # Eng: "Oct 4, '26" / "Oct 4, 2026" / "09/26/26" / "10/03/26"
   if not pub:
    # Oct 4
    for em, en in eng_months.items():
     if en==month and em.lower() in title.lower():
      m=re.search(em+r'\s+(\d{1,2})[^0-9]*\d{0,4}', title, re.I)
      if m:
       d=int(m.group(1))
       # year from title or default to requested year
       ym=re.search(r'(20\d{2})', title)
       y=int(ym.group(1)) if ym else year
       # handle '26 -> 2026
       if y<100: y=2000+y
       if y>2400: y-=543
       pub=f"{y:04d}-{month:02d}-{d:02d}"
       break
   # numeric: Thai D/M/Y strictly — 9/8/2569 = 9 Aug, not forced to requested month
   if not pub:
    m=re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', title)
    if m:
     a=int(m.group(1)); b=int(m.group(2)); y=int(m.group(3))
     if y<100: y=2000+y
     if y>2400: y-=543
     if 1<=a<=31 and 1<=b<=12:
      pub=f"{y:04d}-{b:02d}-{a:02d}"
   # fallback: if no date in title, use upload_date/timestamp if available (non-flat)
   if not pub:
    ud=e.get('upload_date'); ts=e.get('timestamp')
    if not ud and ts:
     try: ud=datetime.utcfromtimestamp(int(ts)).strftime("%Y%m%d")
     except: ud=None
    if ud and len(str(ud))==8: pub=f"{str(ud)[:4]}-{str(ud)[4:6]}-{str(ud)[6:8]}"
    elif ts:
     try: pub=datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
     except: pub=""
   # still no pub -> skip unless title contains month hint and we are broad
   if not pub or not pub.startswith(target_prefix):
    # also allow "ฟังย้อนหลัง" with thai month already matched? already handled
    # last chance: if title has thai month of requested month but date parse failed, assume 01
    if thai_name and thai_name in title and not pub:
     pub=f"{year:04d}-{month:02d}-01"
    else:
     if not pub: continue
     if not pub.startswith(target_prefix): continue
   # thumbnail: flat has no thumbnail/thumbnails, build from vid
   thumb=e.get('thumbnail') or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
   thumbs=e.get('thumbnails') or []
   if thumbs:
    try: best=sorted(thumbs,key=lambda x: x.get('width') or 0)[-1]; thumb=best.get('url') or thumb
    except: pass
   else:
    # try url field has thumbnail? flat entries have 'url' as youtube link
    pass
   episodes.append({"videoId":vid,"title":title,"publishedAt":pub,"thumbnail":thumb,"timestamp":e.get('timestamp') or 0})
  # ✅ De-dup: 1 clip per day — prefer ฟังย้อนหลัง over ฟังสด, then newest
  by_day = {}
  for ep in episodes:
      d = ep['publishedAt']
      prev = by_day.get(d)
      if prev is None:
          by_day[d] = ep
      else:
          # prefer ฟังย้อนหลัง
          cur_is_yon = "ฟังย้อนหลัง" in ep['title']
          prev_is_yon = "ฟังย้อนหลัง" in prev['title']
          if cur_is_yon and not prev_is_yon:
              by_day[d] = ep
          elif cur_is_yon == prev_is_yon and (ep.get('timestamp',0) > prev.get('timestamp',0)):
              by_day[d] = ep
  episodes = list(by_day.values())
  reverse=(sort_order=='desc')
  episodes.sort(key=lambda x: (x['publishedAt'],x.get('timestamp',0)),reverse=reverse)
  print(f"[✓] พบ {len(episodes)} วัน (de-dup จาก {len(by_day)} วัน, raw {len(episodes)}) — {', '.join(sorted(by_day.keys()))}")
  return jsonify({"episodes":episodes})
 except Exception as e:
  import traceback; traceback.print_exc()
  return jsonify({"error":str(e),"episodes":[]}),500
@app.route('/api/get-info', methods=['POST'])
def get_info():
 data=request.json or {}; url=data.get('url',''); video_id=extract_video_id(url)
 if not video_id or len(video_id)<8: return jsonify({"error":"Invalid","id":video_id}),400
 ck=video_id; hit=info_cache.get(ck)
 if hit and time.time()-hit["ts"] < INFO_TTL:
  print(f"[⚡ cache hit] {video_id}")
  return jsonify(hit["data"])
 print(f"\n[+] ดึงเสียง {video_id}")
 audio_url=""; video_title=""; description=""; chapters_raw=[]; duration=0
 try:
  opts={'format':'bestaudio[ext=m4a]/bestaudio/best','quiet':True,'skip_download':True,'no_warnings':True,'getcomments':True,'extractor_args': {'youtube': {'max_comments': ['100']}}}
  with yt_dlp.YoutubeDL(opts) as ydl:
   info=ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",download=False)
   audio_url=info.get('url','') or ""
   if not audio_url:
    fmts=[f for f in (info.get('formats') or []) if f.get('acodec')!='none']
    if fmts: fmts.sort(key=lambda x: x.get('abr') or 0,reverse=True); audio_url=fmts[0].get('url') or ""
   video_title=info.get('title') or ""; description=info.get('description') or ""; duration=int(info.get('duration') or 0); chapters_raw=info.get('chapters') or []
 except Exception as err:
  print(f"[!] {err}")
 chapters=[]
 if chapters_raw and len(chapters_raw)>=1:
  for i,ch in enumerate(chapters_raw):
   st=int(ch.get('start_time') or 0); et=ch.get('end_time'); title=ch.get('title') or f"ตอนที่ {i+1}"
   if et is not None:
    try: dur=format_duration(int(et)-st)
    except: dur="—"
   else:
    nxt=chapters_raw[i+1].get('start_time') if i+1<len(chapters_raw) else None
    if nxt is not None:
     try: dur=format_duration(int(nxt)-st)
     except: dur="—"
    else: dur="จนจบคลิป" if duration else "—"
   raw=f"{st//3600:02d}:{st%3600//60:02d}:{st%60:02d}" if st>=3600 else f"{st//60:02d}:{st%60:02d}"
   chapters.append({"title":title,"rawTime":raw,"time":st,"duration":dur})
 if not chapters or len(chapters)<2:
  parsed=parse_timestamps_from_text(description)
  if len(parsed)>=2:
      for c in parsed: c["estimated"] = False
      chapters=parsed
 # ✅ PINNED COMMENT (TheGhost) is ground truth for full lives — timestamps like "0:15:45 1. คืนปล่อยผี"
 # Description has only "1. คืนปล่อยผี - คุณปุ๊" without times
 if not chapters or len(chapters)<2:
  try:
      # fetch up to 60 comments, look for pinned by TheGhost/@soponwich33 with timestamps
      c_comments = info.get('comments') or []
      best = []
      for cmt in c_comments:
          txt = (cmt.get('text') or '')
          is_pinned = bool(cmt.get('is_pinned'))
          author = (cmt.get('author') or '')
          # pinned comment has timestamps
          if is_pinned and re.search(r'\d{1,2}:\d{2}:\d{2}', txt):
              cand = parse_timestamps_from_text(txt)
              if len(cand) >= 3:
                  best = cand
                  print(f"[✓] pinned comment by {author} -> {len(best)} chapters (real 100%)")
                  break
      # fallback: any comment with >=5 timestamps (sometimes not flagged pinned)
      if not best:
          for cmt in c_comments:
              txt = (cmt.get('text') or '')
              if re.search(r'\d{1,2}:\d{2}:\d{2}', txt):
                  cand = parse_timestamps_from_text(txt)
                  if len(cand) >= 3:
                      best = cand
                      print(f"[✓] comment fallback -> {len(best)} chapters")
                      break
      if best:
          for c in best: c["estimated"] = False
          chapters = best
  except Exception as e:
      print(f"[!] pinned comment parse fail: {e}")
 # FULL-DAY with no real timestamps anywhere — single track (honest)
 if not chapters:
  total = duration or 0
  dur_str = format_duration(total) if total else "เต็มรายการ"
  chapters=[{"title": "▶ ฟังเต็มรายการ ("+dur_str+")", "rawTime": "00:00", "time": 0, "duration": dur_str, "estimated": False}]
 story_names = []
 try:
  names = parse_story_list(description, 0)
  if names: story_names = [c["title"] for c in names]
 except: pass
 if not audio_url:
  try:
   with yt_dlp.YoutubeDL({'quiet':True,'skip_download':True,'format':'bestaudio/best'}) as ydl2:
    audio_url=ydl2.extract_info(f"https://www.youtube.com/watch?v={video_id}",download=False).get('url','') or ""
  except: pass
 resp={"id":video_id,"title":video_title,"audioUrl":audio_url,"duration":duration,"chapters":chapters,"storyNames": story_names}
 info_cache[ck]={"ts": time.time(), "data": resp}
 if len(info_cache) > 80:
  oldest=min(info_cache, key=lambda k: info_cache[k]["ts"])
  del info_cache[oldest]
 return jsonify(resp)
@app.route('/api/health', methods=['GET'])
def health():
 return jsonify({"ok":True,"channel":CHANNEL_ID,"playlist":UPLOADS_PLAYLIST,"cached":len(playlist_cache["entries"])})
if __name__=='__main__':
 port=int(os.environ.get('PORT', 7860))
 print(f"🚀 http://localhost:{port}/index.html"); print(f"   {CHANNEL_ID} -> {UPLOADS_PLAYLIST} (PORT={port})")
 app.run(host='0.0.0.0',port=port,debug=False,threaded=True)
