import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const { parseArgs, outputName, planOutputs, capturePlaywright, capturePuppeteer, VIEWPORT } =
  await import(join(here, "..", "scripts", "render_diagrams.mjs"));

const OUT = "/tmp/out";

test("strip-prefix removes only a leading prefix", () => {
  assert.equal(outputName("dia-x", "dia-"), "x");
  assert.equal(outputName("mydia-x", "dia-"), "mydia-x");
  assert.equal(outputName("plain", ""), "plain");
});

test("unsafe ids fail before capture", () => {
  for (const id of ["../etc", "a/b", "a b", "x..y", "с-кир"]) {
    assert.throws(() => planOutputs([id], { out: OUT, stripPrefix: "" }), /not safe for a file name/);
  }
});

test("duplicate output names fail before capture", () => {
  assert.throws(
    () => planOutputs(["dia-a", "a"], { out: OUT, stripPrefix: "dia-" }),
    /duplicate output name "a"/,
  );
  assert.throws(() => planOutputs(["a", "a"], { out: OUT, stripPrefix: "" }), /duplicate/);
});

test("prefix that consumes the whole id fails", () => {
  assert.throws(() => planOutputs(["dia-"], { out: OUT, stripPrefix: "dia-" }), /becomes empty/);
});

test("missing ids get positional names and paths sit under the output directory", () => {
  const plan = planOutputs(["", "dia-flow"], { out: OUT, stripPrefix: "dia-" });
  assert.deepEqual(
    plan.map((p) => [p.name, p.path]),
    [
      ["diagram-1", join(OUT, "diagram-1.png")],
      ["flow", join(OUT, "flow.png")],
    ],
  );
});

test("--no-sandbox is off unless requested", () => {
  assert.equal(parseArgs(["--html", "a", "--out", "b"]).noSandbox, false);
  assert.equal(parseArgs(["--html", "a", "--out", "b", "--no-sandbox"]).noSandbox, true);
});

function fakePlaywright(ids, { failOn } = {}) {
  const calls = { closed: 0, launchArgs: null, context: null, screenshots: [] };
  const handles = ids.map((id) => ({
    getAttribute: async () => id,
    screenshot: async ({ path }) => {
      if (failOn && path.endsWith(failOn)) throw new Error("screenshot failed");
      calls.screenshots.push(path);
    },
  }));
  const driver = {
    module: {
      chromium: {
        launch: async (launchOptions) => {
          calls.launchArgs = launchOptions.args;
          return {
            newContext: async (contextOptions) => {
              calls.context = contextOptions;
              return {
                newPage: async () => ({
                  goto: async () => {},
                  evaluate: async () => true,
                  locator: () => ({ all: async () => handles }),
                }),
              };
            },
            close: async () => {
              calls.closed += 1;
            },
          };
        },
      },
    },
  };
  return { driver, calls };
}

test("playwright: browser is closed even when a capture throws", async () => {
  const { driver, calls } = fakePlaywright(["a", "b"], { failOn: "b.png" });
  await assert.rejects(
    capturePlaywright(driver, { out: OUT, stripPrefix: "", scale: 2, noSandbox: false, selector: ".d" }, "file:///x"),
    /screenshot failed/,
  );
  assert.equal(calls.closed, 1);
});

test("playwright: duplicate ids capture nothing and still close the browser", async () => {
  const { driver, calls } = fakePlaywright(["a", "a"]);
  await assert.rejects(
    capturePlaywright(driver, { out: OUT, stripPrefix: "", scale: 2, noSandbox: false, selector: ".d" }, "file:///x"),
    /duplicate/,
  );
  assert.equal(calls.screenshots.length, 0);
  assert.equal(calls.closed, 1);
});

test("playwright: shared viewport and sandbox flag", async () => {
  const { driver, calls } = fakePlaywright(["a"]);
  const captured = await capturePlaywright(
    driver,
    { out: OUT, stripPrefix: "", scale: 3, noSandbox: true, selector: ".d" },
    "file:///x",
  );
  assert.deepEqual(captured, [{ name: "a", path: join(OUT, "a.png") }]);
  assert.deepEqual(calls.launchArgs, ["--no-sandbox"]);
  assert.deepEqual(calls.context, { viewport: VIEWPORT, deviceScaleFactor: 3 });
  assert.equal(calls.closed, 1);
});

test("puppeteer: browser is closed when the page fails and viewport matches playwright", async () => {
  const calls = { closed: 0, viewport: null, launchArgs: null };
  const driver = {
    module: {
      launch: async (launchOptions) => {
        calls.launchArgs = launchOptions.args;
        return {
          newPage: async () => ({
            setViewport: async (viewport) => {
              calls.viewport = viewport;
            },
            goto: async () => {
              throw new Error("navigation failed");
            },
          }),
          close: async () => {
            calls.closed += 1;
          },
        };
      },
    },
  };
  await assert.rejects(
    capturePuppeteer(driver, { out: OUT, stripPrefix: "", scale: 2, noSandbox: false, selector: ".d" }, "file:///x"),
    /navigation failed/,
  );
  assert.equal(calls.closed, 1);
  assert.deepEqual(calls.launchArgs, []);
  assert.deepEqual(calls.viewport, { ...VIEWPORT, deviceScaleFactor: 2 });
});
