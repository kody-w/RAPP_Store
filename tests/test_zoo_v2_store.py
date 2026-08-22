"""Security and lifecycle tests for the RAPP Zoo Store v2 extension."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

import zoo_v2_store as zoo


COMMIT = "a" * 40
ARTIFACT = b'print("submitted bytes are inert")\n'
MIT = b"""MIT License

Copyright (c) 2026 Synthetic Example

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""
ARTIFACT_URL = (
    f"https://raw.githubusercontent.com/example/synthetic/{COMMIT}/prototype.py"
)
LICENSE_URL = f"https://raw.githubusercontent.com/example/synthetic/{COMMIT}/LICENSE"
CURRENT_URL = (
    f"https://raw.githubusercontent.com/kody-w/RAPP_Store/{COMMIT}/"
    "api/v2/generations/issue-1.json"
)


def _fetcher(routes):
    def fetch(url):
        if url not in routes:
            raise zoo.StoreError(f"E_FETCH: no test route for {url}")
        return routes[url]
    return fetch


def _prototype(version="0.1.0", artifact=ARTIFACT):
    digest = zoo.sha256_bytes(artifact)
    return {
        "id": "synthetic-example",
        "name": "Synthetic Example",
        "version": version,
        "summary": "A synthetic, non-production prototype.",
        "status": "prototype",
        "artifact": {
            "url": ARTIFACT_URL,
            "sha256": digest,
            "media_type": "text/x-python",
        },
        "license": {
            "spdx": "MIT",
            "evidence_url": LICENSE_URL,
            "evidence_sha256": zoo.sha256_bytes(MIT),
        },
        "wire_contract": "RAPP/1",
        "identity": f"rappid:@synthetic/synthetic-example:{digest}",
        "ecosystem_acceptance": "not-asserted",
        "external_blockers": [
            "Independent RAPP/1 conformance and ecosystem admission are incomplete."
        ],
    }


def _generation(prototypes=None, tombstones=None):
    return {
        "schema": zoo.GENERATION_SCHEMA,
        "generation_id": "issue-1",
        "created_at": "2026-08-22T19:16:00Z",
        "source_issue": 1,
        "previous_generation_url": None,
        "prototypes": prototypes or [],
        "tombstones": tombstones or [],
    }


def _command(operation, prototype=None, reason=None):
    result = {
        "schema": zoo.COMMAND_SCHEMA,
        "operation": operation,
        "id": "synthetic-example",
    }
    if prototype is not None:
        result["prototype"] = prototype
    if reason is not None:
        result["reason"] = reason
    return result


def _routes(artifact=ARTIFACT):
    return {ARTIFACT_URL: artifact, LICENSE_URL: MIT}


class TestSecurityMutations:
    def test_issue_and_artifact_content_are_never_executed(self, monkeypatch):
        malicious = b'import os\nos.system("touch should-not-exist")\n'
        prototype = _prototype(artifact=malicious)
        body = "```json\n" + json.dumps(_command("create", prototype)) + "\n```"
        called = []
        monkeypatch.setattr(os, "system", lambda value: called.append(value))

        parsed = zoo.validate_command(
            zoo.parse_issue_command(body),
            "[ZOO V2 CREATE] synthetic-example",
        )
        result = zoo.apply_command(
            _generation(),
            CURRENT_URL,
            parsed,
            issue_number=2,
            timestamp="2026-08-22T19:17:00Z",
            fetcher=_fetcher(_routes(malicious)),
        )
        assert result["prototypes"][0]["artifact"]["sha256"] == zoo.sha256_bytes(malicious)
        assert called == []

    @pytest.mark.parametrize("url", [
        "https://raw.githubusercontent.com/example/synthetic/main/prototype.py",
        "https://raw.githubusercontent.com/example/synthetic/aaaaaaaa/prototype.py",
        f"https://raw.githubusercontent.com/example/synthetic/{COMMIT.upper()}/prototype.py",
        f"https://raw.githubusercontent.com/example/synthetic/{COMMIT}/../prototype.py",
        f"https://raw.githubusercontent.com/example/synthetic/{COMMIT}/prototype.py?mutable=1",
    ])
    def test_mutable_or_non_exact_raw_url_rejected(self, url):
        prototype = _prototype()
        prototype["artifact"]["url"] = url
        with pytest.raises(zoo.StoreError, match="E_PINNED_URL"):
            zoo.validate_prototype(prototype, _fetcher(_routes()))

    def test_missing_license_rejected(self):
        prototype = _prototype()
        del prototype["license"]
        with pytest.raises(zoo.StoreError, match="missing license"):
            zoo.validate_prototype(prototype, _fetcher(_routes()))

    def test_non_mit_first_license_rejected(self):
        prototype = _prototype()
        prototype["license"]["spdx"] = "Apache-2.0 OR MIT"
        with pytest.raises(zoo.StoreError, match="E_LICENSE_NOT_MIT_FIRST"):
            zoo.validate_prototype(prototype, _fetcher(_routes()))

    def test_artifact_hash_drift_rejected(self):
        with pytest.raises(zoo.StoreError, match="E_HASH_DRIFT"):
            zoo.validate_prototype(_prototype(), _fetcher(_routes(b"changed")))

    def test_delete_rejected_but_deprecate_appends_tombstone(self):
        current = _generation([_prototype()])
        with pytest.raises(zoo.StoreError, match="E_OPERATION"):
            zoo.validate_command(
                _command("delete"),
                "[ZOO V2 DEPRECATE] synthetic-example",
            )

        command = zoo.validate_command(
            _command("deprecate", reason="Superseded by another synthetic fixture."),
            "[ZOO V2 DEPRECATE] synthetic-example",
        )
        result = zoo.apply_command(
            current,
            CURRENT_URL,
            command,
            issue_number=3,
            timestamp="2026-08-22T19:18:00Z",
            fetcher=_fetcher(_routes()),
        )
        assert result["prototypes"] == []
        assert result["tombstones"][0]["id"] == "synthetic-example"
        assert result["tombstones"][0]["last_artifact_sha256"] == _prototype()["artifact"]["sha256"]

        destructively_removed = deepcopy(result)
        destructively_removed["tombstones"] = []
        with pytest.raises(zoo.StoreError, match="E_DESTRUCTIVE_DELETE"):
            zoo.validate_generation(
                destructively_removed,
                fetcher=_fetcher(_routes()),
                previous=current,
            )

    def test_identity_hash_must_bind_artifact(self):
        prototype = _prototype()
        prototype["identity"] = "rappid:@synthetic/synthetic-example:" + "f" * 64
        with pytest.raises(zoo.StoreError, match="E_IDENTITY_HASH"):
            zoo.validate_prototype(prototype, _fetcher(_routes()))

    def test_prior_tombstone_mutation_rejected(self):
        tombstone = {
            "id": "old-prototype",
            "status": "deprecated",
            "reason": "Old synthetic entry.",
            "deprecated_at": "2026-08-01T00:00:00Z",
            "source_issue": 8,
            "last_version": "0.1.0",
            "last_artifact_sha256": "b" * 64,
        }
        previous = _generation(tombstones=[tombstone])
        current = deepcopy(previous)
        current["generation_id"] = "issue-9"
        current["source_issue"] = 9
        current["tombstones"][0]["reason"] = "rewritten"
        with pytest.raises(zoo.StoreError, match="E_TOMBSTONE_APPEND_ONLY"):
            zoo.validate_generation(
                current,
                network=False,
                previous=previous,
            )


class TestCrudAndPointer:
    def test_create_then_update_requires_higher_version(self):
        create = zoo.validate_command(
            _command("create", _prototype()),
            "[ZOO V2 CREATE] synthetic-example",
        )
        created = zoo.apply_command(
            _generation(),
            CURRENT_URL,
            create,
            issue_number=2,
            timestamp="2026-08-22T19:17:00Z",
            fetcher=_fetcher(_routes()),
        )
        same = zoo.validate_command(
            _command("update", _prototype()),
            "[ZOO V2 UPDATE] synthetic-example",
        )
        with pytest.raises(zoo.StoreError, match="E_VERSION_NOT_BUMPED"):
            zoo.apply_command(
                created,
                CURRENT_URL,
                same,
                issue_number=3,
                timestamp="2026-08-22T19:18:00Z",
                fetcher=_fetcher(_routes()),
            )

        update = zoo.validate_command(
            _command("update", _prototype("0.2.0")),
            "[ZOO V2 UPDATE] synthetic-example",
        )
        updated = zoo.apply_command(
            created,
            CURRENT_URL,
            update,
            issue_number=3,
            timestamp="2026-08-22T19:18:00Z",
            fetcher=_fetcher(_routes()),
        )
        assert updated["prototypes"][0]["version"] == "0.2.0"

    def test_update_cannot_erase_external_blocker(self):
        current = _generation([_prototype()])
        replacement = _prototype("0.2.0")
        replacement["external_blockers"] = ["A less specific replacement blocker."]
        update = zoo.validate_command(
            _command("update", replacement),
            "[ZOO V2 UPDATE] synthetic-example",
        )
        with pytest.raises(zoo.StoreError, match="E_EXTERNAL_BLOCKERS"):
            zoo.apply_command(
                current,
                CURRENT_URL,
                update,
                issue_number=3,
                timestamp="2026-08-22T19:18:00Z",
                fetcher=_fetcher(_routes()),
            )

    def test_actor_allowlist_is_exact_and_case_insensitive(self):
        actors = zoo.parse_allowlist("kody-w, Allowed-Bot")
        zoo.validate_actor("allowed-bot", actors)
        with pytest.raises(zoo.StoreError, match="E_ACTOR_NOT_ALLOWED"):
            zoo.validate_actor("not-allowed", actors)

    def test_discovery_only_names_a_commit_pinned_generation(self):
        pointer = {"schema": zoo.DISCOVERY_SCHEMA, "generation_url": CURRENT_URL}
        assert zoo.validate_discovery(pointer) == CURRENT_URL
        pointer["count"] = 1
        with pytest.raises(zoo.StoreError, match="unknown fields"):
            zoo.validate_discovery(pointer)

    def test_pin_discovery_writes_canonical_pointer(self, tmp_path):
        output = tmp_path / "discovery.json"
        zoo.pin_discovery(
            "kody-w/RAPP_Store",
            COMMIT,
            "api/v2/generations/issue-2.json",
            output,
        )
        pointer = json.loads(output.read_text())
        assert set(pointer) == {"schema", "generation_url"}
        assert f"/{COMMIT}/api/v2/generations/issue-2.json" in pointer["generation_url"]
        assert output.read_bytes() == zoo.canonical_json(pointer)

    def test_schema_documents_are_valid_json(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("command", "discovery", "generation"):
            schema = json.loads(
                (root / "schemas" / "zoo-v2" / f"{name}.schema.json").read_text()
            )
            assert schema["$schema"].endswith("2020-12/schema")

    def test_storefront_has_additive_prototype_loader_and_dial(self):
        page = (Path(__file__).resolve().parent.parent / "index.html").read_text()
        assert "loadPrototypes()" in page
        assert "Dial prototype" in page
        assert "rapp-zoo-prototype-summon/2.0" in page
