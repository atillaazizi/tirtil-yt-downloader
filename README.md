# Tırtıl YT Downloader

macOS için toplu YouTube ses/video indirici. Link listesini yapıştır, formatı seç, indir.
İstersen albüm/derleme videolarını parçalara böler (YouTube bölümleri, yoksa sessizlik algılama).

> [rtrw_/dotu-yt](https://github.com/rtrwcloud/dotu-yt) (MIT) projesinin macOS portu.

## Kurulum

**Terminalden (önerilen):**

```bash
curl -fsSL https://raw.githubusercontent.com/atillaazizi/tirtil-yt-downloader/main/install.sh | bash
```

Son sürümü indirir, SHA-256 ve kod imzasını doğrular, `/Applications`'a kurar ve açar.
Belirli bir sürüm için: `... | bash -s -- 1.2.1`. Terminalden kurulumda macOS "geliştirici doğrulanamadı" uyarısı çıkmaz.

**Elle (DMG):** aşağıdaki adımlar.

## Kullanım (hazır uygulama)

1. `Tirtil-x.y.z-arm64.dmg` ([Releases](https://github.com/atillaazizi/tirtil-yt-downloader/releases/latest)) dosyasını aç, uygulamayı **Applications** klasörüne sürükle.
2. İlk açılışta macOS "geliştirici doğrulanamadı" uyarısı verir (uygulama Apple imzalı değil):
   - **Sistem Ayarları → Gizlilik ve Güvenlik** → en altta **"Yine de Aç"**, ya da
   - Terminal'de: `xattr -dr com.apple.quarantine "/Applications/Tırtıl.app"`
3. Linkleri yapıştır → format seç → **İndir**. Dosyalar `İndirilenler/Tırtıl_Downloads` klasörüne iner.

Ek kurulum gerekmez: FFmpeg, Python motoru ve Node uygulamanın içinde. Apple Silicon (M1 ve sonrası), macOS 12+.

**Not:** YouTube "bot" engeli verirse *Gelişmiş → Tarayıcı cookie* ile YouTube'a giriş yapılmış tarayıcıyı seç.
Chrome/Brave/Edge'de macOS Anahtar Zinciri izin sorar — "İzin Ver". Safari için Tam Disk Erişimi gerekir.

## Güncellemeler

Uygulama açılışta GitHub'daki son sürümü denetler (menü: **Tırtıl → Güncellemeleri Denetle…**).
Yeni sürüm varsa sorar; onaylanınca DMG'yi indirir, uygulamayı kapatıp yenisini yerine kurar ve yeniden açar.

İndirme motoru yt-dlp ayrıca günde bir kez denetlenir (Gelişmiş → **yt-dlp'yi Güncelle** / **Otomatik güncelle**).
Resmi yt-dlp sürümünün zipapp'i indirilir, aynı sürümün `SHA2-256SUMS` dosyasıyla doğrulanır ve
`~/Library/Application Support/Tırtıl/yt-dlp/` altında saklanır; paketteki sürümden yeniyse o kullanılır.
Böylece YouTube değişikliklerine karşı uygulamanın yeniden build edilmesi gerekmez.

## Yeni sürüm yayınlama

1. `package.json` içindeki `version` değerini artır (ör. `1.2.1`).
2. `npm run build` → `dist/Tirtil-<sürüm>-arm64.dmg`
3. `node scripts/sign_release.js dist/Tirtil-<sürüm>-arm64.dmg` → `.sig` (sürüm + mimari + SHA-256 içeren imzalı manifest)
4. `gh release create v<sürüm> dist/Tirtil-<sürüm>-arm64.dmg dist/Tirtil-<sürüm>-arm64.dmg.sig --title "Tırtıl v<sürüm>" --notes "..."`

Etiket `v` + `package.json` sürümüyle aynı olmalı; uygulamalar bu sürümü görüp güncelleme önerir.
Uygulama yalnızca `~/.config/tirtil/update-signing-key.pem` ile imzalanmış DMG'leri kurar — bu anahtarı yedekle,
kaybolursa mevcut kullanıcılara otomatik güncelleme gönderilemez.

## Geliştirme

```bash
./scripts/setup.sh   # python venv + npm install
npm start            # geliştirme modu
npm run build        # dist/*.dmg
```

Paketteki yt-dlp'yi yenilemek için: `./scripts/setup.sh && npm run build` (uygulama zaten kendini de günceller).

## Lisans

MIT — bkz. [LICENSE](LICENSE). Orijinal telif: rtrw_.
