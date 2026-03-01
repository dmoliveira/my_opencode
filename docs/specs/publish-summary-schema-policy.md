# Publish Summary Schema Policy

This policy defines versioning, compatibility, and deprecation rules for `/release-train publish` summary artifacts.

## Scope

The policy applies to:

- JSON payloads emitted by `/release-train publish --json`
- JSON files persisted via `/release-train publish --write-summary <path>`

## Schema Versioning

- Every publish summary payload MUST include `summary_schema_version`.
- `summary_schema_version` uses semantic major.minor format (`<major>.<minor>`), for example `1.0`.
- Schema versions are additive by default. New optional fields SHOULD increment the minor version.
- Breaking field changes (rename, type change, required-field removal) MUST increment the major version.

## Compatibility Guarantees

- For a given major version, existing fields MUST keep stable names and data types.
- Consumers may ignore unknown fields; producers may add optional fields without breaking compatibility.
- Producers SHOULD include stable integrity metadata (`summary_checksum`) so consumers can verify artifact content.

## Deprecation Windows

- Deprecated fields MUST remain emitted for at least one full minor release after first deprecation notice.
- A deprecation notice SHOULD be documented in the active milestone changelog and release notes.
- Field removal is allowed only in a new major schema version.

## Change Control

When schema behavior changes, update all of the following in the same PR:

- `docs/specs/publish-summary-schema-policy.md`
- `scripts/release_train_command.py`
- `scripts/selftest.py`
- relevant release-plan docs under `docs/plan/`

## Validation Baseline

At minimum, schema changes SHOULD pass:

- `make validate`
- `make selftest`
- `make install-test`
- `pre-commit run --all-files`
