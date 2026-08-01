/**
 * Shared argument builder for Playwright and Puppeteer wrappers.
 */
import path from "path";
import type { LaunchOptions } from "./types.js";
import { getDefaultStealthArgs, binarySupportsMaximizedWindow } from "./config.js";

const DEBUG = /\bcloakbrowser\b/.test(process.env.DEBUG ?? "");

function normalizeFingerprintString(name: string, value: unknown): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${name} must be a non-empty string`);
  }
  return value.trim();
}

function normalizeFingerprintInteger(
  name: string,
  value: unknown,
  minimum: number,
  maximum: number,
): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer from ${minimum} through ${maximum}`);
  }
  return value;
}

function appendFingerprintOverride(seen: Map<string, string>, key: string, value: string | number): void {
  seen.delete(key);
  seen.set(key, `${key}=${value}`);
}

function normalizedFingerprintOverrides(options: LaunchOptions) {
  return [
    ["--fingerprint-gpu-vendor", normalizeFingerprintString("gpuVendor", options.gpuVendor)],
    ["--fingerprint-gpu-renderer", normalizeFingerprintString("gpuRenderer", options.gpuRenderer)],
    [
      "--fingerprint-hardware-concurrency",
      normalizeFingerprintInteger("hardwareConcurrency", options.hardwareConcurrency, 1, 1024),
    ],
    ["--fingerprint-device-memory", normalizeFingerprintInteger("deviceMemory", options.deviceMemory, 1, 1024)],
    ["--fingerprint-screen-width", normalizeFingerprintInteger("screenWidth", options.screenWidth, 320, 16384)],
    ["--fingerprint-screen-height", normalizeFingerprintInteger("screenHeight", options.screenHeight, 320, 16384)],
    ["--fingerprint-brand", normalizeFingerprintString("brand", options.brand)],
  ] as const;
}

/** Validate dedicated fingerprint overrides without resolving or launching anything. */
export function validateFingerprintOverrides(options: LaunchOptions): void {
  normalizedFingerprintOverrides(options);
}

/**
 * Build deduplicated Chromium CLI args from stealth defaults + user overrides.
 *
 * Priority: stealth defaults < user args < timezone/locale < dedicated fingerprint
 * overrides < extensions/window-management flags.
 */
export function buildArgs(options: LaunchOptions): string[] {
  const seen = new Map<string, string>();

  const preset = options.fingerprintPreset ?? "default";
  if (preset !== "default" && preset !== "consistent") {
    throw new Error(`fingerprintPreset must be "default" or "consistent", got ${JSON.stringify(preset)}`);
  }

  if (options.stealthArgs !== false) {
    for (const arg of getDefaultStealthArgs()) {
      seen.set(arg.split("=")[0], arg);
    }
  }
  if (preset === "consistent") {
    seen.set("--fingerprint-noise", "--fingerprint-noise=false");
    if ((options as { userDataDir?: string }).userDataDir) {
      seen.set("--fingerprint-storage-quota", "--fingerprint-storage-quota=10240");
    }
  }
  // GPU blocklist bypass:
  // - Headed mode (all platforms): Chromium blocks WebGL on software GPUs
  //   in Docker/Xvfb. Flag lets SwiftShader serve WebGL. See issue #56.
  // - Windows (all modes): Chromium's GPU blocklist blocks WebGPU for the
  //   Microsoft Basic Render Driver. Dawn's adapter_blocklist bypass alone
  //   isn't enough. Linux doesn't need it.
  if (options.headless === false || process.platform === "win32") {
    seen.set("--ignore-gpu-blocklist", "--ignore-gpu-blocklist");
  }
  if (options.args) {
    for (const arg of options.args) {
      const key = arg.split("=")[0];
      if (seen.has(key)) {
        if (DEBUG) console.debug(`[cloakbrowser] Arg override: ${seen.get(key)} -> ${arg}`);
      }
      seen.set(key, arg);
    }
  }
  if (options.timezone) {
    const key = "--fingerprint-timezone";
    const flag = `${key}=${options.timezone}`;
    if (seen.has(key)) {
      if (DEBUG) console.debug(`[cloakbrowser] Arg override: ${seen.get(key)} -> ${flag}`);
    }
    seen.set(key, flag);
  }
  if (options.locale) {
    for (const k of ["--lang", "--fingerprint-locale"] as const) {
      const flag = `${k}=${options.locale}`;
      if (seen.has(k)) {
        if (DEBUG) console.debug(`[cloakbrowser] Arg override: ${seen.get(k)} -> ${flag}`);
      }
      seen.set(k, flag);
    }
  }

  for (const [key, value] of normalizedFingerprintOverrides(options)) {
    if (value !== undefined) appendFingerprintOverride(seen, key, value);
  }

  if (options.extensionPaths?.length) {
    const absPaths = options.extensionPaths.map(p => path.resolve(p));
    const joined = absPaths.join(",");

    seen.set("--load-extension", `--load-extension=${joined}`);
    seen.set(
      "--disable-extensions-except",
      `--disable-extensions-except=${joined}`
    );
  }

  // Open maximized (real Chrome overwhelmingly runs maximized) so the window
  // fills the spoofed screen. Skipped if the caller chose a window geometry or an
  // explicit viewport (Playwright `viewport` / Puppeteer `defaultViewport`).
  // Gated to binaries where this stays coherent (see binarySupportsMaximizedWindow)
  // — below the gate it would make outerWidth < innerWidth.
  // viewport lives on LaunchContextOptions; present at runtime for the
  // persistent-context path, absent for plain launch. Read defensively.
  const explicitViewport =
    (options as { viewport?: unknown }).viewport !== undefined ||
    options.launchOptions?.defaultViewport !== undefined;
  const hasWindowFlag = ["--start-maximized", "--window-size", "--window-position"].some(
    k => seen.has(k)
  );
  if (
    !explicitViewport &&
    !hasWindowFlag &&
    binarySupportsMaximizedWindow(options.licenseKey, options.browserVersion)
  ) {
    seen.set("--start-maximized", "--start-maximized");
  }
  return [...seen.values()];
}
