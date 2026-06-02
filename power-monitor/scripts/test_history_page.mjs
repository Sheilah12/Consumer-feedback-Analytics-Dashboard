import { chromium } from "playwright";

const base = process.env.BASE_URL || "http://127.0.0.1";

const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
});

await page.goto(`${base}/history`, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(2000);

const state = await page.evaluate(() => {
  const power = window.Chart?.getChart?.("chart-power");
  const daily = window.Chart?.getChart?.("chart-daily");
  const tbody = document.getElementById("readings-tbody")?.innerText?.slice(0, 80);
  return {
    chartJs: typeof Chart !== "undefined",
    chartZoom: typeof ChartZoom !== "undefined",
    hammer: typeof Hammer !== "undefined",
    powerPoints: power?.data?.datasets?.[0]?.data?.length ?? -1,
    dailyPoints: daily?.data?.datasets?.[0]?.data?.length ?? -1,
    tbody,
  };
});

console.log(JSON.stringify({ state, errors }, null, 2));
await browser.close();
