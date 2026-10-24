// Netlify build step: encrypt the dashboard bundle into docs/data.js.
// The bundle holds a snapshot of data/garmin.json and, when DASHBOARD_GITHUB_TOKEN is
// set, a read-data/run-sync token so the page can load fresh data from the private
// repo and trigger a sync without a Netlify deploy.
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

const token = process.env.DASHBOARD_GITHUB_TOKEN;
// Netlify sets REPOSITORY_URL, e.g. https://github.com/owner/repo
const repo = process.env.DASHBOARD_GITHUB_REPO || (process.env.REPOSITORY_URL || "").match(/github\.com[/:]([^/]+\/[^/.]+)/)?.[1];
const data = existsSync(SOURCE) ? JSON.parse(readFileSync(SOURCE, "utf8")) : null;

if (!data && !token) {
  console.log(`${SOURCE} not found yet - the dashboard will show demo data until the first sync.`);
  process.exit(0);
}
if (token && !repo) {
  console.error("DASHBOARD_GITHUB_TOKEN is set but the repository is unknown. Set DASHBOARD_GITHUB_REPO=owner/repo.");
  process.exit(1);
}
console.log(token ? `Live data from GitHub repo ${repo} enabled.` : "DASHBOARD_GITHUB_TOKEN not set - the page shows the data from this build only.");

const bundle = { v: 2, data, github: token ? { token, repo } : null };
const salt = randomBytes(16);
const iv = randomBytes(12);
const key = pbkdf2Sync(password, salt, ITERATIONS, 32, "sha256");
const cipher = createCipheriv("aes-256-gcm", key, iv);
const ciphertext = Buffer.concat([cipher.update(JSON.stringify(bundle)), cipher.final(), cipher.getAuthTag()]);

const payload = { v: 2, iter: ITERATIONS, salt: salt.toString("base64"), iv: iv.toString("base64"), data: ciphertext.toString("base64") };
writeFileSync(TARGET, `window.GARMIN_ENC = ${JSON.stringify(payload)};\n`);
console.log(`Encrypted bundle -> ${TARGET}`);
