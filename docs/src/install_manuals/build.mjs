import { createRequire } from "module";
import path from "path";
import { fileURLToPath } from "url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const here = path.dirname(fileURLToPath(import.meta.url));
const docs = path.join(here, "..", "..");
const jobs = [
  ["pi02w.html", "ASL-DVS_Pi02w_Install_Manual.pdf"],
  ["full.html", "ASL-DVS_Full_Build_Install_Manual.pdf"],
];
const outDir = process.argv[2] || docs;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
for (const [src, pdf] of jobs) {
  const page = await browser.newPage();
  await page.goto("file://" + path.join(here, src), { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({ path: path.join(outDir, pdf), format: "Letter", printBackground: true, preferCSSPageSize: true });
  await page.close();
  console.log("wrote " + path.join(outDir, pdf));
}
await browser.close();
