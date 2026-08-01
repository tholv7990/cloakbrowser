import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("fingerprint override prelaunch validation", () => {
  const originalBinaryPath = process.env.CLOAKBROWSER_BINARY_PATH;
  let ensureBinary: ReturnType<typeof vi.fn>;
  let maybeResolveGeoip: ReturnType<typeof vi.fn>;
  let resolveWebrtcArgs: ReturnType<typeof vi.fn>;
  let playwrightLaunch: ReturnType<typeof vi.fn>;
  let playwrightPersistentLaunch: ReturnType<typeof vi.fn>;
  let puppeteerLaunch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    delete process.env.CLOAKBROWSER_BINARY_PATH;
    vi.resetModules();
    ensureBinary = vi.fn().mockResolvedValue("/fake/chrome");
    maybeResolveGeoip = vi.fn().mockResolvedValue({});
    resolveWebrtcArgs = vi.fn().mockImplementation((options) => Promise.resolve(options.args));
    playwrightLaunch = vi.fn();
    playwrightPersistentLaunch = vi.fn();
    puppeteerLaunch = vi.fn();

    vi.doMock("../src/download.js", () => ({ ensureBinary }));
    vi.doMock("../src/geoip.js", () => ({
      maybeResolveGeoip,
      resolveWebrtcArgs,
      appendWebrtcExitIp: vi.fn((args) => args),
    }));
    vi.doMock("playwright-core", () => ({
      chromium: {
        launch: playwrightLaunch,
        launchPersistentContext: playwrightPersistentLaunch,
      },
    }));
    vi.doMock("puppeteer-core", () => ({ default: { launch: puppeteerLaunch } }));
  });

  afterEach(() => {
    vi.doUnmock("../src/download.js");
    vi.doUnmock("../src/geoip.js");
    vi.doUnmock("playwright-core");
    vi.doUnmock("puppeteer-core");
    vi.resetModules();
    if (originalBinaryPath === undefined) delete process.env.CLOAKBROWSER_BINARY_PATH;
    else process.env.CLOAKBROWSER_BINARY_PATH = originalBinaryPath;
  });

  it.each([
    "buildLaunchOptions",
    "launch",
    "launchContext",
    "launchPersistentContext",
  ])("rejects before Playwright side effects in %s", async (entrypoint) => {
    const playwright = await import("../src/playwright.js");
    const options =
      entrypoint === "launchPersistentContext"
        ? { userDataDir: "/tmp/profile", gpuVendor: "   " }
        : { gpuVendor: "   " };

    await expect((playwright as any)[entrypoint](options)).rejects.toThrow("gpuVendor");

    expect(ensureBinary).not.toHaveBeenCalled();
    expect(maybeResolveGeoip).not.toHaveBeenCalled();
    expect(resolveWebrtcArgs).not.toHaveBeenCalled();
    expect(playwrightLaunch).not.toHaveBeenCalled();
    expect(playwrightPersistentLaunch).not.toHaveBeenCalled();
  });

  it.each(["launch", "launchPersistentContext"])(
    "rejects before Puppeteer side effects in %s",
    async (entrypoint) => {
      const puppeteer = await import("../src/puppeteer.js");
      const options =
        entrypoint === "launchPersistentContext"
          ? { userDataDir: "/tmp/profile", gpuVendor: "   " }
          : { gpuVendor: "   " };

      await expect((puppeteer as any)[entrypoint](options)).rejects.toThrow("gpuVendor");

      expect(ensureBinary).not.toHaveBeenCalled();
      expect(maybeResolveGeoip).not.toHaveBeenCalled();
      expect(resolveWebrtcArgs).not.toHaveBeenCalled();
      expect(puppeteerLaunch).not.toHaveBeenCalled();
    },
  );
});
