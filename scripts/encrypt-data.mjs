// Netlify build step: encrypt data/garmin.json into docs/data.js.
// AES-256-GCM with a PBKDF2-SHA256 key from $DASHBOARD_PASSWORD; docs/index.html
// decrypts it in the browser with the same parameters (Web Crypto).
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { pbkdf2Sync, randomBytes, createCipheriv } from "node:crypto";

const SOURCE = "data/garmin.json";
const TARGET = "docs/data.js";
const ITERATIONS = 600000;

const password = process.env.DASHBOARD_PASSWORD;
if (!password) {
  console.error("DASHBOARD_PASSWORD is not set - refusing to publish. Add it under Site configuration > Environment variables.");
  process.exit(1);
}
if (!existsSync(SOURCE)) {
  console.log(`${SOURCE} not found yet - the dashboard will show demo data until the first sync.`);
  process.exit(0);
}

const salt = randomBytes(16);
const iv = randomBytes(12);
const key = pbkdf2Sync(password, salt, ITERATIONS, 32, "sha256");
const cipher = createCipheriv("aes-256-gcm", key, iv);
const ciphertext = Buffer.concat([cipher.update(readFileSync(SOURCE)), cipher.final(), cipher.getAuthTag()]);

const payload = { v: 1, iter: ITERATIONS, salt: salt.toString("base64"), iv: iv.toString("base64"), data: ciphertext.toString("base64") };
writeFileSync(TARGET, `window.GARMIN_ENC = ${JSON.stringify(payload)};\n`);
console.log(`Encrypted ${SOURCE} -> ${TARGET}`);
