// Netlify "ignore" step: exit 0 skips the build, exit 1 builds.
// Each production deploy costs Netlify credits (the free plan covers ~20 a month), so
// when the page loads its data live from GitHub, skip commits that only touch data/.
import { execSync } from "node:child_process";

const { CACHED_COMMIT_REF: prev, COMMIT_REF: cur, DASHBOARD_GITHUB_TOKEN: token } = process.env;

if (!token) {
  console.log("DASHBOARD_GITHUB_TOKEN not set: the page embeds its data, so every data commit needs a build.");
  process.exit(1);
}
if (!prev || !cur || prev === cur) process.exit(1); // first build or a manual "Trigger deploy"

try {
  const changed = execSync(`git diff --name-only ${prev} ${cur}`).toString().split("\n").filter(Boolean);
  if (changed.length && changed.every(f => f.startsWith("data/"))) {
    console.log("Only data/ changed - the page reads it live from GitHub, skipping the build.");
    process.exit(0);
  }
} catch (e) {
  console.log(`Could not diff ${prev}..${cur} (${e.message.split("\n")[0]}), building.`);
}
process.exit(1);
