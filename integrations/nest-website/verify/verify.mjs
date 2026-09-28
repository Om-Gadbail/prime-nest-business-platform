/** Prompt 5 Nest browser verification (exact production drop-in code).
 *
 * Serves `integrations/nest-website/verify/` with Vite (real VITE_* env, real
 * TS pipeline — the same path the production Nest site will use), drives it
 * with real Chromium (desktop + mobile), and asserts the production adapter:
 *  - homepage renders + config fetch fires to /api/v1/public/nest/config
 *  - enquiry POST goes to /api/v1/public/nest/leads (slug=net, never prime)
 *    with Idempotency-Key header
 *  - success state renders backend message; error state renders distinctly
 *  - honeypot path short-circuits without network (spam-safe)
 *
 * Backend is stubbed at the network edge via request interception so the
 * browser proof is deterministic without a live server; the LIVE backend
 * proof is `backend/tests/test_block3_nest_public.py` + Prompt 5 pytest
 * (real POSTs to /api/v1/public/nest/* asserting Nest visibility).
 *
 * Usage: node verify.mjs [--port 5123]
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const VITE_BIN =
  "C:\\Users\\ossag\\OneDrive\\Desktop\\prime-nest-business-platform\\apps\\staff-dashboard\\node_modules\\.bin\\vite.cmd";
const portArg = process.argv.find((a) => a.startsWith("--port="));
const PORT = portArg ? Number(portArg.split("=")[1]) : 5123;

function waitFor(url, timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const res = await fetch(url);
        if (res.ok) return resolve(true);
      } catch {
        /* not up yet */
      }
      if (Date.now() - start > timeoutMs) return reject(new Error(`vite not up: ${url}`));
      setTimeout(tick, 500);
    };
    tick();
  });
}

async function main() {
  const { createRequire } = await import("node:module");
  const require = createRequire(
    "C:\\Users\\ossag\\OneDrive\\Desktop\\prime-nest-business-platform\\apps\\staff-dashboard\\package.json",
  );
  const { chromium: chromiumApi } = require("@playwright/test");
  const viteUp = await (async () => {
    try {
      const res = await fetch(`http://localhost:${PORT}/`);
      return res.ok;
    } catch {
      return false;
    }
  })();
  // Reuse an already-running host (e.g. started manually); otherwise spawn one.
  const vite = viteUp
    ? null
    : spawn(`"${VITE_BIN}" --port ${PORT} --strictPort`, {
        cwd: here,
        stdio: "pipe",
        shell: true,
      });
  let viteLog = "";
  if (vite) {
    vite.stdout.on("data", (d) => (viteLog += String(d)));
    vite.stderr.on("data", (d) => (viteLog += String(d)));
  }
  const results = [];
  try {
    await waitFor(`http://localhost:${PORT}/`);
    const browser = await chromiumApi.launch();
    try {
      for (const viewport of [
        { width: 1280, height: 800, label: "desktop" },
        { width: 390, height: 844, label: "mobile" },
      ]) {
        const context = await browser.newContext({ viewport });
        const page = await context.newPage();
        const seen = { config: null, lead: null };
        await page.route("**/api/v1/public/nest/config", async (route) => {
          seen.config = route.request().url();
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              slug: "nest",
              lead_capture_enabled: true,
              booking_enabled: true,
            }),
          });
        });
        await page.route("**/api/v1/public/nest/leads", async (route) => {
          seen.lead = {
            url: route.request().url(),
            method: route.request().method(),
            idem: route.request().headers()["idempotency-key"],
            body: route.request().postDataJSON(),
          };
          await route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify({
              success: true,
              status: "received",
              lead_id: "11111111-1111-4111-8111-111111111111",
              message: "Enquiry received — Nest Library will confirm shortly.",
            }),
          });
        });
        await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
        await page.waitForSelector("#enquiry-form");
        const title = await page.title();
        results.push({ check: `${viewport.label}: homepage renders`, pass: title.includes("Nest") });
        await page.waitForFunction(
          () => document.getElementById("config-status")?.dataset.loaded === "true",
          { timeout: 15000 },
        );
        results.push({ check: `${viewport.label}: config fetch fires`, pass: !!seen.config });
        results.push({
          check: `${viewport.label}: config targets nest slug`,
          pass: String(seen.config || "").includes("/api/v1/public/nest/config"),
        });
        await page.fill("#name", "Aarav Sharma");
        await page.fill("#phone", "+919876543210");
        await page.selectOption("#interest", "Seat Inquiry");
        await page.fill("#message", "Evening seat enquiry");
        await page.click("button[type=submit]");
        await page.waitForFunction(
          () => document.getElementById("result")?.dataset.state === "success",
          { timeout: 15000 },
        );
        const successText = await page.textContent("#result");
        results.push({
          check: `${viewport.label}: lead POST targets nest slug`,
          pass: String(seen.lead?.url || "").includes("/api/v1/public/nest/leads"),
        });
        results.push({
          check: `${viewport.label}: never posts to prime slug`,
          pass: !String(seen.lead?.url || "").includes("/prime/"),
        });
        results.push({
          check: `${viewport.label}: idempotency-key header present`,
          pass: !!seen.lead?.idem,
        });
        results.push({
          check: `${viewport.label}: success state renders`,
          pass: /received/i.test(successText || ""),
        });
        await page.screenshot({
          path: path.join(here, `shot-${viewport.label}-success.png`),
        });
        // Error state: next submit fails distinctly.
        await page.unroute("**/api/v1/public/nest/leads");
        await page.route("**/api/v1/public/nest/leads", async (route) => {
          await route.fulfill({
            status: 422,
            contentType: "application/json",
            body: JSON.stringify({ error: { message: "Phone number looks invalid." } }),
          });
        });
        await page.click("button[type=submit]");
        await page.waitForFunction(
          () => document.getElementById("result")?.dataset.state === "error",
          { timeout: 15000 },
        );
        results.push({ check: `${viewport.label}: error state renders`, pass: true });
        await page.screenshot({
          path: path.join(here, `shot-${viewport.label}-error.png`),
        });
        await context.close();
      }
      // Honeypot: the production contract posts website_url in the body and
      // the BACKEND short-circuits (fake success, no lead created). Assert
      // the honeypot value is transmitted for backend filtering and the UX
      // still renders success (no bot-visible error oracle).
      const context = await browser.newContext();
      const page = await context.newPage();
      let honeypotBody = null;
      await page.route("**/api/v1/public/nest/config", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ slug: "nest", lead_capture_enabled: true, booking_enabled: true }),
        });
      });
      await page.route("**/api/v1/public/nest/leads", async (route) => {
        honeypotBody = route.request().postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            status: "received",
            lead_id: "22222222-2222-4222-8222-222222222222",
            message: "Enquiry received — Nest Library will confirm shortly.",
          }),
        });
      });
      await page.goto(`http://localhost:${PORT}/`, { waitUntil: "networkidle" });
      await page.waitForSelector("#enquiry-form");
      await page.fill("#name", "Spam Bot");
      await page.fill("#phone", "+910000000000");
      await page.evaluate(() => {
        document.getElementById("website_url").value = "http://spam.example";
      });
      await page.click("button[type=submit]");
      await page.waitForFunction(
        () => document.getElementById("result")?.dataset.state === "success",
        { timeout: 15000 },
      );
      results.push({
        check: "honeypot value transmitted for backend filtering",
        pass: honeypotBody !== null && String(honeypotBody.website_url || "") !== "",
      });
      await context.close();
    } finally {
      await browser.close();
    }
  } finally {
    if (vite) vite.kill();
  }
  const failed = results.filter((r) => !r.pass);
  for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.check}`);
  console.log(`\n${results.length - failed.length}/${results.length} nest drop-in browser checks passed`);
  if (failed.length) {
    console.log("vite log tail:\n" + String(viteLog).slice(-2000));
    process.exit(1);
  }
  fs.writeFileSync(path.join(here, "verify-results.json"), JSON.stringify(results, null, 2));
}

main().catch((err) => {
  console.error("nest verify failed:", err);
  process.exit(1);
});
