# CloakBrowser Manager Profile Field Capability Matrix

This matrix is the implementation boundary for the Windows-only profile manager. It prevents the UI from copying controls shown by other antidetect products when the CloakBrowser engine does not provide an equivalent tested capability.

| Area | Field or control | V1 decision | CloakBrowser mapping |
|---|---|---|---|
| General | Name, folder, status, tags, notes | Include | Manager metadata |
| General | Multiple startup URLs | Include | Open after persistent context launch |
| Accounts | Website username/password | Exclude | Browser login state persists in user-data; manager is not a vault |
| Accounts | 2FA secret | Exclude | High-value secret with no browser-launch purpose |
| Identity | Platform/browser selector | Fixed | Windows + CloakBrowser Chromium |
| Identity | Windows 10/11 selector | Exclude | Engine exposes only `--fingerprint-platform=windows` |
| Identity | Stable seed | Include | `--fingerprint=<seed>` |
| Identity | Consistent preset | Include/default | `fingerprint_preset="consistent"` |
| Identity | Regenerate every launch | Exclude | Breaks persistent identity; regeneration is explicit only |
| Identity | Browser version | Installed or pinned | `browser_version` |
| Identity | User agent | Automatic; advanced custom | `user_agent`, with mismatch warning |
| Proxy | Direct/HTTP/HTTPS/SOCKS5/SOCKS5H | Include | Existing proxy resolver and auth relay |
| Location | Auto from proxy | Include/default with proxy | `geoip=True` resolves locale/timezone/exit IP |
| Location | Locale/timezone | Include | `locale`, `timezone` binary flags |
| Location | WebRTC proxy alignment | Include/default with proxy | `--fingerprint-webrtc-ip=<exit-ip>` |
| Location | Manual geolocation/permission | Include | Validated Playwright context settings |
| Window | Headed mode | Fixed for V1 | Persistent headed context |
| Window | Maximized/custom size | Include | Real window geometry or validated window arguments |
| Window | Independent screen spoof | Exclude | Risks impossible screen/outer/inner combinations |
| Appearance | Color scheme | Include | `color_scheme` |
| Hardware | Hardware concurrency | Advanced | `--fingerprint-hardware-concurrency` |
| Hardware | GPU vendor | Advanced | `--fingerprint-gpu-vendor` |
| Hardware | GPU renderer | Exclude | No tested independent engine control |
| Hardware | Device memory | Exclude | No dedicated engine control |
| Fingerprint | Canvas/WebGL image/audio/client rect toggles | Exclude | Seed and binary own coherent surfaces |
| Fingerprint | Fonts/speech/media devices/plugins | Exclude | No tested independent V1 controls |
| Device | Device name/MAC/host LAN IP | Exclude | Not engine-supported and not needed for normal web fingerprints |
| Behavior | Humanization | Include | `humanize`, `human_preset` |
| Behavior | Clear cache before launch | Include/off by default | Manager operation while profile is stopped |
| Behavior | Restore tabs | Include | Persistent profile policy |
| Behavior | Disable GPU | Exclude | Harms performance and may create a suspicious renderer |
| Behavior | Ignore HTTPS errors | Advanced/off | Playwright context option with warning |
| Behavior | Extra Chromium arguments | Advanced | Allowlist/denylist; manager-owned flags blocked |
| Storage | Cookies/storage state | Import/export | Stored in profile user-data, never the main DB row |
| Runtime | Multiple simultaneous instances | Fixed false | One owned session per profile |
| Extensions | Unpacked local extensions | Include | `extension_paths` after manifest/path validation |

## Canonical V1 profile groups

The API exposes structured groups named `location`, `window`, and `behavior`. These groups use Pydantic models with unknown fields forbidden. They are not arbitrary JSON escape hatches.

The normal creation path asks only for a name, optional organization metadata, proxy, and startup URLs. Advanced fingerprint overrides remain collapsed and display consistency warnings.
