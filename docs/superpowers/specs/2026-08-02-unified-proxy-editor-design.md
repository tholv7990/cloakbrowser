# Unified Proxy Editor Design

## Objective

Use one proxy editor component for every add, edit, test, assign, and remove flow in the Manager frontend. New-profile, advanced-profile, profile-row, and proxy-catalog entry points must expose identical parsing, validation, protocol selection, credential handling, and test behavior.

## Current problem

The frontend currently splits proxy behavior between `ProxyEditorDrawer` and `ProxyInlineForm`. Existing proxies use the drawer, while new-profile and advanced-profile flows use the inline form. This duplicates state and orchestration and permits behavior to diverge.

Authenticated testing exposed two concrete risks:

- Quick Test in an existing-proxy drawer tests the saved proxy represented by `current`, not necessarily the edited values visible in the form.
- The UI says credentials are write-only, but existing password data can be rendered into the form. A stored password must never be returned to or displayed by the frontend.

## Component architecture

`ProxyEditorDrawer` becomes the only interactive proxy editor. `ProxyInlineForm` is retired after all consumers move to the drawer.

The drawer supports three explicit modes through props and state:

1. **Create** — edit and test an unsaved proxy, then persist it.
2. **Edit** — update an existing saved proxy without changing its identity.
3. **Assign** — create or select a proxy for a profile and return the saved proxy to the profile form. The caller owns the final profile save.

Profile forms render a compact proxy summary and an Add/Edit button. The button opens the same drawer used from the proxy catalog and profile table. Removing a proxy in assignment mode clears the profile's `proxy_id`; it does not delete the reusable proxy record.

## Data flow

All modes use the existing `proxyFormSchema`, `parseProxyText`, and `toProxyPayload` functions.

- Opening with no proxy initializes clean defaults plus an optional label.
- Opening with a saved proxy initializes non-secret fields and a `has_password` marker.
- Password input starts empty. An empty password preserves the stored password during edit.
- Replacing the password sends the new username/password pair.
- Explicit credential removal uses `clear_credentials=true` and a deliberate UI action.
- Create and update responses must not contain a password.

On save, the drawer calls `onSaved(proxy)`. Assignment consumers set the returned proxy ID in their profile form. Catalog/edit consumers invalidate the proxy query and close or remain open according to their existing flow.

## Test behavior

Quick Test always sends the form's current validated endpoint and credentials to the ad-hoc `/proxies/test` endpoint. This applies to both new and existing proxies, ensuring an edited host, port, scheme, username, or password is tested before save.

Full Quality Test requires persistence because the job and report are keyed by proxy ID:

- A new proxy is saved first.
- An existing proxy with dirty form values is updated first.
- The quality test then runs against that saved ID.

Quick and quality results remain visible when query invalidation returns a new proxy object with the same ID. The drawer resets only when it opens or the proxy identity changes.

## Validation and protocols

The unified editor supports `direct`, `http`, `https`, `socks5`, and `socks5h` through one schema. Paste parsing and manual entry produce the same payload. Protocol is never inferred from the port: the operator's selected or pasted scheme is authoritative.

Direct mode clears endpoint fields and disables proxy testing. Host, port, and paired credential validation remain identical in every entry point.

## Error handling

- Form validation errors remain inline and block save/test.
- Quick-test failures remain visible without closing or resetting the drawer.
- Save failures preserve all typed values.
- A failed quality-test pre-save does not start a report job.
- Background proxy-list refetches cannot erase form edits or displayed results.
- API responses containing a non-null password fail frontend contract validation and are never rendered.

## Testing

Frontend tests must cover:

- create from the new-profile flow;
- create/assign from the advanced-profile flow;
- edit from the profile table and proxy catalog;
- assignment removal without deleting the proxy;
- paste parsing for HTTP and SOCKS5;
- Quick Test using dirty current values for an existing proxy;
- Full Quality Test saving dirty values before starting;
- stored-password preservation with an empty password field;
- explicit credential replacement and clearing;
- test-result persistence across same-ID query refetches;
- no password value rendered from a saved proxy.

Backend contract tests must assert that proxy read/create/update responses never include the stored password while update requests can preserve, replace, or explicitly clear credentials.

## Scope

This change consolidates frontend proxy editing and closes credential/test consistency gaps. It does not change proxy providers, proxy network testing algorithms, profile launch behavior, or the Shop automation pipeline.
