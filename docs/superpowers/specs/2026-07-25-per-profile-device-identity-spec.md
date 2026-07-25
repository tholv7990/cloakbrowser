# Per-profile device identity — specification for the Chromium binary

**Status:** blocked on the binary. Nothing in this repo can implement it.
**Priority:** highest open fingerprint item, above the `innerWidth` clamp.

## The problem, measured

Two profiles launched simultaneously on one machine (different `fingerprint_seed`,
default `consistent` preset) were probed and diffed:

| Parameter | Profile A | Profile B | |
|---|---|---|---|
| canvas hash | `d296c751` | `f4a65fbc` | differs |
| font metrics | `3d0169f7` | `8c77e79f` | differs |
| **screen** | `1920x1080` | `1920x1080` | **identical** |
| **hardwareConcurrency** | `8` | `8` | **identical** |
| **deviceMemory** | `8` | `8` | **identical** |
| userAgent, platform, timezone, language, audio | — | — | **identical** |

The seed varies the hashable noise but **not the declared device**. Every profile
this product creates reports the same machine.

## Why this matters more than it looks

The threat model is not anonymity (one user avoiding uniqueness). It is
**multi-accounting**: N accounts on one platform, where the question asked is "are
these the same device?" Against that question, shared-but-common values are not
camouflage — they are a clustering key. Industry description of the failure mode:

> "A standard browser, even with multiple profiles, shares core device parameters
> across all of them — Chrome profiles, for example, do not isolate hardware
> identifiers or canvas fingerprints."

That is our current behaviour for hardware. Competitors (GoLogin: "over 50 …
parameters including … screen resolution, and CPU characteristics"; AdsPower:
per-profile "resolution … hardware-level fingerprint masking") vary these per
profile as standard.

Worse than sharing them: **randomised canvas on identical hardware is itself a
signature.** Real devices have a stable canvas. Ours varies while the device never
does — a combination that occurs in antidetect browsers and nowhere else.

## Required change

The binary must derive a **coherent device identity from the fingerprint seed** and
report it consistently.

### 1. Coherence — the hard requirement
Attributes must be drawn *jointly*, from configurations that actually exist. Never
independently randomised. Constraints that must hold:

- GPU model ↔ vendor ↔ platform (no NVIDIA/Direct3D on a reported macOS device)
- GPU tier ↔ memory tier (no RTX 4090 with 4 GB RAM)
- screen resolution ↔ devicePixelRatio ↔ available height (taskbar-consistent)
- cores ↔ memory ↔ GPU tier (a coherent machine class: office laptop, gaming desktop…)
- userAgent ↔ platform ↔ OS build
- font set ↔ platform ↔ OS version

Sampling should follow a **weighted real-device distribution**, so common machines
appear often and rare ones rarely — matching the real population rather than a
uniform spread, which would make every profile unusual.

Combination count is not a problem: ~15 resolutions × 5 core counts × 4 memory
tiers × ~40 GPUs × OS builds × font sets exceeds 10^6 without storing a single
device record. The library is the *constraint model*, not a table.

### 2. Determinism — equally hard
`seed → device` must be a pure function. The same profile must report the same
device on every launch, forever, across binary upgrades.

> "Profiles hold consistent identities across sessions, which is what platform
> detection actually tests for."

A profile whose specs drift between sessions is worse than one that never varies:
drift is an account-ban signal, not merely a fingerprint leak.

### 3. Flags to expose
Today the binary accepts only:

```
--fingerprint=<seed>  --fingerprint-noise     --fingerprint-platform
--fingerprint-locale  --fingerprint-timezone  --fingerprint-storage-quota
--fingerprint-webrtc-ip
```

Either derive the device internally from `--fingerprint=<seed>` (preferred — keeps
coherence in one place), or expose explicit flags the wrapper can pass:
`--fingerprint-screen=WxH`, `--fingerprint-cores=N`, `--fingerprint-memory=N`,
`--fingerprint-gpu=<model>`. If explicit flags are added, the binary must still
reject incoherent combinations rather than trusting the caller.

### 4. Related defect — `innerWidth` clamp
Separately: when a window is larger than the spoofed screen, `screen` and
`outerWidth/Height` are clamped but `innerWidth/innerHeight` reports the real
viewport. Measured on a 3440x1440 monitor: screen `1920x1080`, window `1920x1032`,
viewport `2984x1219` — a viewport larger than its own window, which is impossible
and a one-line check for any detector. The wrapper now caps tiling and custom
window sizes, but a **manually maximised window still leaks**.

## Wrapper responsibilities once the binary lands
1. Pass the seed (already done) and surface the resulting device in the profile UI,
   so a user can see what each profile claims.
2. Keep clamping window geometry to the profile's own screen — which becomes
   per-profile once screens vary.
3. Regenerating a profile's fingerprint must regenerate the device with it.

## Acceptance criteria
- N profiles with N seeds report N distinct devices; no two share the full set.
- Every generated device passes a coherence check (no impossible combinations).
- Relaunching a profile 10× yields byte-identical device attributes.
- The device distribution matches the real-world population: common configs common.
- CreepJS reports no lies/inconsistencies for any generated device.
- Viewport never exceeds the reported screen, including when maximised.
