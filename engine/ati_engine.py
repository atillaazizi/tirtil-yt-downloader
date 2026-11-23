"""
Tırtıl Engine Worker - Tırtıl YT Downloader (macOS)
Electron UI'ya satır satır JSON olay akışı gönderir.
Fork: dotu-yt by rtrw_ (MIT)
"""

import os
import base64
import sys
import json
import re
import glob
import time
import random
import shutil
import traceback
import sqlite3
import tempfile
import subprocess
import threading
import urllib.parse
import concurrent.futures
import difflib
import math
import unicodedata
import platform


def _patch_mac_ver():
    """Bazı Mac'lerde platform.mac_ver() boş sürüm döndürür; paketli yt-dlp bunu int()'e
    çevirirken "invalid literal for int() with base 10: ''" ile çöker. sw_vers'e düş."""
    original = platform.mac_ver

    def safe_mac_ver(*args, **kwargs):
        release, versioninfo, machine = original(*args, **kwargs)
        if not re.fullmatch(r"\d+(\.\d+)*", release or ""):
            try:
                out = subprocess.run(["/usr/bin/sw_vers", "-productVersion"],
                                     capture_output=True, text=True, timeout=5).stdout.strip()
            except Exception:
                out = ""
            release = out if re.fullmatch(r"\d+(\.\d+)*", out) else "14.0"
        return release, versioninfo, machine

    platform.mac_ver = safe_mac_ver


_patch_mac_ver()

def _vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "")))


def _load_ytdlp():
    """Uygulama yt-dlp'nin daha yeni bir sürümünü indirdiyse (ATI_YTDLP_DIR) onu, yoksa paketteki
    sürümü yükler. Yeni sürüm açılamazsa paketteki sürüme döner."""
    from importlib import metadata
    try:
        bundled = metadata.version("yt-dlp")
    except Exception:
        bundled = "0"
    base = os.environ.get("ATI_YTDLP_DIR")
    try:
        with open(os.path.join(base, "current.txt"), encoding="utf-8") as f:
            ver = f.read().strip()
        zpath = os.path.join(base, f"yt-dlp-{ver}.zip")
        if re.fullmatch(r"[\d.]+", ver) and _vtuple(ver) > _vtuple(bundled) and os.path.isfile(zpath):
            sys.path.insert(0, zpath)
            try:
                import yt_dlp as mod
                # Zip bozuksa Python sessizce paketteki sürüme düşer; gerçekten zipten mi geldi?
                if not os.path.abspath(mod.__file__ or "").startswith(os.path.abspath(zpath) + os.sep):
                    raise ImportError("yt-dlp zip açılamadı")
                return mod, bundled, "güncel"
            except Exception:
                sys.path.remove(zpath)
                for name in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
                    del sys.modules[name]
    except Exception:
        pass
    import yt_dlp as mod
    return mod, bundled, "paket"


yt_dlp, YTDLP_BUNDLED, YTDLP_SOURCE = _load_ytdlp()  # mac_ver yamasından sonra yüklenmeli

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

HOME = os.path.expanduser("~")
APP_SUPPORT = os.path.join(HOME, "Library", "Application Support")
EXTRA_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]


def send_event(event_type, **kwargs):
    payload = {"event": event_type}
    payload.update(kwargs)
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


LOG_DIR = os.environ.get("ATI_LOG_DIR") or os.path.join(HOME, "Library", "Logs", "Tırtıl")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "ati_latest.log")
_log_lock = threading.Lock()


def write_persistent_log(line):
    try:
        with _log_lock, open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log(msg, level="info"):
    timestamp = time.strftime("%H:%M:%S")
    send_event("log", message=msg, level=level, timestamp=timestamp)
    write_persistent_log(f"[{timestamp}] [{level.upper()}] {msg}")


# --- Tarayıcı cookie keşfi (macOS) ---------------------------------------

CHROMIUM_BROWSERS = [
    ("chrome", os.path.join(APP_SUPPORT, "Google", "Chrome")),
    ("brave", os.path.join(APP_SUPPORT, "BraveSoftware", "Brave-Browser")),
    ("edge", os.path.join(APP_SUPPORT, "Microsoft Edge")),
    ("vivaldi", os.path.join(APP_SUPPORT, "Vivaldi")),
    ("opera", os.path.join(APP_SUPPORT, "com.operasoftware.Opera")),
    ("chromium", os.path.join(APP_SUPPORT, "Chromium")),
]
FIREFOX_PROFILES = os.path.join(APP_SUPPORT, "Firefox", "Profiles")


# macOS izni yüzünden cookie'si okunamayan tarayıcılar (kullanıcıya Tam Disk Erişimi önermek için)
COOKIE_BLOCKED = []


def _count_yt_cookies(db_path, query):
    """Kilitli olabilecek DB'yi geçici kopyadan okuyup YouTube cookie sayısını döndürür.
    Okunamıyorsa (macOS izni vb.) None döner."""
    fd, temp_db = tempfile.mkstemp(prefix="ati_ck_probe_", suffix=".db")
    os.close(fd)
    try:
        shutil.copyfile(db_path, temp_db)
        conn = sqlite3.connect(temp_db)
        try:
            return conn.execute(query).fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None
    finally:
        try:
            os.remove(temp_db)
        except OSError:
            pass


def _chromium_profiles(base_dir, browser):
    if browser == "opera":
        return [""]
    profiles = ["Default"]
    for d in sorted(glob.glob(os.path.join(base_dir, "Profile *"))):
        profiles.append(os.path.basename(d))
    return profiles


def _probe_chromium(browser, base_dir):
    """YouTube cookie'si olan profiller arasından en son kullanılanı seçer."""
    if not os.path.isdir(base_dir):
        return None
    best = None  # (mtime, prof)
    blocked = False
    for prof in _chromium_profiles(base_dir, browser):
        prof_dir = os.path.join(base_dir, prof) if prof else base_dir
        for cookie_file in (os.path.join(prof_dir, "Network", "Cookies"), os.path.join(prof_dir, "Cookies")):
            if not os.path.isfile(cookie_file):
                continue
            try:
                # yt-dlp profili klasörü listeleyerek arar; listelenemiyorsa o da bulamaz
                os.listdir(prof_dir)
            except OSError:
                blocked = True
                break
            cnt = _count_yt_cookies(cookie_file, "SELECT count(*) FROM cookies WHERE host_key LIKE '%youtube%'")
            if cnt is None:
                blocked = True
                break
            if cnt > 0:
                mtime = os.path.getmtime(cookie_file)
                if best is None or mtime > best[0]:
                    best = (mtime, prof)
            break
    if best:
        prof = best[1]
        desc = browser.capitalize() + (f" ({prof})" if prof else "")
        return (browser, prof or None, f"Cookie otomatik bulundu: {desc} aktif oturum ✅")
    if blocked and browser not in COOKIE_BLOCKED:
        COOKIE_BLOCKED.append(browser)
    return None


def _probe_firefox():
    if not os.path.isdir(FIREFOX_PROFILES):
        return None
    for prof_dir in sorted(glob.glob(os.path.join(FIREFOX_PROFILES, "*"))):
        cookie_file = os.path.join(prof_dir, "cookies.sqlite")
        if not os.path.isfile(cookie_file):
            continue
        cnt = _count_yt_cookies(cookie_file, "SELECT count(*) FROM moz_cookies WHERE host LIKE '%youtube%'")
        if cnt is None:
            if "firefox" not in COOKIE_BLOCKED:
                COOKIE_BLOCKED.append("firefox")
            continue
        if cnt > 0:
            return ("firefox", prof_dir, f"Cookie otomatik bulundu: Firefox ({os.path.basename(prof_dir)}) aktif oturum ✅")
    return None


def find_best_browser_cookies(preferred="auto"):
    """
    macOS tarayıcılarında YouTube oturumu olan profili bulur.
    Dönen: (browser, profile, mesaj) veya None.
    Safari otomatik taranmaz (Tam Disk Erişimi ister); elle seçilebilir.
    """
    pref = (preferred or "auto").strip().lower()
    if pref == "none":
        return None
    if pref == "safari":
        return ("safari", None, "Safari cookie'leri kullanılıyor (Tam Disk Erişimi gerekebilir)")
    if pref == "firefox":
        return _probe_firefox() or ("firefox", None, "Firefox cookie'leri deneniyor")

    if pref != "auto":
        for b_name, base_dir in CHROMIUM_BROWSERS:
            if b_name == pref:
                found = _probe_chromium(b_name, base_dir)
                if found:
                    return found
                # İzin yüzünden okunamıyorsa boşuna denemeyip cookie'siz devam et
                return None if pref in COOKIE_BLOCKED else (pref, None, f"{pref.capitalize()} cookie'leri deneniyor")
        return (pref, None, f"{pref} cookie'leri deneniyor")

    for b_name, base_dir in CHROMIUM_BROWSERS:
        found = _probe_chromium(b_name, base_dir)
        if found:
            return found
    return _probe_firefox()


# --- Harici araçlar --------------------------------------------------------

def _find_tool(name):
    bundled = os.environ.get("ATI_FFMPEG_DIR")
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for d in filter(None, [bundled, os.path.join(base, "ffmpeg")]):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_BIN_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def get_ffmpeg_bin():
    return _find_tool("ffmpeg") or "ffmpeg"


def get_node_bin():
    # Paketli uygulamada Electron'un kendi Node'u (ATI_NODE_BIN shim) — kurulum gerektirmez.
    shim = os.environ.get("ATI_NODE_BIN")
    if shim and os.path.isfile(shim):
        return "node", shim
    for name in ("deno", "node"):
        p = _find_tool(name)
        if p:
            return name, p
    return None, None


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = name.strip(". ")
    return name[:200] if name else "audio"


def get_audio_duration(filepath):
    """Süreyi ffprobe olmadan, ffmpeg çıktısından okur (pakette yalnız ffmpeg var)."""
    try:
        result = subprocess.run([get_ffmpeg_bin(), "-hide_banner", "-i", filepath],
                                capture_output=True, text=True, timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", result.stderr)
        if m:
            h, mi, sec = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(sec)
    except Exception:
        pass
    return 0


def detect_silence(filepath, silence_thresh=-38, min_silence=1.0):
    try:
        cmd = [
            get_ffmpeg_bin(), "-hide_banner", "-i", filepath,
            "-af", f"silencedetect=noise={silence_thresh}dB:d={min_silence}",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        starts, ends = [], []
        for line in result.stderr.splitlines():
            m = re.search(r"silence_start:\s*([\d.]+)", line)
            if m:
                starts.append(float(m.group(1)))
            m = re.search(r"silence_end:\s*([\d.]+)", line)
            if m:
                ends.append(float(m.group(1)))

        boundaries = []
        for s in starts:
            matching_ends = [e for e in ends if s < e < s + 10]
            boundaries.append((s + matching_ends[0]) / 2.0 if matching_ends else s)
        return boundaries
    except Exception:
        return []


AUDIO_ENCODERS = {
    "mp3": ["-codec:a", "libmp3lame"],
    "m4a": ["-codec:a", "aac"],
    "flac": ["-codec:a", "flac"],
    "wav": ["-codec:a", "pcm_s16le"],
}


def split_audio_file(filepath, chapters, output_dir, title_prefix, codec="mp3", bitrate="320k"):
    ffmpeg_bin = get_ffmpeg_bin()
    total_duration = get_audio_duration(filepath)
    results = []
    ext = os.path.splitext(filepath)[1].lstrip(".").lower() or codec
    enc = AUDIO_ENCODERS.get(ext, ["-codec:a", "copy"])
    lossy = ext in ("mp3", "m4a")

    for i, ch in enumerate(chapters):
        start = ch["start"]
        end = ch["end"]
        track_title = ch.get("title") or f"Parça {i+1:02d}"
        safe_name = sanitize_filename(f"{i+1:02d} - {track_title}")
        out_path = os.path.join(output_dir, f"{safe_name}.{ext}")

        if i == len(chapters) - 1 and total_duration > 0:
            end = total_duration

        duration = end - start
        if duration < 0.5:
            continue

        cmd = [ffmpeg_bin, "-y", "-hide_banner", "-ss", f"{start:.3f}", "-i", filepath, "-t", f"{duration:.3f}", "-vn"]
        cmd += enc
        if lossy:
            cmd += ["-b:a", bitrate]
        cmd += [
            "-ar", "44100", "-ac", "2", "-threads", "0",
            "-map_metadata", "-1",
            "-metadata", f"title={track_title}",
            "-metadata", f"album={title_prefix}",
            "-metadata", f"track={i+1}/{len(chapters)}",
            "-avoid_negative_ts", "make_zero",
            out_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=600)
            if os.path.isfile(out_path):
                actual_dur = get_audio_duration(out_path)
                size_mb = os.path.getsize(out_path) / (1024 * 1024)
                results.append((track_title, out_path, size_mb, actual_dur))
        except Exception:
            pass

    return results


def merge_segments(segments, duration=0):
    """[(başlangıç, bitiş)] aralıklarını sıralar, çakışanları birleştirir."""
    out = []
    for a, b in sorted((float(a), float(b)) for a, b in segments):
        if duration:
            b = min(b, duration)
        if b - a < 0.2:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def shift_chapters(chapters, cuts):
    """Kesilen aralıklara göre bölüm zamanlarını kaydırır (parçalara bölme için)."""
    def removed_before(t):
        return sum(max(0.0, min(b, t) - a) for a, b in cuts if a < t)
    out = []
    for ch in chapters:
        s0 = ch["start"] - removed_before(ch["start"])
        e0 = ch["end"] - removed_before(ch["end"])
        if e0 - s0 > 1:
            out.append({**ch, "start": s0, "end": e0})
    return out


def rewrite_audio(filepath, bitrate="320", cuts=None, loudnorm=False):
    """Tek ffmpeg geçişinde SponsorBlock aralıklarını keser ve/veya ses seviyesini eşitler (-14 LUFS).
    Kapak ve etiketler korunur; hata olursa dosyaya dokunmaz."""
    root, dot_ext = os.path.splitext(filepath)
    ext = dot_ext.lstrip(".").lower()
    if ext not in AUDIO_ENCODERS or not (cuts or loudnorm):
        return False
    filters = []
    if cuts:
        cond = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cuts)
        filters += [f"aselect='not({cond})'", "asetpts=N/SR/TB"]
    if loudnorm:
        filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    tmp = f"{root}.tirtil-tmp{dot_ext}"
    cmd = [get_ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", filepath,
           "-map", "0:a:0", "-map", "0:v?", "-c:v", "copy", "-map_metadata", "0",
           "-af", ",".join(filters), "-ar", "44100"]
    cmd += AUDIO_ENCODERS[ext]
    if ext in ("mp3", "m4a"):
        cmd += ["-b:a", f"{bitrate}k"]
    if ext == "mp3":
        cmd += ["-id3v2_version", "3"]
    cmd.append(tmp)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            os.replace(tmp, filepath)
            return True
        write_persistent_log(f"ffmpeg yeniden yazma hatası: {r.stderr[-500:]}")
    except Exception:
        write_persistent_log(traceback.format_exc())
    try:
        os.remove(tmp)
    except Exception:
        pass
    return False


SPONSOR_CATEGORIES = ["sponsor", "selfpromo", "interaction", "intro", "outro", "music_offtopic"]


def clear_ytdlp_cache():
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            ydl.cache.remove()
        return True
    except Exception:
        return False


_LIST_RE = re.compile(r"[?&]list=([A-Za-z0-9_-]+)")


def playlist_id(url):
    """YouTube çalma listesi kimliği. Otomatik Mix/radyo listeleri (RD...) sonsuz ve kişiye özel
    olduğu için genişletilmez; o linkler tek video olarak kalır."""
    if "youtu" not in (url or ""):
        return None
    m = _LIST_RE.search(url)
    if not m or m.group(1).startswith("RD"):
        return None
    return m.group(1)


def expand_playlist(url):
    """Çalma listesini video linklerine açar. Dönüş: (başlık, [linkler])."""
    pid = playlist_id(url)
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True,
            "socket_timeout": 30, "extractor_retries": 3}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/playlist?list={pid}", download=False)
    links = []
    for e in info.get("entries") or []:
        if not e:
            continue
        vid = e.get("id")
        link = f"https://www.youtube.com/watch?v={vid}" if vid else e.get("url")
        if link and link not in links:
            links.append(link)
    return info.get("title") or pid, links


# --- Müzik servisleri ------------------------------------------------------
# Spotify sesi DRM'li, doğrudan indirilemez. Parça bilgisi (sanatçı, ad, süre, kapak) Spotify'ın
# herkese açık embed sayfasından alınır, Deezer'ın açık API'siyle ISRC/yıl/parça no tamamlanır,
# aynı kayıt YouTube Music'te bulunup oradan indirilir. Şarkı sözleri LRCLIB'den gelir.

_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
_SPOTIFY_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[\w-]+/)?(?:embed/)?|spotify:)"
    r"(track|album|playlist|artist|episode|show)[/:]([A-Za-z0-9]{22})")
SPOTIFY_TRACKS = {}  # parça id -> bilgi (liste açılırken öğrenilenler; tekrar istek atmamak için)
_meta_lock = threading.Lock()
_DEEZER_ALBUM = {}  # albüm id -> {artist, label}
# spotDL FORBIDDEN_WORDS (+ birkaç ek): şarkının kendi adında yoksa sonucu cezalandırır
_FORBIDDEN_WORDS = ("bassboosted", "remix", "remastered", "remaster", "reverb", "bassboost", "live", "acoustic",
                    "8daudio", "concert", "acapella", "slowed", "instrumental", "cover", "karaoke", "nightcore",
                    "spedup", "1hour", "reaction")
_ARTIST_JOIN_WORDS = ("feat", "ft", "featuring", "with", "mit", "x", "and", "und", "vs", "con", "ve")
# YouTube Music arama filtreleri, yazım düzeltmesi kapalı (ytmusicapi get_search_params)
_YTM_PARAMS = {"songs": "EgWKAQIIAWoMEA4QChADEAQQCRAF", "videos": "EgWKAQIQAWoMEA4QChADEAQQCRAF"}


def _http(url, data=None, headers=None, timeout=20):
    """yt-dlp'nin ağ katmanı: paketli uygulamada sertifika/proxy ayarları onunla zaten çalışıyor."""
    h = {"User-Agent": _BROWSER_UA}
    h.update(headers or {})
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "socket_timeout": timeout}) as ydl:
        return ydl.urlopen(yt_dlp.networking.Request(url, data=data, headers=h)).read().decode("utf-8", "replace")


def _http_json(url, query=None, **kw):
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    return json.loads(_http(url, **kw))


def _norm(s):
    return re.sub(r"[^\w]+", " ", (s or "").lower()).strip()


def _core_title(title):
    """"(feat. X)", "[Remastered]", " - Radio Edit" gibi ekleri atar."""
    return re.sub(r"\s*[(\[].*?[)\]]|\s+-\s+.*$", "", title or "").strip() or (title or "")


def _split_artists(text):
    return [a.strip() for a in re.split(r",\s*|\s+&\s+", (text or "").replace("\xa0", " ")) if a.strip()]


def _parse_duration(text):
    parts = [int(p) for p in re.findall(r"\d+", text or "")]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


# Spotify ------------------------------------------------------------------

def spotify_ref(url):
    """Spotify linki ise (tür, id), değilse None."""
    m = _SPOTIFY_RE.search(url or "")
    return (m.group(1), m.group(2)) if m else None


def spotify_track_url(tid):
    return f"https://open.spotify.com/track/{tid}"


def _spotify_entity(kind, sid):
    html = _http(f"https://open.spotify.com/embed/{kind}/{sid}")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise Exception("Spotify sayfası okunamadı (link özel ya da kaldırılmış olabilir)")
    entity = (((json.loads(m.group(1)).get("props") or {}).get("pageProps") or {})
              .get("state") or {}).get("data", {}).get("entity")
    if not entity:
        raise Exception("Spotify içeriği bulunamadı (link özel ya da kaldırılmış olabilir)")
    return entity


def _spotify_cover(entity):
    # Albüm/listede coverArt.sources, parçada visualIdentity.image
    srcs = [(s.get("width") or 0, s["url"]) for s in ((entity.get("coverArt") or {}).get("sources") or []) if s.get("url")]
    srcs += [(s.get("maxWidth") or 0, s["url"]) for s in ((entity.get("visualIdentity") or {}).get("image") or [])
             if s.get("url")]
    return max(srcs)[1] if srcs else ""


def _spotify_date(entity):
    iso = ((entity.get("releaseDate") or {}).get("isoString") or "")[:10]
    return iso if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso) else ""


def spotify_track_meta(tid):
    """Parça bilgisi: {title, artists, duration, album, album_artist, cover, date, track_number}.
    Liste açılırken öğrenilen eksikse (kapak, tam sanatçı listesi) parçanın kendi sayfasıyla tamamlanır."""
    with _meta_lock:
        meta = dict(SPOTIFY_TRACKS.get(tid) or {})
    if meta.get("cover") and meta.get("complete"):
        return meta
    if spotify_api_enabled():
        try:
            fresh = _api_track_meta(_spotify_api(f"tracks/{tid}"))
            fresh.update({k: v for k, v in meta.items() if v and k in ("album", "album_artist", "track_number")})
            with _meta_lock:
                SPOTIFY_TRACKS[tid] = fresh
            return dict(fresh)
        except Exception as err:
            _spotify_api_disable(err)
    e = _spotify_entity("track", tid)
    meta.update({
        "title": e.get("title") or e.get("name") or meta.get("title") or "",
        "artists": [a["name"] for a in e.get("artists") or [] if a.get("name")] or meta.get("artists") or [],
        "duration": (e.get("duration") or 0) / 1000.0 or meta.get("duration") or 0,
        "cover": meta.get("cover") or _spotify_cover(e),
        "date": meta.get("date") or _spotify_date(e),
        "explicit": e.get("isExplicit") if e.get("isExplicit") is not None else meta.get("explicit"),
        "complete": True,
    })
    with _meta_lock:
        SPOTIFY_TRACKS[tid] = meta
    return dict(meta)


def expand_spotify(kind, sid):
    """Spotify albüm/çalma listesi/sanatçı linkini parça linklerine açar.
    Dönüş: (başlık, [linkler], tam_liste_mi). Tam değilse (embed 100 sınırı, sanatçı) senkron silme yapılmaz."""
    if spotify_api_enabled():
        try:
            title, items, complete = spotify_api_expand(kind, sid)
            links = []
            with _meta_lock:
                for tid, meta in items:
                    SPOTIFY_TRACKS[tid] = meta
                    if spotify_track_url(tid) not in links:
                        links.append(spotify_track_url(tid))
            return title, links, complete
        except Exception as err:
            _spotify_api_disable(err)
    e = _spotify_entity(kind, sid)
    name = e.get("name") or e.get("title") or sid
    is_album = kind == "album"
    album_artist = (e.get("subtitle") or "").replace("\xa0", " ") if is_album else ""
    if is_album:
        title = f"{album_artist} - {name}" if album_artist else name
    elif kind == "artist":
        title = f"{name} - Popüler"
    else:
        title = name
    cover = _spotify_cover(e) if is_album else ""
    date = _spotify_date(e) if is_album else ""
    links = []
    for pos, t in enumerate(e.get("trackList") or [], 1):
        m = re.match(r"spotify:track:([A-Za-z0-9]{22})$", t.get("uri") or "")
        if not m or t.get("isPlayable") is False:
            continue
        tid = m.group(1)
        with _meta_lock:
            SPOTIFY_TRACKS.setdefault(tid, {
                "title": t.get("title") or "",
                "artists": _split_artists(t.get("subtitle")) or ([name] if kind == "artist" else []),
                "duration": (t.get("duration") or 0) / 1000.0,
                "album": name if is_album else "",
                "album_artist": album_artist,
                "cover": cover,
                "date": date,
                "track_number": pos if is_album else 0,
                "explicit": t.get("isExplicit"),
            })
        link = spotify_track_url(tid)
        if link not in links:
            links.append(link)
    capped = len(e.get("trackList") or []) >= 100
    if capped:
        log(f"Spotify yalnızca ilk 100 parçayı paylaşıyor: {title} listesinin ilk 100 parçası alındı. "
            "Tamamı için Gelişmiş ayarlara Spotify API anahtarı gir.", "warn")
    return title, links, not capped and kind != "artist"


# Spotify Web API (isteğe bağlı) ------------------------------------------------
# Kullanıcı kendi Spotify geliştirici anahtarını (developer.spotify.com) girerse listeler 100 parça sınırı
# olmadan, ISRC ve parça numaralarıyla birlikte gelir. Hata olursa embed sayfasına dönülür.

_SPOTIFY_API = {"token": None, "exp": 0.0, "disabled": False}
_spotify_api_lock = threading.Lock()


def spotify_api_enabled():
    return bool(os.environ.get("ATI_SPOTIFY_ID") and os.environ.get("ATI_SPOTIFY_SECRET")) \
        and not _SPOTIFY_API["disabled"]


def _spotify_token():
    with _spotify_api_lock:
        if _SPOTIFY_API["token"] and time.time() < _SPOTIFY_API["exp"] - 60:
            return _SPOTIFY_API["token"]
        cred = base64.b64encode(f"{os.environ['ATI_SPOTIFY_ID']}:{os.environ['ATI_SPOTIFY_SECRET']}".encode()).decode()
        d = json.loads(_http("https://accounts.spotify.com/api/token", data=b"grant_type=client_credentials",
                             headers={"Authorization": f"Basic {cred}",
                                      "Content-Type": "application/x-www-form-urlencoded"}))
        _SPOTIFY_API["token"] = d["access_token"]
        _SPOTIFY_API["exp"] = time.time() + float(d.get("expires_in") or 3600)
        return _SPOTIFY_API["token"]


def _spotify_api(path, query=None):
    url = path if path.startswith("http") else f"https://api.spotify.com/v1/{path}"
    return _http_json(url, query, headers={"Authorization": f"Bearer {_spotify_token()}"})


def _spotify_api_disable(err):
    if not _SPOTIFY_API["disabled"]:
        _SPOTIFY_API["disabled"] = True
        write_persistent_log(traceback.format_exc())
        log(f"Spotify API kullanılamadı ({str(err)[:80]}). Herkese açık sayfadan devam ediliyor.", "warn")


def _api_track_meta(t, album=None):
    album = album or t.get("album") or {}
    images = sorted(album.get("images") or [], key=lambda i: i.get("width") or 0)
    date = album.get("release_date") or ""
    return {
        "title": t.get("name") or "",
        "artists": [a["name"] for a in t.get("artists") or [] if a.get("name")],
        "duration": (t.get("duration_ms") or 0) / 1000.0,
        "album": album.get("name") or "",
        "album_artist": ", ".join(a["name"] for a in album.get("artists") or [] if a.get("name")),
        "cover": images[-1]["url"] if images else "",
        "date": date if re.fullmatch(r"\d{4}(-\d{2}){0,2}", date) else "",
        "track_number": t.get("track_number") or 0,
        "disc_number": t.get("disc_number") or 0,
        "explicit": t.get("explicit"),
        "isrc": (t.get("external_ids") or {}).get("isrc") or "",
        "label": album.get("label") or "",
        "complete": True,
    }


def _paged(first):
    page = first
    while page:
        yield from page.get("items") or []
        page = _spotify_api(page["next"]) if page.get("next") else None


def spotify_api_expand(kind, sid):
    """Dönüş: (başlık, [(parça id, meta)], tam_liste_mi)."""
    out = []
    if kind == "album":
        a = _spotify_api(f"albums/{sid}")
        for t in _paged(a.get("tracks") or {}):
            if t and t.get("id"):
                out.append((t["id"], _api_track_meta(t, a)))
        artist = ", ".join(x["name"] for x in a.get("artists") or [] if x.get("name"))
        return (f"{artist} - {a.get('name')}" if artist else a.get("name") or sid), out, True
    if kind == "playlist":
        p = _spotify_api(f"playlists/{sid}", {"fields": "name"})
        first = _spotify_api(f"playlists/{sid}/tracks", {"limit": 100})
        for it in _paged(first):
            t = (it or {}).get("track") or {}
            if t.get("id") and t.get("type", "track") == "track" and not t.get("is_local"):
                out.append((t["id"], _api_track_meta(t)))
        return p.get("name") or sid, out, True
    if kind == "artist":
        a = _spotify_api(f"artists/{sid}")
        for t in _spotify_api(f"artists/{sid}/top-tracks", {"market": "US"}).get("tracks") or []:
            if t.get("id"):
                out.append((t["id"], _api_track_meta(t)))
        return f"{a.get('name') or sid} - Popüler", out, False
    raise Exception(f"Desteklenmeyen Spotify türü: {kind}")


# Deezer: ISRC, yayın tarihi, parça/disk numarası, albüm sanatçısı ------------

def deezer_enrich(meta):
    """Deezer'ın açık arama API'siyle meta'yı tamamlar (yerinde). Bulamazsa sessizce geçer."""
    try:
        artist = (meta.get("artists") or [""])[0]
        core = _core_title(meta["title"])
        res = _http_json("https://api.deezer.com/search", {"q": f"{artist} {core}", "limit": 10})
        want = meta.get("duration") or 0
        core_n, artist_n = _norm(core), _norm(artist)
        best, best_diff = None, None
        for t in res.get("data") or []:
            if core_n not in _norm(t.get("title")) or (artist_n and artist_n not in _norm((t.get("artist") or {}).get("name"))):
                continue
            diff = abs((t.get("duration") or 0) - want) if want else 0
            if diff <= 4 and (best_diff is None or diff < best_diff):
                best, best_diff = t, diff
        if not best:
            return meta
        meta["isrc"] = best.get("isrc") or meta.get("isrc", "")
        detail = _http_json(f"https://api.deezer.com/track/{best['id']}")
        if detail.get("release_date") and not meta.get("date"):
            meta["date"] = detail["release_date"]
        album = detail.get("album") or best.get("album") or {}
        # Spotify albümü biliniyorsa ve Deezer'daki başka bir albümse (derleme, deluxe) numaraları alma
        same_album = not meta.get("album") or _norm(album.get("title")) == _norm(meta["album"])
        if same_album:
            meta["album"] = meta.get("album") or album.get("title") or ""
            if detail.get("track_position"):
                meta["track_number"] = detail["track_position"]
            if detail.get("disk_number"):
                meta["disc_number"] = detail["disk_number"]
            if album.get("id"):
                aid = album["id"]
                with _meta_lock:
                    cached = _DEEZER_ALBUM.get(aid)
                if cached is None:
                    d = _http_json(f"https://api.deezer.com/album/{aid}")
                    cached = {"artist": (d.get("artist") or {}).get("name") or "", "label": d.get("label") or ""}
                    with _meta_lock:
                        _DEEZER_ALBUM[aid] = cached
                meta["album_artist"] = meta.get("album_artist") or cached["artist"]
                meta["label"] = meta.get("label") or cached["label"]
    except Exception:
        write_persistent_log(traceback.format_exc())
    return meta


# YouTube Music arama --------------------------------------------------------

def ytmusic_search(query, kind="songs"):
    """YouTube Music araması: [{id, title, artists, album, duration, explicit, verified}].
    kind="songs": resmi stüdyo kayıtları (YouTube'un otomatik "Topic" sesleri), kind="videos": klipler ve yüklemeler.
    Yazım düzeltmesi kapalı: YouTube Music sorguyu "düzeltip" başka şarkı getirmesin (spotDL: ignore_spelling)."""
    body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": "1.20241111.01.00", "hl": "en"}},
            "query": query, "params": _YTM_PARAMS[kind]}
    data = json.loads(_http("https://music.youtube.com/youtubei/v1/search?prettyPrint=false",
                            data=json.dumps(body).encode(),
                            headers={"Content-Type": "application/json", "Origin": "https://music.youtube.com"}))
    out = []

    def walk(o):
        if isinstance(o, dict):
            item = o.get("musicResponsiveListItemRenderer")
            if item:
                yield item
            else:
                for v in o.values():
                    yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)

    for item in walk(data):
        vid = (item.get("playlistItemData") or {}).get("videoId")
        cols = ["".join(r.get("text", "") for r in ((c.get("musicResponsiveListItemFlexColumnRenderer") or {})
                                                    .get("text") or {}).get("runs") or [])
                for c in item.get("flexColumns") or []]
        if not vid or len(cols) < 2:
            continue
        # Şarkı: "Sanatçı • Albüm • 3:50"  Video: "Kanal • 1.2M views • 3:50"
        parts = [p.strip() for p in cols[1].split("•")]
        dur = _parse_duration(parts[-1]) if parts and re.fullmatch(r"[\d:]+", parts[-1]) else 0
        middle = [p for p in parts[1:-1] if not re.search(r"\b(views|plays)\b", p, re.I)]
        badges = [((b.get("musicInlineBadgeRenderer") or {}).get("icon") or {}).get("iconType")
                  for b in item.get("badges") or []]
        out.append({"id": vid, "title": cols[0], "artists": _split_artists(parts[0]) if parts else [],
                    "album": middle[0] if kind == "songs" and middle else "", "duration": dur,
                    "explicit": "MUSIC_EXPLICIT_BADGE" in badges, "verified": kind == "songs"})
    return out


def _slug(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^\w]+", " ", s).strip()


def _ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() * 100 if a and b else 0.0


def _strip_artists(text, artists):
    """Sonuç başlığından sanatçı adlarını ve "feat/ft/x/&" gibi bağlaçları çıkarır."""
    out = f" {_slug(text)} "
    for a in artists:
        a = _slug(a)
        if a:
            out = out.replace(f" {a} ", " ")
    for w in _ARTIST_JOIN_WORDS:
        out = out.replace(f" {w} ", " ")
    return re.sub(r"\s+", " ", out).strip()


def match_score(meta, r):
    """spotDL'in eşleşme kurallarının sadeleştirilmiş hali (spotdl/utils/matching.py, order_results).
    0-100 arası puan; None = aday elendi."""
    song_name = _slug(meta["title"])
    core_name = _slug(_core_title(meta["title"]))
    artists = meta.get("artists") or []
    r_title = _slug(r["title"])
    r_artists = [_slug(a) for a in r.get("artists") or []]
    r_artist_text = " ".join(r_artists)

    # Ortak kelime yoksa hiç uğraşma
    if not any(w in r_title.replace(" ", "") for w in core_name.split() if w):
        return None

    # Sanatçı: ana sanatçı başlıkta/sanatçılarda geçiyor mu, geçmiyorsa ne kadar benziyor
    def artist_hit(a):
        a = _slug(a)
        if not a:
            return 0.0
        if f" {a} " in f" {r_title} " or f" {a} " in f" {r_artist_text} ":
            return 100.0
        return max([_ratio(a, x) for x in r_artists] + [0.0])

    main = artist_hit(artists[0]) if artists else 100.0
    if len(artists) > 1 and main < 80:
        others = sum(artist_hit(a) for a in artists[1:]) / (len(artists) - 1)
        artist_match = (main + others) / 2
    else:
        artist_match = main  # YouTube Music çoğu zaman yalnız ana sanatçıyı yazar

    # Ad: sanatçılar ve bağlaçlar atıldıktan sonra benzerlik; tüm kelimeler geçiyorsa yüksek say
    cleaned = _strip_artists(r["title"], artists + (r.get("artists") or []))
    name_match = max(_ratio(song_name, cleaned), _ratio(core_name, _slug(_core_title(cleaned))))
    if core_name and set(core_name.split()) <= set(r_title.split()):
        name_match = max(name_match, 90.0)
    flat_song = song_name.replace(" ", "")
    for w in _FORBIDDEN_WORDS:
        if w in r_title.replace(" ", "") and w not in flat_song:
            name_match -= 15

    want = meta.get("duration") or 0
    time_match = 100 * math.exp(-0.1 * abs(want - r["duration"])) if want and r.get("duration") else 50.0

    if name_match <= 60 or artist_match < 70 or time_match < 25:
        return None
    avg = (artist_match + name_match) / 2
    if time_match < 50 and avg < 75:
        return None

    if r.get("verified") and not r.get("isrc_search") and r.get("album") and meta.get("album"):
        album_match = _ratio(_slug(meta["album"]), _slug(r["album"]))
        if album_match <= 80:
            avg = (avg + album_match) / 2
    if r.get("isrc_search") or avg <= 85:
        avg = (avg + time_match) / 2
    if meta.get("explicit") is not None and r.get("verified") and bool(r.get("explicit")) != bool(meta["explicit"]):
        avg -= 5
    return min(avg, 100.0)


def _best(meta, results, skip):
    scored = []
    for r in results:
        if r["id"] in skip:
            continue
        s = match_score(meta, r)
        if s is not None:
            scored.append((s, r))
    return max(scored, key=lambda x: x[0]) if scored else (None, None)


def _yt_result(r, source):
    who = ", ".join(r.get("artists") or [])
    return {"id": r["id"], "title": f"{who} - {r['title']}" if who and who.lower() not in r["title"].lower() else r["title"],
            "source": source, "ytmusic": source.startswith("YouTube Music")}


def find_youtube_match(meta):
    """Parçanın YouTube karşılığı (spotDL'in sırası): ISRC ile YouTube Music, ad ile YouTube Music şarkılar,
    YouTube Music videolar, normal YouTube. Dönüş: {id, title, source, ytmusic}."""
    skip = set(meta.get("_skip_ids") or ())  # daha önce açılamayan (yaş kısıtlı vb.) videolar
    artist = ", ".join((meta.get("artists") or [])[:2])
    query = f"{artist} - {meta['title']}".strip(" -")
    isrc_ids = set()

    if meta.get("isrc"):
        try:
            hits = [dict(h, isrc_search=True) for h in ytmusic_search(meta["isrc"])[:5]]
            isrc_ids = {h["id"] for h in hits}
            if len(hits) == 1 and hits[0]["id"] not in skip:
                return _yt_result(hits[0], "YouTube Music (ISRC)")  # tek doğrulanmış sonuç: neredeyse kesin
            s, r = _best(meta, hits, skip)
            if r and s > 80:
                return _yt_result(r, "YouTube Music (ISRC)")
        except Exception:
            write_persistent_log(traceback.format_exc())

    pool = []
    for kind in ("songs", "videos"):
        try:
            results = ytmusic_search(query, kind)
        except Exception:
            write_persistent_log(traceback.format_exc())
            continue
        for r in results:
            if r["id"] in isrc_ids and r["id"] not in skip:
                return _yt_result(r, "YouTube Music (ISRC)")
        s, r = _best(meta, results, skip)
        if r and s >= 80 and r["verified"]:
            return _yt_result(r, "YouTube Music")
        if r:
            pool.append((s, r))
    if pool:
        # Eşit sayılabilecek puanlarda stüdyo kaydı (şarkı) klipten iyidir: intro/outro yok
        s, r = max(pool, key=lambda x: x[0] + (5 if x[1]["verified"] else 0))
        return _yt_result(r, "YouTube Music" if r["verified"] else "YouTube Music (video)")

    # Son çare: normal YouTube araması (kanal adı sanatçı yerine geçer)
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True,
                           "socket_timeout": 30, "extractor_retries": 3}) as ydl:
        info = ydl.extract_info(f"ytsearch10:{query}", download=False)
    results = [{"id": e["id"], "title": e.get("title") or "", "duration": e.get("duration") or 0,
                "artists": [re.sub(r"\s*-\s*topic$", "", e.get("channel") or e.get("uploader") or "", flags=re.I)]}
               for e in info.get("entries") or [] if e and e.get("id")]
    s, r = _best(meta, results, skip)
    if r:
        return {"id": r["id"], "title": r["title"], "source": "YouTube", "ytmusic": False}
    # Kurallara uyan yoksa yalnız süresi tutan ilk sonuç (yanlış şarkı indirmektense hata vermek daha iyi)
    want = meta.get("duration") or 0
    for r in results:
        if r["id"] not in skip and want and r["duration"] and abs(r["duration"] - want) <= 15:
            return {"id": r["id"], "title": r["title"], "source": "YouTube (zayıf eşleşme)", "ytmusic": False}
    raise Exception(f"YouTube'da güvenilir eşleşme bulunamadı: {query}")


def spotify_display(meta):
    artist = ", ".join(meta.get("artists") or [])
    return f"{artist} - {meta['title']}" if artist else meta["title"]


def apply_spotify_meta(info, meta):
    """YouTube bilgisini Spotify'ınkiyle değiştirir: dosya adı "Sanatçı - Parça", etiketler ve kare kapak."""
    info["title"] = spotify_display(meta)  # dosya adı şablonu %(title)s
    info["track"] = meta["title"]          # FFmpegMetadata başlık etiketi için önce "track"a bakar
    info["description"] = ""               # YouTube video açıklaması müzik etiketine girmesin
    if meta.get("artists"):
        info["artist"] = ", ".join(meta["artists"])
        info["artists"] = list(meta["artists"])
    for key in ("album", "album_artist", "track_number", "disc_number"):
        if meta.get(key):
            info[key] = meta[key]
    if meta.get("date"):
        info["upload_date"] = meta["date"].replace("-", "")  # FFmpegMetadata "date" etiketini buradan yazar
    if meta.get("cover"):
        info["thumbnails"] = [{"url": meta["cover"], "id": "spotify"}]
        info["thumbnail"] = meta["cover"]


# Şarkı sözleri (LRCLIB) -------------------------------------------------------

def fetch_lyrics(artist, title, album="", duration=0):
    """LRCLIB'den (synced, plain) döner; bulunamazsa ("", "")."""
    headers = {"User-Agent": "Tirtil-Downloader (macOS)"}
    try:
        q = {"artist_name": artist, "track_name": title}
        if album:
            q["album_name"] = album
        if duration:
            q["duration"] = int(round(duration))
        try:
            d = _http_json("https://lrclib.net/api/get", q, headers=headers)
            if d.get("syncedLyrics") or d.get("plainLyrics"):
                return d.get("syncedLyrics") or "", d.get("plainLyrics") or ""
        except Exception:
            pass  # 404: tam eşleşme yok, aramaya düş
        res = _http_json("https://lrclib.net/api/search", {"q": f"{artist} {_core_title(title)}"}, headers=headers)
        core_n, artist_n = _norm(_core_title(title)), _norm(artist.split(",")[0])
        for d in res or []:
            if core_n not in _norm(d.get("trackName")) or (artist_n and artist_n not in _norm(d.get("artistName"))):
                continue
            if duration and d.get("duration") and abs(d["duration"] - duration) > 4:
                continue
            if d.get("instrumental"):
                return "", ""
            if d.get("syncedLyrics") or d.get("plainLyrics"):
                return d.get("syncedLyrics") or "", d.get("plainLyrics") or ""
    except Exception:
        write_persistent_log(traceback.format_exc())
    return "", ""


def write_lrc(filepath, synced):
    """Zamanlı sözleri dosyanın yanına .lrc olarak yazar (çoğu oynatıcı aynı adlı .lrc'yi okur)."""
    try:
        with open(os.path.splitext(filepath)[0] + ".lrc", "w", encoding="utf-8") as f:
            f.write(synced.strip() + "\n")
        return True
    except Exception:
        write_persistent_log(traceback.format_exc())
        return False


def embed_lyrics(filepath, synced, plain):
    """mutagen yoksa yedek yol: düz sözleri ffmpeg ile gömer."""
    root, dot_ext = os.path.splitext(filepath)
    ext = dot_ext.lstrip(".").lower()
    text = plain or re.sub(r"^\[[\d:.]+\]\s?", "", synced or "", flags=re.M)
    if not text.strip() or ext not in ("mp3", "m4a", "flac"):
        return False
    tmp = f"{root}.tirtil-tmp{dot_ext}"
    cmd = [get_ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", filepath,
           "-map", "0", "-c", "copy", "-map_metadata", "0", "-metadata", f"lyrics={text.strip()}"]
    if ext == "mp3":
        cmd += ["-id3v2_version", "3"]
    cmd.append(tmp)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            os.replace(tmp, filepath)
            return True
        write_persistent_log(f"ffmpeg söz gömme hatası: {r.stderr[-500:]}")
    except Exception:
        write_persistent_log(traceback.format_exc())
    try:
        os.remove(tmp)
    except Exception:
        pass
    return False


def _parse_lrc(synced):
    """"[01:02.34] metin" satırlarını [(metin, milisaniye)] listesine çevirir."""
    out = []
    for line in (synced or "").splitlines():
        stamps = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", line)
        text = re.sub(r"\[[\d:.]+\]", "", line).strip()
        for mm, ss in stamps:
            out.append((text, int((int(mm) * 60 + float(ss)) * 1000)))
    return sorted(out, key=lambda x: x[1])


def write_tags(filepath, meta=None, synced="", plain=""):
    """mutagen ile ek etiketler (spotDL utils/metadata.py): sözler (MP3'te zamanlı SYLT dahil), ISRC, kaynak linki,
    plak şirketi, explicit işareti. mutagen yoksa/hata olursa False döner (çağıran ffmpeg yoluna düşer)."""
    try:
        import mutagen
        from mutagen.id3 import ID3, ID3NoHeaderError, USLT, SYLT, TSRC, WOAS, TPUB, TXXX
        from mutagen.mp4 import MP4, MP4FreeForm
    except Exception:
        return False
    meta = meta or {}
    ext = os.path.splitext(filepath)[1].lstrip(".").lower()
    text = plain or "\n".join(t for t, _ in _parse_lrc(synced)) or ""
    try:
        if ext == "mp3":
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()
            if text:
                tags.delall("USLT")
                tags.add(USLT(encoding=3, lang="eng", desc="", text=text))
            if synced:
                tags.delall("SYLT")
                tags.add(SYLT(encoding=3, lang="eng", format=2, type=1, desc="", text=_parse_lrc(synced)))
            if meta.get("isrc"):
                tags.add(TSRC(encoding=3, text=meta["isrc"]))
            if meta.get("url"):
                tags.add(WOAS(url=meta["url"]))
            if meta.get("label"):
                tags.add(TPUB(encoding=3, text=meta["label"]))
            if meta.get("explicit") is not None:
                tags.add(TXXX(encoding=3, desc="ITUNESADVISORY", text="1" if meta["explicit"] else "2"))
            tags.save(filepath, v2_version=3)
        elif ext == "m4a":
            f = MP4(filepath)
            if text:
                f["\xa9lyr"] = text
            if meta.get("isrc"):
                f["----:com.apple.iTunes:ISRC"] = MP4FreeForm(meta["isrc"].encode())
            if meta.get("label"):
                f["----:com.apple.iTunes:LABEL"] = MP4FreeForm(meta["label"].encode())
            if meta.get("url"):
                f["----:com.apple.iTunes:SOURCE"] = MP4FreeForm(meta["url"].encode())
            if meta.get("explicit") is not None:
                f["rtng"] = [4 if meta["explicit"] else 2]  # iTunes: 4 = explicit, 2 = temiz
            if meta.get("date"):
                f["\xa9day"] = meta["date"]  # ffmpeg "20121116" yazar; Apple biçimi "2012-11-16"
            f.save()
        elif ext in ("flac", "opus", "ogg"):
            f = mutagen.File(filepath)
            if f is None:
                return False
            if f.tags is None:
                f.add_tags()
            if text:
                f["LYRICS"] = text
            if meta.get("isrc"):
                f["ISRC"] = meta["isrc"]
            if meta.get("label"):
                f["LABEL"] = meta["label"]
            if meta.get("url"):
                f["SOURCE"] = meta["url"]
            if meta.get("date"):
                f["DATE"] = meta["date"]
            f.save()
        else:
            return False
        return True
    except Exception:
        write_persistent_log(traceback.format_exc())
        return False


# Bandcamp / SoundCloud ---------------------------------------------------------

def media_list_kind(url):
    """Parçalara açılması gereken Bandcamp/SoundCloud liste linki ise servis adı, değilse None."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return None
    host = (p.hostname or "").lower()
    parts = [x for x in p.path.split("/") if x]
    if host.endswith("bandcamp.com"):
        if (parts and parts[0] == "album") or not parts or parts == ["music"]:
            return "bandcamp"
    if host in ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"):
        if len(parts) >= 3 and parts[1] == "sets":
            return "soundcloud"
        if len(parts) == 1 or (len(parts) == 2 and parts[1] in ("tracks", "albums", "sets", "popular-tracks")):
            return "soundcloud"
    return None


def expand_media_list(url):
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True,
            "socket_timeout": 30, "extractor_retries": 3}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    links = []
    for e in info.get("entries") or []:
        link = (e or {}).get("url") or (e or {}).get("webpage_url")
        if link and link.startswith("http") and link not in links:
            links.append(link)
    title = info.get("title") or url
    if info.get("uploader") and info["uploader"] not in title:
        title = f"{info['uploader']} - {title}"
    return title, links


def needs_expand(url, expand_playlists=True):
    """İndirmeden önce parçalara açılacak link mi? Spotify/Bandcamp/SoundCloud listeleri tek dosya olarak
    inemediği için her zaman açılır; YouTube listesi ayara bağlı (düz liste sayfası her zaman)."""
    sp = spotify_ref(url)
    if sp:
        return sp[0] in ("album", "playlist", "artist")
    if media_list_kind(url):
        return True
    return bool(playlist_id(url)) and (expand_playlists or "v=" not in url)


def expand_urls(urls):
    """Her link için {url, title, entries, error}. Liste olmayanlar olduğu gibi döner."""
    results = []
    for url in urls:
        if not needs_expand(url):
            results.append({"url": url, "entries": [url]})
            continue
        try:
            sp = spotify_ref(url)
            complete = False
            if sp:
                title, links, complete = expand_spotify(*sp)
            elif media_list_kind(url):
                title, links = expand_media_list(url)
            else:
                title, links = expand_playlist(url)
            if not links:
                raise Exception("Listede indirilebilir parça yok")
            results.append({"url": url, "title": title, "entries": links, "spotify_complete": bool(sp and complete)})
        except Exception as e:
            write_persistent_log(traceback.format_exc())
            results.append({"url": url, "entries": [url], "error": str(e)[:180]})
    return results


class BatchDownloader:
    def __init__(self, config):
        items = []
        for u in config.get("urls", []):
            if isinstance(u, str):
                items.append({"url": u.strip(), "folder": ""})
            elif isinstance(u, dict):
                items.append({"url": str(u.get("url") or "").strip(), "folder": str(u.get("folder") or "")})
        self.items = [i for i in items if i["url"]]
        self.download_folder = os.path.expanduser(config.get("download_folder") or os.path.join(HOME, "Downloads", "Tırtıl_Downloads"))
        self.format_choice = config.get("format", "mp3").lower()
        self.bitrate = str(config.get("bitrate", "320"))
        self.workers = int(config.get("workers", 3))
        self.split_enabled = bool(config.get("split", False))
        self.cookie_choice = (config.get("cookie_browser") or "none").strip().lower()
        self.cookie_browser = None
        self.cookie_profile = None
        self.delay_mode = config.get("delay_mode", "safe")
        self.expand_playlists = bool(config.get("expand_playlists", False))
        self.playlist_folders = bool(config.get("playlist_folders", True))
        self.embed_meta = bool(config.get("embed_meta", True))
        self.resolution = str(config.get("resolution") or "best")
        self.skip_downloaded = bool(config.get("skip_downloaded", False))
        self.archive_dir = config.get("archive_dir") or ""
        self.loudnorm = bool(config.get("loudnorm", False))
        self.sponsorblock = bool(config.get("sponsorblock", False))
        self.lyrics = bool(config.get("lyrics", False))
        self.playlist_m3u = bool(config.get("playlist_m3u", True))
        self.spotify_sync = bool(config.get("spotify_sync", False))
        self.outputs = {}         # sıra -> inen dosya (m3u için)
        self.synced_lists = {}    # klasör -> o Spotify listesinin güncel parça id'leri (yalnız tam listeler)
        self._sync_states = {}
        self.completed_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.total_count = len(self.items)
        self.cancel_flag = False
        self.lock = threading.Lock()

        os.makedirs(self.download_folder, exist_ok=True)

        best_cookie = find_best_browser_cookies(self.cookie_choice)
        if COOKIE_BLOCKED:
            names = ", ".join(b.capitalize() for b in COOKIE_BLOCKED)
            # Sadece bilgi: izin istemi yalnızca YouTube bot engeli gelirse gösterilir
            log(f"{names} cookie'lerine erişim yok (macOS izni). Cookie'siz devam ediliyor.", "info")
        if best_cookie:
            self.cookie_browser, self.cookie_profile, info_msg = best_cookie
            log(info_msg, "success")
        else:
            if self.cookie_choice not in ("none", ""):
                log("Tarayıcı cookie oturumu bulunamadı. Cookie'siz güvenli istemci modu kullanılıyor ✅", "info")
            self.cookie_browser = "none"

    def get_delay_seconds(self):
        return {
            "super_safe": random.uniform(4.0, 7.5),
            "safe": random.uniform(2.0, 4.2),
            "fast": random.uniform(1.0, 2.0),
        }.get(self.delay_mode, 0.0)

    # --- Spotify liste senkronu (spotDL "sync") ---------------------------------------
    # Liste klasöründe .tirtil-sync.json: Spotify parça id -> dosya adı. Bir sonraki indirmede bu parçalar YouTube'da
    # yeniden aranmadan atlanır; senkron açıksa listeden çıkan parçaların dosyaları Çöp'e taşınır.

    def _sync_file(self, folder):
        return os.path.join(self.item_dir(folder), ".tirtil-sync.json")

    def _sync_state(self, folder):
        with self.lock:
            st = self._sync_states.get(folder)
            if st is None:
                st = {"tracks": {}}
                try:
                    with open(self._sync_file(folder), encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded.get("tracks"), dict):
                        st = loaded
                except Exception:
                    pass
                self._sync_states[folder] = st
            return st

    def _sync_save(self, folder):
        with self.lock:
            st = self._sync_states.get(folder)
            if st is None:
                return
            try:
                tmp = self._sync_file(folder) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self._sync_file(folder))
            except Exception:
                write_persistent_log(traceback.format_exc())

    def _sync_known_file(self, folder, tid):
        """Bu Spotify parçası bu klasöre bu biçimde daha önce indiyse dosya yolu."""
        if not (folder and self.playlist_folders):
            return None
        name = self._sync_state(folder)["tracks"].get(tid)
        if not name:
            return None
        path = os.path.join(self.item_dir(folder), name)
        ext = os.path.splitext(name)[1].lstrip(".").lower()
        if os.path.isfile(path) and (self.format_choice == "original" or ext == self.format_choice):
            return path
        return None

    def _sync_record(self, folder, tid, path):
        if folder and self.playlist_folders and path and os.path.dirname(path) == self.item_dir(folder):
            self._sync_state(folder)["tracks"][tid] = os.path.basename(path)
            self._sync_save(folder)

    @staticmethod
    def _to_trash(path):
        trash = os.path.join(HOME, ".Trash")
        base, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(trash, base + ext)
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(trash, f"{base} {n}{ext}")
            n += 1
        shutil.move(path, dest)

    def sync_remove_missing(self):
        """Senkron açıkken: listeden çıkarılan parçaların dosyalarını (ve .lrc'lerini) Çöp'e taşır."""
        for folder, current in self.synced_lists.items():
            st = self._sync_state(folder)
            gone = [tid for tid in list(st["tracks"]) if tid not in current]
            for tid in gone:
                path = os.path.join(self.item_dir(folder), st["tracks"].pop(tid))
                for p in (path, os.path.splitext(path)[0] + ".lrc"):
                    if os.path.isfile(p):
                        try:
                            self._to_trash(p)
                            if p == path:
                                log(f"Senkron: listeden çıkarılmış, Çöp'e taşındı: {os.path.basename(p)}", "info")
                        except Exception:
                            write_persistent_log(traceback.format_exc())
            if gone:
                self._sync_save(folder)

    def write_m3u(self):
        """Her liste klasörüne inen parçaların sırasıyla <liste>.m3u8 yazar. Önceki listede olup bu sefer
        inmeyen (atlanan) ama hâlâ duran dosyalar korunur."""
        groups = {}
        for n, item in enumerate(self.items, 1):
            if item["folder"]:
                groups.setdefault(item["folder"], []).append(n)
        for folder, idxs in groups.items():
            d = self.item_dir(folder)
            m3u = os.path.join(d, sanitize_filename(folder) + ".m3u8")
            names = [os.path.basename(self.outputs[i]) for i in idxs
                     if self.outputs.get(i) and os.path.dirname(self.outputs[i]) == d and os.path.isfile(self.outputs[i])]
            try:
                with open(m3u, encoding="utf-8") as f:
                    old = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            except Exception:
                old = []
            names += [n for n in old if n not in names and os.path.isfile(os.path.join(d, n))]
            if not names:
                continue
            try:
                with open(m3u, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n" + "\n".join(names) + "\n")
            except Exception:
                write_persistent_log(traceback.format_exc())

    def item_dir(self, folder):
        if folder and self.playlist_folders:
            d = os.path.join(self.download_folder, sanitize_filename(folder))
            os.makedirs(d, exist_ok=True)
            return d
        return self.download_folder

    def archive_path(self):
        if not (self.skip_downloaded and self.archive_dir):
            return None
        os.makedirs(self.archive_dir, exist_ok=True)
        # Format başına ayrı arşiv: MP3 olarak inen bir video MP4 olarak yine inebilir
        return os.path.join(self.archive_dir, f"archive_{self.format_choice}.txt")

    def build_ydl_opts(self, folder=""):
        ffmpeg_bin = get_ffmpeg_bin()
        ffmpeg_dir = os.path.dirname(ffmpeg_bin) if os.path.isabs(ffmpeg_bin) else None

        opts = {
            "noplaylist": True,
            "no_overwrites": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "extractor_retries": 5,
            "retries": 10,
            "fragment_retries": 10,
            "file_access_retries": 5,
            "socket_timeout": 30,
            "outtmpl": os.path.join(self.item_dir(folder), "%(title)s.%(ext)s"),
        }
        archive = self.archive_path()
        if archive:
            opts["download_archive"] = archive

        rt_name, rt_path = get_node_bin()
        if rt_name:
            opts["js_runtimes"] = {rt_name: {"path": rt_path}}
            opts["remote_components"] = ["ejs:github"]

        if self.cookie_browser and self.cookie_browser != "none":
            opts["cookiesfrombrowser"] = (self.cookie_browser, self.cookie_profile, None, None)

        if self.format_choice == "mp4":
            opts.update({
                "format": self.video_format(),
                "merge_output_format": "mp4",
            })
        elif self.format_choice == "original":
            # Dönüştürmeden (spotDL --bitrate disable): kaynağın sesi olduğu gibi kaydedilir, kalite kaybı ve
            # şişme olmaz. Mac uyumluluğu için önce M4A (AAC); YouTube Premium cookie'si varsa 256 kbps (141) gelir.
            opts.update({
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}],
                "keepvideo": False,
            })
        else:
            pp_args = ["-ar", "44100", "-ac", "2", "-threads", "0"]
            if self.format_choice in ("mp3", "m4a"):
                pp_args = ["-b:a", f"{self.bitrate}k"] + pp_args
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.format_choice,
                    "preferredquality": self.bitrate,
                }],
                "postprocessor_args": {"extractaudio": pp_args},
                "keepvideo": False,
            })

        pps = opts.setdefault("postprocessors", [])
        if self.sponsorblock and self.format_choice != "mp4":
            # Yalnızca segmentleri alır; kesim indirmeden sonra rewrite_audio ile yapılır
            # (yt-dlp'nin ModifyChapters adımı pakette olmayan ffprobe'a ihtiyaç duyar)
            pps.insert(0, {"key": "SponsorBlock", "categories": SPONSOR_CATEGORIES, "when": "after_filter"})

        if self.embed_meta:
            # Kapak resmi + etiketler (başlık, sanatçı, tarih). WAV kapak desteklemez.
            pps.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": self.format_choice == "mp4"})
            if self.format_choice != "wav":
                opts["writethumbnail"] = True
                pps.insert(0, {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
                pps.append({"key": "EmbedThumbnail"})
                if self.format_choice != "mp4":
                    # Müzik uygulamaları kare kapak bekler: 16:9 küçük resmi ortadan kare kırp
                    opts.setdefault("postprocessor_args", {})["thumbnailsconvertor"] = [
                        "-vf", "crop=min(iw\\,ih):min(iw\\,ih)"]

        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir
        return opts

    def video_format(self):
        """H.264 (avc1) + AAC: her Mac'te ve oynatıcıda açılır. YouTube H.264'ü en fazla 1080p verir;
        1440p/4K yalnızca açıkça seçilirse VP9/AV1 olarak indirilir."""
        h = int(self.resolution) if self.resolution.isdigit() else 1080
        c = f"[height<={h}]"
        if h > 1080:
            return f"bestvideo{c}+bestaudio[ext=m4a]/bestvideo{c}+bestaudio/best{c}/best"
        return (f"bestvideo{c}[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo{c}[ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo{c}+bestaudio/best{c}/best")

    def progress_hook(self, d, idx, total):
        if self.cancel_flag:
            raise Exception("Kullanıcı tarafından iptal edildi")

        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            num_pct = (downloaded / total_bytes * 100.0) if total_bytes else 0.0
            spd = (d.get("_speed_str") or "").strip()
            eta = (d.get("_eta_str") or "").strip()
            spd = re.sub(r"\x1b\[[0-9;]*m", "", spd)
            eta = re.sub(r"\x1b\[[0-9;]*m", "", eta)

            overall = (self.completed_count + (num_pct / 100.0)) / max(1, total)
            send_event("progress", index=idx, total=total, percent=num_pct, speed=spd, eta=eta, overall=overall)

    @staticmethod
    def _final_path(info):
        for rd in info.get("requested_downloads") or []:
            p = rd.get("filepath")
            if p and os.path.isfile(p):
                return p
        p = info.get("filepath") or info.get("_filename")
        return p if p and os.path.isfile(p) else None

    def download_one(self, idx, total, item):
        url = item["url"]
        if self.cancel_flag:
            return None

        max_attempts = 3
        backoff_delays = [5.0, 12.0, 25.0]
        attempt = 0

        sp = spotify_ref(url)
        if sp and sp[0] in ("episode", "show"):
            return self._fail(idx, total, url, "Spotify podcast linkleri desteklenmiyor. "
                                               "Parça, albüm, çalma listesi veya sanatçı linki kullan.")
        if sp and sp[0] != "track":
            # Liste açılamadıysa (expand_queue hatası) buraya tek link olarak düşer
            return self._fail(idx, total, url, "Spotify listesi açılamadı (özel liste olabilir).")
        sp_meta, dl_url = None, url
        skip_ids = set()  # açılamayan eşleşmeler; denemeler arasında korunur

        # Senkron/atlama: bu Spotify parçası bu liste klasörüne zaten indiyse YouTube'da yeniden arama
        if sp and (self.skip_downloaded or self.spotify_sync):
            known = self._sync_known_file(item["folder"], sp[1])
            if known:
                title = os.path.splitext(os.path.basename(known))[0]
                with self.lock:
                    self.completed_count += 1
                    self.skipped_count += 1
                    overall = self.completed_count / total
                    self.outputs[idx] = known
                send_event("item_start", index=idx, total=total, title=title)
                log(f"[{idx}/{total}] Daha önce indirilmiş, atlandı: {title}", "info")
                send_event("item_skipped", index=idx, total=total, title=title)
                send_event("progress", index=idx, total=total, percent=100.0, speed="", eta="", overall=overall)
                return True

        while attempt < max_attempts:
            attempt += 1
            if self.cancel_flag:
                return None

            stage = "download"
            try:
                if sp and dl_url == url:
                    stage = "spotify"
                    if sp_meta is None:
                        sp_meta = deezer_enrich(spotify_track_meta(sp[1]))
                        sp_meta["url"] = spotify_track_url(sp[1])
                    sp_meta["_skip_ids"] = skip_ids
                    match = find_youtube_match(sp_meta)
                    # Premium cookie'si varsa YouTube Music adresi 256 kbps AAC (format 141) verebilir
                    host = "music.youtube.com" if match["ytmusic"] and self.cookie_browser not in (None, "none") \
                        else "www.youtube.com"
                    dl_url = f"https://{host}/watch?v={match['id']}"
                    log(f"[{idx}/{total}] Spotify: {spotify_display(sp_meta)} | {match['source']} eşleşmesi: {match['title']}", "info")
                    stage = "download"

                ydl_opts = self.build_ydl_opts(item["folder"])
                ydl_opts["progress_hooks"] = [lambda d: self.progress_hook(d, idx, total)]

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(dl_url, download=False)
                    if info and sp_meta:
                        apply_spotify_meta(info, sp_meta)
                    # Arşivdeki videolar için yt-dlp bilgi döndürmez (None)
                    title = info.get("title", f"audio_{idx}") if info else url
                    send_event("item_start", index=idx, total=total, title=title)
                    if self.skip_downloaded and (info is None or ydl.in_download_archive(info)):
                        with self.lock:
                            self.completed_count += 1
                            self.skipped_count += 1
                            overall = self.completed_count / total
                        log(f"[{idx}/{total}] Daha önce indirilmiş, atlandı: {title}", "info")
                        send_event("item_skipped", index=idx, total=total, title=title)
                        send_event("progress", index=idx, total=total, percent=100.0, speed="", eta="", overall=overall)
                        return True
                    log(f"[{idx}/{total}] İndiriliyor: {title} ({info.get('ext', '?')} ~{info.get('abr', '?')}kbps)", "info")
                    if "141" in str(info.get("format_id") or "").split("+"):
                        log(f"[{idx}/{total}] YouTube Music Premium kalitesi: 256 kbps AAC", "success")
                    info = ydl.process_ie_result(info, download=True)

                with self.lock:
                    self.completed_count += 1
                    overall = self.completed_count / total
                send_event("progress", index=idx, total=total, percent=100.0, speed="", eta="", overall=overall)

                output_path = self._final_path(info)
                cuts = []
                if self.sponsorblock and output_path and self.format_choice != "mp4":
                    cuts = merge_segments([(c["start_time"], c["end_time"]) for c in info.get("sponsorblock_chapters") or []],
                                          info.get("duration") or 0)
                    if cuts:
                        secs = sum(b - a for a, b in cuts)
                        log(f"[{idx}/{total}] SponsorBlock: {len(cuts)} bölüm kesiliyor ({secs:.0f} sn)", "info")
                if output_path and self.format_choice != "mp4" and (cuts or self.loudnorm):
                    if self.loudnorm:
                        log(f"[{idx}/{total}] Ses seviyesi eşitleniyor...", "info")
                    if not rewrite_audio(output_path, self.bitrate, cuts, self.loudnorm):
                        log(f"[{idx}/{total}] Kesim/eşitleme yapılamadı, dosya olduğu gibi bırakıldı.", "warn")
                        cuts = []
                info["_tirtil_cuts"] = cuts
                if output_path and self.format_choice != "mp4":
                    self.finalize_tags(idx, total, output_path, info, sp_meta)
                size_mb = 0.0
                if output_path:
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    log(f"[{idx}/{total}] [OK] Tamam: {os.path.basename(output_path)} ({size_mb:.1f} MB)", "success")
                else:
                    log(f"[{idx}/{total}] [OK] Tamam: {title}.{self.format_choice}", "success")

                send_event("item_done", index=idx, total=total, title=title, size_mb=size_mb, file=output_path or "")
                if output_path:
                    with self.lock:
                        self.outputs[idx] = output_path
                    if sp:
                        self._sync_record(item["folder"], sp[1], output_path)

                if self.split_enabled and output_path and self.format_choice != "mp4":
                    self.handle_split(idx, total, output_path, sanitize_filename(title), info, self.item_dir(item["folder"]))

                return True

            except Exception as e:
                write_persistent_log(traceback.format_exc())
                err_str = str(e)
                low = err_str.lower()

                # DRM'li siteler hiçbir denemede inmez; boşuna tekrar etme
                if "[drm]" in low or "drm protection" in low:
                    return self._fail(idx, total, url, "Bu site DRM korumalı, indirilemez. "
                                                       "(Spotify linkleri YouTube Music üzerinden iner.)")

                # Cookie'li denemede herhangi bir hata (Keychain reddi, bozuk/uyumsuz cookie DB, hesap
                # oturumu sorunları vb.): cookie'siz moda geç, deneme hakkı yakma
                if stage == "download" and self.cookie_browser and self.cookie_browser != "none":
                    log(f"[{idx}/{total}] Tarayıcı cookie'si ile hata ({err_str[:80]}). Cookie'siz deneniyor...", "warn")
                    if ("cookies database" in low or "not permitted" in low or "permission" in low) \
                            and self.cookie_browser not in COOKIE_BLOCKED:
                        COOKIE_BLOCKED.append(self.cookie_browser)
                    with self.lock:
                        self.cookie_browser = "none"
                        self.cookie_profile = None
                    attempt -= 1
                    time.sleep(0.5)
                    continue

                if self.cancel_flag:
                    return None

                # Spotify eşleşmesi açılamadıysa (yaş kısıtı, bölge, kaldırılmış): aynı şarkının başka
                # yüklemesini dene, deneme hakkı yakma
                if sp_meta and stage == "download" and dl_url != url and len(skip_ids) < 3 and any(
                        k in low for k in ("confirm your age", "age-restricted", "age restricted", "unavailable",
                                           "not available", "private video", "removed")):
                    skip_ids.add(dl_url.rsplit("v=", 1)[-1])
                    log(f"[{idx}/{total}] Eşleşen video açılamadı ({err_str[:60]}). Başka yükleme aranıyor...", "warn")
                    dl_url = url
                    attempt -= 1
                    continue

                is_rate_limit = any(k in low for k in ("429", "403", "too many", "sign in", "bot", "confirm"))
                is_bot_check = any(k in low for k in ("sign in", "not a bot", "confirm you", "age-restricted", "age restricted", "members-only"))

                # Bot/oturum engeli + okunamayan tarayıcı cookie'si: izin vermek işe yarar, kullanıcıya söyle
                if is_bot_check and COOKIE_BLOCKED and not getattr(self, "_permission_hinted", False):
                    self._permission_hinted = True
                    send_event("cookie_permission", browsers=COOKIE_BLOCKED)

                if is_rate_limit and attempt < max_attempts:
                    cooldown = backoff_delays[attempt - 1]
                    log(f"[{idx}/{total}] YouTube bot koruması algılandı. {cooldown:.0f}s bekleniyor ({attempt}/{max_attempts})...", "warn")
                    time.sleep(cooldown)
                elif attempt < max_attempts:
                    log(f"[{idx}/{total}] Sorun: {err_str[:120]}... 3s sonra tekrar ({attempt}/{max_attempts})", "warn")
                    time.sleep(3)
                else:
                    return self._fail(idx, total, url, err_str, f"{max_attempts} denemeden sonra ")

        return False

    def finalize_tags(self, idx, total, path, info, sp_meta):
        """Şarkı sözleri (LRCLIB) ve Spotify'dan gelen ek etiketler (ISRC, explicit, plak şirketi, kaynak linki)."""
        synced = plain = ""
        if self.lyrics:
            if sp_meta:
                artist, title = ", ".join(sp_meta.get("artists") or []), sp_meta["title"]
                album, duration = sp_meta.get("album") or "", sp_meta.get("duration") or 0
            else:
                # YouTube Music / Bandcamp / SoundCloud parçaları sanatçı ve parça adını kendisi verir
                artist = info.get("artist") or ", ".join(info.get("artists") or [])
                title, album, duration = info.get("track") or "", info.get("album") or "", info.get("duration") or 0
            if artist and title:
                synced, plain = fetch_lyrics(artist, title, album, duration)
                if not (synced or plain):
                    log(f"[{idx}/{total}] Şarkı sözü bulunamadı.", "info")
        extra = sp_meta if (sp_meta and self.embed_meta) else None
        if not (synced or plain or extra):
            return
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        tagged = write_tags(path, extra, synced, plain)
        if not tagged and (synced or plain):
            tagged = embed_lyrics(path, synced, plain)
        # MP3'te zamanlı sözler SYLT olarak gömülü; diğer biçimlerde oynatıcılar için .lrc
        lrc = bool(synced) and not (tagged and ext == "mp3") and write_lrc(path, synced)
        if synced or plain:
            how = "zamanlı, gömülü" if (synced and tagged and ext == "mp3") else "gömülü" if tagged else ""
            how = ", ".join(x for x in (how, ".lrc" if lrc else "") if x)
            if how:
                log(f"[{idx}/{total}] Şarkı sözleri eklendi ({how}).", "info")

    def _fail(self, idx, total, url, error, prefix=""):
        with self.lock:
            self.failed_count += 1
        log(f"[{idx}/{total}] {prefix}BAŞARISIZ: {url} -- {error[:180]}", "error")
        send_event("item_failed", index=idx, total=total, url=url, error=error[:180])
        return False

    def handle_split(self, idx, total, filepath, title_prefix, info, out_dir):
        log(f"[{idx}/{total}] Bölüm (chapter) bilgisi kontrol ediliyor...", "info")
        chapters = info.get("chapters") or []
        ch_list = []
        if chapters:
            for ch in chapters:
                ch_list.append({
                    "start": ch.get("start_time", 0),
                    "end": ch.get("end_time", 0),
                    "title": ch.get("title", ""),
                })
            if info.get("_tirtil_cuts"):
                ch_list = shift_chapters(ch_list, info["_tirtil_cuts"])
            log(f"[{idx}/{total}] {len(ch_list)} YouTube bölümü bulundu", "success")
        else:
            log(f"[{idx}/{total}] FFmpeg ile sessizlik aralıkları aranıyor...", "info")
            ch_list = self.detect_chapters_from_silence(filepath)

        if len(ch_list) < 2:
            log(f"[{idx}/{total}] Tek parça algılandı, bölme atlandı.", "info")
            return

        log(f"[{idx}/{total}] Ses {len(ch_list)} ayrı parçaya bölünüyor...", "info")
        split_dir = os.path.join(out_dir, sanitize_filename(title_prefix))
        os.makedirs(split_dir, exist_ok=True)

        results = split_audio_file(filepath, ch_list, split_dir, title_prefix, codec=self.format_choice, bitrate=f"{self.bitrate}k")
        if results:
            log(f"[{idx}/{total}] Auto-Split tamam: {len(results)} parça '{os.path.basename(split_dir)}' klasörüne kaydedildi", "success")
            try:
                os.remove(filepath)
                log(f"[{idx}/{total}] Ana derleme dosyası temizlendi", "info")
            except Exception:
                pass

    def detect_chapters_from_silence(self, filepath):
        duration = get_audio_duration(filepath)
        if duration <= 0:
            return []
        silences = detect_silence(filepath, silence_thresh=-38, min_silence=1.0)
        if len(silences) < 2:
            silences = detect_silence(filepath, silence_thresh=-32, min_silence=0.8)
        if len(silences) < 2:
            return []

        boundaries = [0.0] + [s for s in silences if 2.0 < s < duration - 2.0] + [duration]
        chapters = []
        for i in range(len(boundaries) - 1):
            s, e = boundaries[i], boundaries[i + 1]
            if e - s > 3:
                chapters.append({"start": s, "end": e, "title": f"Parça {len(chapters)+1:02d}"})
        return chapters

    def expand_queue(self):
        # Genişletme kapalıyken bile düz çalma listesi sayfası (v= yok) tek iş gibi inmesin diye açılır
        targets = [i["url"] for i in self.items if needs_expand(i["url"], self.expand_playlists)]
        if targets:
            results = {r["url"]: r for r in expand_urls(targets)}
            expanded, seen = [], set()
            for item in self.items:
                r = results.get(item["url"])
                if r is None:
                    entries, folder = [item["url"]], item["folder"]
                else:
                    if r.get("error"):
                        log(f"Çalma listesi açılamadı, tek link olarak denenecek: {r['url']} -- {r['error']}", "warn")
                    elif r.get("title"):
                        log(f"Liste genişletildi: {r['title']} ({len(r['entries'])} parça)", "success")
                    entries, folder = r["entries"], (r.get("title") or item["folder"])
                    if r.get("spotify_complete") and folder:
                        self.synced_lists[folder] = {e.rsplit("/", 1)[-1] for e in entries}
                for link in entries:
                    if link not in seen:
                        seen.add(link)
                        expanded.append({"url": link, "folder": folder})
            self.items = expanded
            self.total_count = len(expanded)
        send_event("queue", items=[{"index": n, "url": i["url"], "folder": i["folder"]} for n, i in enumerate(self.items, 1)])

    def run(self):
        self.expand_queue()
        quality = "" if self.format_choice in ("mp4", "original", "wav", "flac") else f" {self.bitrate}kbps"
        log(f"İndirme başlıyor: {self.total_count} link [{self.format_choice.upper()}{quality}]", "info")
        log(f"Engel koruması: Cookie [{self.cookie_browser}] | Bekleme [{self.delay_mode}]", "info")
        log(f"yt-dlp {yt_dlp.version.__version__} ({YTDLP_SOURCE})", "info")
        ffmpeg = _find_tool("ffmpeg")
        if not ffmpeg:
            log("FFmpeg bulunamadı! Uygulamayı yeniden indir veya: brew install ffmpeg", "error")
        rt_name, _ = get_node_bin()
        if not rt_name:
            log("JS çalışma zamanı (node/deno) yok; bazı videolar başarısız olabilir.", "warn")

        clear_ytdlp_cache()
        log("yt-dlp iç token önbelleği otomatik temizlendi.", "info")

        if self.workers > 1 and self.total_count > 1:
            active_workers = min(self.workers, self.total_count)
            log(f"Paralel mod: {active_workers} eşzamanlı indirme", "info")
            with concurrent.futures.ThreadPoolExecutor(max_workers=active_workers) as executor:
                futures = []
                for idx, item in enumerate(self.items, 1):
                    if self.cancel_flag:
                        break
                    futures.append(executor.submit(self.download_one, idx, self.total_count, item))
                    delay = self.get_delay_seconds()
                    if delay > 0 and idx < self.total_count:
                        time.sleep(delay * 0.4)
                concurrent.futures.wait(futures)
        else:
            for idx, item in enumerate(self.items, 1):
                if self.cancel_flag:
                    log("İndirme kullanıcı tarafından durduruldu.", "warn")
                    break
                self.download_one(idx, self.total_count, item)

                delay = self.get_delay_seconds()
                if delay > 0 and idx < self.total_count and not self.cancel_flag:
                    log(f"Sonraki link öncesi {delay:.1f}s bekleme...", "info")
                    time.sleep(delay)

        if self.spotify_sync and not self.cancel_flag and self.playlist_folders:
            self.sync_remove_missing()
        if self.playlist_m3u and self.playlist_folders and self.format_choice != "mp4":
            self.write_m3u()

        send_event("finished", success=self.completed_count, failed=self.failed_count, skipped=self.skipped_count,
                   total=self.total_count, folder=self.download_folder)
        log(f"Bitti! {self.completed_count}/{self.total_count} başarılı, {self.failed_count} başarısız.", "success" if self.failed_count == 0 else "warn")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--ytdlp-info":
        send_event("ytdlp_info", version=yt_dlp.version.__version__, bundled=YTDLP_BUNDLED, source=YTDLP_SOURCE)
        return

    if len(sys.argv) >= 3 and sys.argv[1] == "--expand":
        try:
            with open(sys.argv[2], "r", encoding="utf-8") as f:
                urls = json.load(f).get("urls", [])
        except Exception as e:
            send_event("error", error=f"Geçersiz yapılandırma: {e}")
            sys.exit(1)
        send_event("expanded", results=expand_urls(urls))
        return

    try:
        if len(sys.argv) < 2:
            config = json.loads(sys.stdin.read())
        else:
            with open(sys.argv[1], "r", encoding="utf-8") as f:
                config = json.load(f)
    except Exception as e:
        send_event("error", error=f"Geçersiz yapılandırma: {e}")
        sys.exit(1)

    BatchDownloader(config).run()


if __name__ == "__main__":
    main()
