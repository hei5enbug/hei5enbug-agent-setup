#!/usr/bin/env node
/**
 * Capture elements of a local HTML file to image files.
 *
 * Contract
 *   Input   a local HTML file, a CSS selector, an output directory
 *   Output  one image per matched element, named from the element id, plus a JSON report
 *   Naming  element id with a leading prefix removed by --strip-prefix (only when the id
 *           starts with that prefix). Ids may contain only letters, digits, "-" and "_".
 *           Two elements that would produce the same file name are an error; nothing is
 *           captured until every name is known to be safe and unique.
 *
 * Dependency
 *   Needs a browser automation module resolvable from the working directory, either
 *   playwright or puppeteer-core, and a Chromium-based browser executable.
 *   A missing dependency exits with code 2 and an explanation. It never renders a
 *   partial result and reports success.
 *
 * This script does not judge whether the captured image looks right. Look at it yourself.
 *
 * Usage
 *   render_diagrams.mjs --html page.html --out dir [--selector .diagram]
 *                       [--scale 2] [--browser /path/to/chrome] [--strip-prefix dia-]
 *                       [--no-sandbox]
 *
 * Exit codes: 0 every element captured, 1 no element matched, 2 dependency or usage error.
 */

import { existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";
import { platform } from "node:process";

export const VIEWPORT = { width: 1600, height: 1200 };
const SAFE_ID = /^[A-Za-z0-9_-]+$/;

export function parseArgs(argv) {
  const options = {
    selector: ".diagram",
    scale: 2,
    stripPrefix: "",
    noSandbox: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    switch (flag) {
      case "--html": options.html = value; index += 1; break;
      case "--out": options.out = value; index += 1; break;
      case "--selector": options.selector = value; index += 1; break;
      case "--scale": options.scale = Number(value); index += 1; break;
      case "--browser": options.browser = value; index += 1; break;
      case "--strip-prefix": options.stripPrefix = value ?? ""; index += 1; break;
      case "--no-sandbox": options.noSandbox = true; break;
      case "--help": options.help = true; break;
      default:
        throw new Error(`unknown argument: ${flag}`);
    }
  }
  return options;
}

export function outputName(id, stripPrefix) {
  if (stripPrefix && id.startsWith(stripPrefix)) return id.slice(stripPrefix.length);
  return id;
}

/**
 * Turn element ids into output names, failing before any capture when an id is unsafe
 * for a file name or two elements would collide.
 */
export function planOutputs(ids, options) {
  const names = [];
  const seen = new Map();
  ids.forEach((rawId, index) => {
    const id = rawId || `diagram-${index + 1}`;
    if (!SAFE_ID.test(id)) {
      throw new Error(
        `element id "${id}" is not safe for a file name; use only letters, digits, "-" and "_"`,
      );
    }
    const name = outputName(id, options.stripPrefix);
    if (!name) {
      throw new Error(`element id "${id}" becomes empty after removing prefix "${options.stripPrefix}"`);
    }
    if (seen.has(name)) {
      throw new Error(
        `duplicate output name "${name}" from ids "${seen.get(name)}" and "${id}"; give every diagram a distinct id`,
      );
    }
    seen.set(name, id);
    names.push({ id, name, path: join(options.out, `${name}.png`) });
  });
  return names;
}

const BROWSER_CANDIDATES = {
  darwin: [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  ],
  linux: [
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
  ],
  win32: [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  ],
};

function findBrowser(explicit) {
  const fromEnv =
    process.env.CHROME_PATH ||
    process.env.PUPPETEER_EXECUTABLE_PATH ||
    process.env.BROWSER_PATH;
  for (const candidate of [explicit, fromEnv, ...(BROWSER_CANDIDATES[platform] ?? [])]) {
    if (candidate && existsSync(candidate)) return candidate;
  }
  return null;
}

async function importFrom(specifier) {
  try {
    return await import(specifier);
  } catch {}
  try {
    const requireFromCwd = createRequire(join(process.cwd(), "package.json"));
    return await import(pathToFileURL(requireFromCwd.resolve(specifier)).href);
  } catch {}
  return null;
}

async function loadDriver() {
  const playwright = await importFrom("playwright");
  if (playwright) return { kind: "playwright", module: playwright };
  const puppeteer = await importFrom("puppeteer-core");
  if (puppeteer) {
    return { kind: "puppeteer-core", module: puppeteer.default ?? puppeteer };
  }
  return null;
}

function fail(code, message) {
  process.stderr.write(`${message}\n`);
  process.exit(code);
}

function browserArgs(options) {
  return options.noSandbox ? ["--no-sandbox"] : [];
}

export async function capturePlaywright(driver, options, url) {
  const browser = await driver.module.chromium.launch({
    executablePath: options.browserPath,
    args: browserArgs(options),
  });
  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: options.scale,
    });
    const page = await context.newPage();
    await page.goto(url, { waitUntil: "networkidle" });
    await page.evaluate(() => (document.fonts ? document.fonts.ready.then(() => true) : true));
    const handles = await page.locator(options.selector).all();
    const ids = [];
    for (const handle of handles) ids.push(await handle.getAttribute("id"));
    const plan = planOutputs(ids, options);
    const captured = [];
    for (let index = 0; index < handles.length; index += 1) {
      await handles[index].screenshot({ path: plan[index].path });
      captured.push({ name: plan[index].name, path: plan[index].path });
    }
    return captured;
  } finally {
    await browser.close();
  }
}

export async function capturePuppeteer(driver, options, url) {
  const browser = await driver.module.launch({
    executablePath: options.browserPath,
    headless: "shell",
    args: browserArgs(options),
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ ...VIEWPORT, deviceScaleFactor: options.scale });
    await page.goto(url, { waitUntil: "networkidle0", timeout: 120000 });
    await page.evaluate(() => (document.fonts ? document.fonts.ready.then(() => true) : true));
    const ids = await page.$$eval(options.selector, (elements) =>
      elements.map((element) => element.id || ""),
    );
    const plan = planOutputs(ids, options);
    const handles = await page.$$(options.selector);
    const captured = [];
    for (let index = 0; index < handles.length; index += 1) {
      await handles[index].screenshot({ path: plan[index].path });
      captured.push({ name: plan[index].name, path: plan[index].path });
    }
    return captured;
  } finally {
    await browser.close();
  }
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    fail(2, error.message);
  }

  if (options.help || !options.html || !options.out) {
    process.stdout.write(
      "usage: render_diagrams.mjs --html FILE --out DIR [--selector CSS] [--scale N]\n" +
        "                          [--browser PATH] [--strip-prefix PREFIX] [--no-sandbox]\n",
    );
    process.exit(options.help ? 0 : 2);
  }

  if (!Number.isFinite(options.scale) || options.scale <= 0) {
    fail(2, "--scale must be a positive number");
  }

  const htmlPath = resolve(options.html);
  if (!existsSync(htmlPath)) fail(2, `html file not found: ${htmlPath}`);

  options.out = resolve(options.out);
  mkdirSync(options.out, { recursive: true });

  const driver = await loadDriver();
  if (!driver) {
    fail(
      2,
      "no browser automation module found.\n" +
        "Install playwright or puppeteer-core so it resolves from this directory, " +
        "or render the diagrams another way and attach the images by hand.",
    );
  }

  options.browserPath = findBrowser(options.browser);
  if (driver.kind === "puppeteer-core" && !options.browserPath) {
    fail(
      2,
      "no Chromium-based browser executable found.\n" +
        "Pass --browser PATH, or set CHROME_PATH.",
    );
  }

  const url = pathToFileURL(htmlPath).href;
  const captured =
    driver.kind === "playwright"
      ? await capturePlaywright(driver, options, url)
      : await capturePuppeteer(driver, options, url);

  process.stdout.write(
    `${JSON.stringify({ ok: captured.length > 0, driver: driver.kind, captured }, null, 2)}\n`,
  );

  if (captured.length === 0) {
    process.stderr.write(`no element matched selector: ${options.selector}\n`);
    process.exit(1);
  }

  process.exit(0);
}

const invokedDirectly =
  process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (invokedDirectly) {
  main().catch((error) => fail(2, error?.stack ?? String(error)));
}
