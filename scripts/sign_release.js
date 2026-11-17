#!/usr/bin/env node
// Güncelleme imzası (Ed25519, sürüme bağlı manifest).
//   node scripts/sign_release.js --init        → anahtar çifti üretir, açık anahtarı yazdırır
//   node scripts/sign_release.js <dosya.dmg>   → <dosya.dmg>.sig (JSON manifest) üretir
// Dosya adı Tirtil-<sürüm>-<arch>.dmg olmalı; sürüm package.json ile aynı olmalı.
// Özel anahtar repo dışında tutulur: ~/.config/tirtil/update-signing-key.pem (YEDEKLE!)
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const KEY_PATH = process.env.TIRTIL_SIGNING_KEY || path.join(os.homedir(), '.config', 'tirtil', 'update-signing-key.pem');
const arg = process.argv[2];

if (arg === '--init') {
  if (fs.existsSync(KEY_PATH)) {
    console.error(`Anahtar zaten var: ${KEY_PATH}`);
    process.exit(1);
  }
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519');
  fs.mkdirSync(path.dirname(KEY_PATH), { recursive: true, mode: 0o700 });
  fs.writeFileSync(KEY_PATH, privateKey.export({ type: 'pkcs8', format: 'pem' }), { mode: 0o600 });
  console.log(`Özel anahtar: ${KEY_PATH}`);
  console.log('Açık anahtar (electron/updater.js içine):');
  console.log(publicKey.export({ type: 'spki', format: 'pem' }));
  process.exit(0);
}

if (!arg || !fs.existsSync(arg)) {
  console.error('Kullanım: node scripts/sign_release.js <Tirtil-sürüm-arch.dmg> | --init');
  process.exit(1);
}
const match = path.basename(arg).match(/^Tirtil-(\d+\.\d+\.\d+)-(arm64|x64)\.dmg$/);
if (!match) {
  console.error('Dosya adı Tirtil-<sürüm>-<arch>.dmg biçiminde olmalı.');
  process.exit(1);
}
const [, version, arch] = match;
const pkgVersion = require(path.join(__dirname, '..', 'package.json')).version;
if (version !== pkgVersion) {
  console.error(`Sürüm uyuşmuyor: dosya ${version}, package.json ${pkgVersion}`);
  process.exit(1);
}
const sha256 = crypto.createHash('sha256').update(fs.readFileSync(arg)).digest('hex');
const payload = `tirtil-update:v1\n${version}\n${arch}\n${sha256}`;
const key = crypto.createPrivateKey(fs.readFileSync(KEY_PATH));
const signature = crypto.sign(null, Buffer.from(payload), key).toString('base64');
fs.writeFileSync(`${arg}.sig`, JSON.stringify({ version, arch, sha256, signature }, null, 2) + '\n');
console.log(`İmza: ${arg}.sig`);
