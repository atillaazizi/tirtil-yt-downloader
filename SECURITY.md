# Güvenlik

## Açık bildirme

Bir güvenlik açığı bulduysan lütfen herkese açık issue açma.
GitHub'da **Security → Report a vulnerability** ile gizli olarak bildir.

## Güncelleme güvenliği

- Uygulama yalnızca GitHub Releases'teki `Tirtil-<sürüm>-<arch>.dmg` dosyasını indirir.
- Her sürümün yanında Ed25519 ile imzalanmış bir manifest (`.dmg.sig`) bulunur: sürüm, mimari ve DMG'nin SHA-256 değeri.
- Uygulama, içine gömülü açık anahtarla imzayı doğrular; sürüm etiketle aynı ve yüklü sürümden yeni olmalı, SHA-256 eşleşmeli.
  Bunlardan biri tutmazsa güncelleme kurulmaz (eski sürüme düşürme ve değiştirilmiş dosya engellenir).
- Kurulumdan önce `codesign --verify --deep --strict` ile paket bütünlüğü denetlenir.

## yt-dlp güncellemeleri

- İndirme motoru yt-dlp, uygulamadan bağımsız olarak yalnızca `github.com/yt-dlp/yt-dlp` resmi sürümlerinden güncellenir.
- İndirilen zipapp, aynı sürümün `SHA2-256SUMS` dosyasıyla doğrulanır; tutmazsa kullanılmaz.
  Yüklenemezse paketteki yt-dlp'ye dönülür.
- Bu, yt-dlp'nin kendi `yt-dlp -U` güncellemesiyle aynı güven modelidir: güven GitHub'a ve yt-dlp projesine dayanır,
  uygulamanın Ed25519 imzası bu dosyayı kapsamaz. İstemeyen kullanıcı Gelişmiş → **Otomatik güncelle**'yi kapatabilir.
