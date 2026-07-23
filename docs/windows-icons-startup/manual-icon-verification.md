# Manual Windows taskbar-icon verification

CI cannot observe the Windows taskbar/compositor, so icon behavior is verified by hand.
Run each step on Windows 10/11, record PASS/FAIL, and attach the requested screenshot.

**Environment to record:** Windows version/build, dev vs packaged build, DPI/scale,
`%LOCALAPPDATA%\Plasma` (or `…\CloakBrowser\Manager`) present, monitor count.

| # | Action | Expected | Screenshot |
|---|---|---|---|
| 1 | Open Plasma (the app window) | App window + its taskbar button show the **Plasma** icon, not a generic/Chrome icon | taskbar with Plasma running |
| 2 | (Packaged build) look at the taskbar while the backend runs | **No** separate Python/console taskbar entry (sidecar is windowless) | full taskbar |
| 3 | Start one profile; watch the taskbar as the window appears | Its button shows the **Plasma dart** within ~1 frame; at most a single brief born-frame of Chrome's icon, then stable | slow-mo/burst capture of the first ~500 ms if possible |
| 4 | Let the profile finish loading a page | Icon **stays** the Plasma dart (does not switch back after load) | taskbar after load |
| 5 | Start a **second** profile | Two **separate** taskbar buttons (per-profile AUMID), each the Plasma dart — not merged into one Chrome group | taskbar with 2 profiles |
| 6 | Hover/peek each profile button | Each is its own window with its own thumbnail; grouping matches the documented per-profile policy | thumbnail peek |
| 7 | Close and reopen a profile | Icon behavior identical to step 3 (survives restart) | — |
| 8 | Restart the whole Plasma app, reopen a profile | Same icon behavior (no icon-cache staleness) | — |
| 9 | Pin the Plasma app to the taskbar/Start; relaunch from the pin | Pinned shortcut shows the Plasma icon; launching from it still brands correctly | pinned icon |
| 10 | Confirm the browser still works end-to-end | Fingerprint/proxy behavior unchanged; **no** CloakBrowser verification error in logs; binary not modified | — |

**Known/accepted limitation:** step 3 may show a single ~1-frame flash of the CloakBrowser
binary's own icon at window creation (the "born-frame"). Eliminating even that frame would require
modifying the verified binary, which is prohibited. A stable dart after that frame is PASS.

**If step 5 shows one merged group:** the per-profile AUMID isn't landing — check
`window_icon._set_taskbar_identity` succeeded (it is best-effort and swallows failures); capture the
window's `System.AppUserModel.ID` with a tool like NirSoft `GetWindowInfo`/`propsys` and attach.

**If step 2 shows a console entry (dev build):** expected in `uvicorn` dev mode; only the **packaged**
build hides the sidecar. Note which build was tested.
