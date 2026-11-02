import { createRequire } from "module";

const input = JSON.parse(await new Promise((resolve, reject) => {
  let s = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (d) => (s += d));
  process.stdin.on("end", () => resolve(s));
  process.stdin.on("error", reject);
}));

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require(input.playwrightModule || "playwright"));
} catch (e) {
  console.log(JSON.stringify({ error: "playwright is not installed" }));
  process.exit(3);
}

const launch = { headless: true, args: ["--no-sandbox"] };
if (input.chromePath) launch.executablePath = input.chromePath;
const browser = await chromium.launch(launch);
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 900 } });
const page = await context.newPage();

const pageErrors = [];
const consoleErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e && e.message || e)));
page.on("console", (m) => {
  if (m.type() !== "error") return;
  const t = m.text();
  if (/Failed to load resource: the server responded with a status of (401|403|404)/.test(t)) return;
  consoleErrors.push(t);
});

const out = { url: input.url, pageErrors, consoleErrors };
try {
  const resp = await page.goto(input.url, { waitUntil: "load", timeout: 20000 });
  out.status = resp ? resp.status() : null;
  out.title = await page.title();
  if (input.login) {
    await page.fill(input.login.passwordSelector, input.login.password);
    await page.click(input.login.submitSelector);
    await page.waitForSelector(input.login.readySelector, { state: "attached", timeout: 15000 });
    out.loggedIn = true;
  }
  await page.waitForTimeout(1500);
  const tabSel = input.tabSelector || '[id^="tbtn-"]';
  out.tabs = await page.$$eval(tabSel, (els) => els.map((e) => (e.id || e.textContent || "").replace(/^tbtn-/, "").trim()).filter(Boolean).sort());
  out.themeToggle = (await page.$$('[data-theme-toggle], #theme-toggle, .theme-toggle, [id*="theme"]')).length;
  for (const tab of input.clickTabs || []) {
    const btn = page.locator(`#tbtn-${tab}`);
    if ((await btn.count()) === 0) { out[`tab_${tab}`] = "absent"; continue; }
    await btn.first().click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(400);
    out[`tab_${tab}`] = await page.locator(`#panel-${tab}.active, #panel-${tab}.is-active, #panel-${tab}:not([hidden])`).count();
  }
} catch (e) {
  out.navigationError = String(e && e.message || e).slice(0, 400);
} finally {
  await browser.close();
}
console.log(JSON.stringify(out));
