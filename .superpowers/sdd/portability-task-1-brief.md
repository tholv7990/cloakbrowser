### Task 1: Versioned profile export/import

**Files:**
- Create: `manager_backend/features/portability/schemas.py`
- Create: `manager_backend/features/portability/profiles.py`
- Create: `manager_backend/features/portability/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_profile_portability.py`

**Interfaces:**
- Produces: `export_profile(session, id) -> ProfileExportV1`; `import_profile(session, settings, document) -> ProfileImportResult`.

- [ ] Write failing tests for deterministic schema, secret/path/ID exclusion, 2 MiB limit, bad version, catalog resolution, collision naming, fresh UUID/seed, warnings, and rollback.
- [ ] Run the focused test and confirm import symbols/routes are missing.
- [ ] Implement strict Pydantic export/import models, `Content-Disposition` download, and one transaction. Proxy metadata generates a warning and no assignment.
- [ ] Require explicit format/version, filter machine-specific extension startup URLs, bound safe validation errors, and require trusted `ManagerSettings` for directory creation.
- [ ] Reserve the SQLite writer transaction before deterministic indexed catalog/name resolution so concurrent imports cannot duplicate normalized catalogs or collision names.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): add profile import and export"`.
