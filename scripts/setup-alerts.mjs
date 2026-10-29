#!/usr/bin/env node
// Switch on route alerts: the 3-hourly rain check, and Web Push delivery.
//
// Both need secrets that live in two places at once — CRON_SECRET in GitHub
// (the cron sends it) and in Render (the backend checks it), VAPID keys in
// Render. This mints them, sets the GitHub half itself through the `gh` CLI,
// and writes the Render half to `.env.render` (git-ignored) for Render's
// "Add from .env" box. It also puts that text on the clipboard.
//
// Values are never printed, so it's safe to run where output is shared or
// logged. Re-running reuses `.env.render`, so GitHub and Render can't drift.
//
//   node scripts/setup-alerts.mjs [backend-url] [contact]
//
// Defaults are the live instance; pass your own when deploying a fork. The
// contact is the VAPID `sub` claim: a mailto: or https: URL push services can
// reach you at if your pushes misbehave.
import { execFileSync } from "node:child_process";
import { generateKeyPairSync, randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { platform } from "node:os";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const ENV_FILE = `${ROOT}.env.render`;
const BACKEND_URL = process.argv[2] ?? "https://floodwatch-backend-dlni.onrender.com";
const CONTACT = process.argv[3] ?? "https://floodwatch-ghana-ten.vercel.app";

function readEnv(path) {
  if (!existsSync(path)) return {};
  return Object.fromEntries(
    readFileSync(path, "utf8")
      .split(/\r?\n/)
      .filter((line) => line.includes("=") && !line.startsWith("#"))
      .map((line) => [line.slice(0, line.indexOf("=")), line.slice(line.indexOf("=") + 1)])
  );
}

// A P-256 coordinate or scalar is 32 bytes; JWK may drop leading zeros.
const pad32 = (b64u) => {
  const raw = Buffer.from(b64u, "base64url");
  return Buffer.concat([Buffer.alloc(32 - raw.length), raw]);
};

/** Same shape as `python -m app.services.push`: raw public point + raw scalar, base64url. */
function vapidKeys() {
  const { privateKey } = generateKeyPairSync("ec", { namedCurve: "prime256v1" });
  const { x, y, d } = privateKey.export({ format: "jwk" });
  return {
    VAPID_PUBLIC_KEY: Buffer.concat([Buffer.from([4]), pad32(x), pad32(y)]).toString("base64url"),
    VAPID_PRIVATE_KEY: pad32(d).toString("base64url"),
  };
}

const existing = readEnv(ENV_FILE);
const env = {
  CRON_SECRET: existing.CRON_SECRET ?? randomBytes(32).toString("hex"),
  ...(existing.VAPID_PRIVATE_KEY
    ? { VAPID_PUBLIC_KEY: existing.VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY: existing.VAPID_PRIVATE_KEY }
    : vapidKeys()),
  VAPID_SUBJECT: existing.VAPID_SUBJECT ?? CONTACT,
};
const text = Object.entries(env).map(([k, v]) => `${k}=${v}`).join("\n") + "\n";
writeFileSync(ENV_FILE, text, { mode: 0o600 });
console.log(existing.CRON_SECRET ? "Reused .env.render." : "Wrote new secrets to .env.render.");

const gh = (args, input) =>
  execFileSync("gh", args, { cwd: ROOT, input, stdio: ["pipe", "pipe", "inherit"] })
    .toString()
    .trim();

const repo = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]);
// Piped through stdin, so neither value appears in the process list or the output.
gh(["secret", "set", "CRON_SECRET", "--repo", repo], env.CRON_SECRET);
gh(["secret", "set", "BACKEND_URL", "--repo", repo], BACKEND_URL);
console.log(`Set CRON_SECRET and BACKEND_URL on GitHub (${repo}).`);

const clipboard = { win32: "clip", darwin: "pbcopy" }[platform()];
if (clipboard) {
  execFileSync(clipboard, { input: text });
  console.log("Copied the Render values to your clipboard.");
}
console.log(
  "\nLast step: in Render, open the backend's Environment page, click\n" +
    '"Add from .env", paste, then "Save, rebuild, and deploy".'
);
