#!/usr/bin/env node
// Güncelleme imzası (Ed25519).
//   node scripts/sign_release.js --init        → anahtar çifti üretir, açık anahtarı yazdırır
//   node scripts/sign_release.js <dosya.dmg>   → <dosya.dmg>.sig üretir
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
  console.error('Kullanım: node scripts/sign_release.js <dosya.dmg> | --init');
  process.exit(1);
}
const key = crypto.createPrivateKey(fs.readFileSync(KEY_PATH));
const sig = crypto.sign(null, fs.readFileSync(arg), key).toString('base64');
fs.writeFileSync(`${arg}.sig`, sig + '\n');
console.log(`İmza: ${arg}.sig`);
