"""
Tırtıl Engine Worker - Tırtıl YT Downloader (macOS)
Electron UI'ya satır satır JSON olay akışı gönderir.
Fork: dotu-yt by rtrw_ (MIT)
"""

import os
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
import concurrent.futures
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

import yt_dlp  # noqa: E402  (mac_ver yamasından sonra yüklenmeli)

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


def clear_ytdlp_cache():
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            ydl.cache.remove()
        return True
    except Exception:
        return False


class BatchDownloader:
    def __init__(self, config):
        self.urls = config.get("urls", [])
        self.download_folder = os.path.expanduser(config.get("download_folder") or os.path.join(HOME, "Downloads", "Tırtıl_Downloads"))
        self.format_choice = config.get("format", "mp3").lower()
        self.bitrate = str(config.get("bitrate", "320"))
        self.workers = int(config.get("workers", 3))
        self.split_enabled = bool(config.get("split", False))
        self.cookie_choice = (config.get("cookie_browser") or "none").strip().lower()
        self.cookie_browser = None
        self.cookie_profile = None
        self.delay_mode = config.get("delay_mode", "safe")
        self.completed_count = 0
        self.failed_count = 0
        self.total_count = len(self.urls)
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

    def build_ydl_opts(self):
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
            "outtmpl": os.path.join(self.download_folder, "%(title)s.%(ext)s"),
        }

        rt_name, rt_path = get_node_bin()
        if rt_name:
            opts["js_runtimes"] = {rt_name: {"path": rt_path}}
            opts["remote_components"] = ["ejs:github"]

        if self.cookie_browser and self.cookie_browser != "none":
            opts["cookiesfrombrowser"] = (self.cookie_browser, self.cookie_profile, None, None)

        if self.format_choice == "mp4":
            opts.update({
                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
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

        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir
        return opts

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

    def download_one(self, idx, total, url):
        if self.cancel_flag:
            return None

        max_attempts = 3
        backoff_delays = [5.0, 12.0, 25.0]
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            if self.cancel_flag:
                return None

            try:
                ydl_opts = self.build_ydl_opts()
                ydl_opts["progress_hooks"] = [lambda d: self.progress_hook(d, idx, total)]

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get("title", f"audio_{idx}")
                    log(f"[{idx}/{total}] İndiriliyor: {title} ({info.get('ext', '?')} ~{info.get('abr', '?')}kbps)", "info")
                    info = ydl.process_ie_result(info, download=True)

                with self.lock:
                    self.completed_count += 1
                    overall = self.completed_count / total
                send_event("progress", index=idx, total=total, percent=100.0, speed="", eta="", overall=overall)

                output_path = self._final_path(info)
                size_mb = 0.0
                if output_path:
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    log(f"[{idx}/{total}] [OK] Tamam: {os.path.basename(output_path)} ({size_mb:.1f} MB)", "success")
                else:
                    log(f"[{idx}/{total}] [OK] Tamam: {title}.{self.format_choice}", "success")

                send_event("item_done", index=idx, total=total, title=title, size_mb=size_mb, file=output_path or "")

                if self.split_enabled and output_path and self.format_choice != "mp4":
                    self.handle_split(idx, total, output_path, sanitize_filename(title), info)

                return True

            except Exception as e:
                write_persistent_log(traceback.format_exc())
                err_str = str(e)
                low = err_str.lower()

                # Cookie'li denemede herhangi bir hata (Keychain reddi, bozuk/uyumsuz cookie DB, hesap
                # oturumu sorunları vb.): cookie'siz moda geç, deneme hakkı yakma
                if self.cookie_browser and self.cookie_browser != "none":
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
                    with self.lock:
                        self.failed_count += 1
                    log(f"[{idx}/{total}] {max_attempts} denemeden sonra BAŞARISIZ: {url} -- {err_str[:180]}", "error")
                    send_event("item_failed", index=idx, total=total, url=url, error=err_str[:180])
                    return False

        return False

    def handle_split(self, idx, total, filepath, title_prefix, info):
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
            log(f"[{idx}/{total}] {len(ch_list)} YouTube bölümü bulundu", "success")
        else:
            log(f"[{idx}/{total}] FFmpeg ile sessizlik aralıkları aranıyor...", "info")
            ch_list = self.detect_chapters_from_silence(filepath)

        if len(ch_list) < 2:
            log(f"[{idx}/{total}] Tek parça algılandı, bölme atlandı.", "info")
            return

        log(f"[{idx}/{total}] Ses {len(ch_list)} ayrı parçaya bölünüyor...", "info")
        split_dir = os.path.join(self.download_folder, sanitize_filename(title_prefix))
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

    def run(self):
        quality = "" if self.format_choice == "mp4" else f" {self.bitrate}kbps"
        log(f"İndirme başlıyor: {self.total_count} link [{self.format_choice.upper()}{quality}]", "info")
        log(f"Engel koruması: Cookie [{self.cookie_browser}] | Bekleme [{self.delay_mode}]", "info")
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
                for idx, url in enumerate(self.urls, 1):
                    if self.cancel_flag:
                        break
                    futures.append(executor.submit(self.download_one, idx, self.total_count, url))
                    delay = self.get_delay_seconds()
                    if delay > 0 and idx < self.total_count:
                        time.sleep(delay * 0.4)
                concurrent.futures.wait(futures)
        else:
            for idx, url in enumerate(self.urls, 1):
                if self.cancel_flag:
                    log("İndirme kullanıcı tarafından durduruldu.", "warn")
                    break
                self.download_one(idx, self.total_count, url)

                delay = self.get_delay_seconds()
                if delay > 0 and idx < self.total_count and not self.cancel_flag:
                    log(f"Sonraki link öncesi {delay:.1f}s bekleme...", "info")
                    time.sleep(delay)

        send_event("finished", success=self.completed_count, failed=self.failed_count, total=self.total_count, folder=self.download_folder)
        log(f"Bitti! {self.completed_count}/{self.total_count} başarılı, {self.failed_count} başarısız.", "success" if self.failed_count == 0 else "warn")


def main():
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
