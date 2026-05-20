"""
OpenClaw Colony — DEV_COMMIT_INIT Tests
=========================================
Tests the Genesis startup sequence end-to-end.
Covers idempotency, secret validation, genesis block structure,
state machine wiring, and DB commit.
"""

import hashlib
import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend is on path (conftest.py also does this, but be explicit)
_backend = os.path.join(os.path.dirname(__file__), "..", "backend")
if os.path.abspath(_backend) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend))

# Set dev-safe defaults BEFORE importing the module under test
os.environ.setdefault("COLONY_DB_PATH", ":memory:")
os.environ.setdefault("COLONY_DEV_MODE", "true")
os.environ.setdefault("COLONY_NODE_ID", "test-node-genesis")
os.environ.setdefault("COLONY_NODE_URL", "http://localhost:8000")

from dev_commit_init import (
    validate_secrets,
    create_genesis_block,
    commit_genesis,
    dev_commit_init,
    SecretValidationError,
    GENESIS_TASK_ID,
    GENESIS_PREV_HASH,
    GENESIS_DESCRIPTION,
    _compute_genesis_hash,
)


# ══════════════════════════════════════════════════════════════════════════════
# Secret Validation Tests
# Note: validate_secrets() reads os.environ at call time, so patch.dict works.
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateSecrets:

    def test_dev_mode_no_raise_on_missing_secrets(self):
        """In dev mode (strict=False), missing secrets emit warnings but do not raise."""
        with patch.dict(os.environ, {"COLONY_BAS_SECRET": "", "COLONY_ADMIN_KEY": ""}):
            result = validate_secrets(strict=False)
        assert "COLONY_BAS_SECRET" in result
        assert "MISSING" in result["COLONY_BAS_SECRET"]

    def test_strict_mode_raises_on_missing_bas_secret(self):
        """In strict mode, missing BAS_SECRET raises SecretValidationError."""
        with patch.dict(os.environ, {
            "COLONY_BAS_SECRET": "",
            "COLONY_ADMIN_KEY": "validkey123456"
        }):
            with pytest.raises(SecretValidationError):
                validate_secrets(strict=True)

    def test_strict_mode_raises_on_missing_admin_key(self):
        """In strict mode, missing ADMIN_KEY raises SecretValidationError."""
        with patch.dict(os.environ, {
            "COLONY_BAS_SECRET": "a" * 32,
            "COLONY_ADMIN_KEY": ""
        }):
            with pytest.raises(SecretValidationError):
                validate_secrets(strict=True)

    def test_strict_mode_raises_on_weak_bas_secret(self):
        """BAS_SECRET shorter than 32 chars is flagged as weak in strict mode."""
        with patch.dict(os.environ, {
            "COLONY_BAS_SECRET": "tooshort",
            "COLONY_ADMIN_KEY": "validkey123456"
        }):
            with pytest.raises(SecretValidationError):
                validate_secrets(strict=True)

    def test_valid_secrets_pass_strict_mode(self):
        """Valid secrets pass strict validation without raising."""
        with patch.dict(os.environ, {
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "validadminkey",
            "COLONY_NODE_URL": "https://node001.openclaw.net",
            "COLONY_NODE_ID": "node-custom-001",
        }):
            result = validate_secrets(strict=True)
        assert result["COLONY_BAS_SECRET"] == "OK"
        assert result["COLONY_ADMIN_KEY"] == "OK"

    def test_returns_dict_with_all_keys(self):
        """Result dict must contain entries for all checked variables."""
        with patch.dict(os.environ, {
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "validkey"
        }):
            result = validate_secrets(strict=False)
        assert "COLONY_BAS_SECRET" in result
        assert "COLONY_ADMIN_KEY" in result
        assert "COLONY_NODE_ID" in result
        assert "COLONY_NODE_URL" in result
        assert "COLONY_PEERS" in result

    def test_localhost_url_flagged_as_local(self):
        """localhost NODE_URL is flagged but not an error."""
        with patch.dict(os.environ, {
            "COLONY_NODE_URL": "http://localhost:8000",
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "key"
        }):
            result = validate_secrets(strict=False)
        assert "LOCAL" in result["COLONY_NODE_URL"]

    def test_public_url_passes(self):
        """Public HTTPS URL is marked OK."""
        with patch.dict(os.environ, {
            "COLONY_NODE_URL": "https://node001.openclaw.net",
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "key"
        }):
            result = validate_secrets(strict=False)
        assert "OK" in result["COLONY_NODE_URL"]

    def test_default_node_id_flagged(self):
        """Default node ID is flagged as DEFAULT."""
        with patch.dict(os.environ, {
            "COLONY_NODE_ID": "node-001-bethel",
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "key"
        }):
            result = validate_secrets(strict=False)
        assert "DEFAULT" in result["COLONY_NODE_ID"]

    def test_custom_node_id_passes(self):
        """Custom node ID is marked OK."""
        with patch.dict(os.environ, {
            "COLONY_NODE_ID": "node-custom-bethel-acres",
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "key"
        }):
            result = validate_secrets(strict=False)
        assert "OK" in result["COLONY_NODE_ID"]

    def test_peers_count_in_result(self):
        """Peer count is reported correctly."""
        with patch.dict(os.environ, {
            "COLONY_PEERS": "http://peer1,http://peer2",
            "COLONY_BAS_SECRET": "a" * 64,
            "COLONY_ADMIN_KEY": "key"
        }):
            result = validate_secrets(strict=False)
        assert "2" in result["COLONY_PEERS"]


# ══════════════════════════════════════════════════════════════════════════════
# Genesis Block Creation Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateGenesisBlock:

    def test_returns_dict_with_required_fields(self):
        block = create_genesis_block(node_id="node-001")
        for field in ["task_id", "prompt_hash", "lq_composite",
                      "lineage_hash", "prev_hash", "committed_at",
                      "node_id", "description"]:
            assert field in block, f"Missing field: {field}"

    def test_task_id_is_genesis(self):
        block = create_genesis_block(node_id="node-001")
        assert block["task_id"] == GENESIS_TASK_ID

    def test_prev_hash_is_64_zeros(self):
        block = create_genesis_block(node_id="node-001")
        assert block["prev_hash"] == "0" * 64

    def test_lq_composite_is_1(self):
        """Genesis is unconditionally sovereign — LQ = 1.0."""
        block = create_genesis_block(node_id="node-001")
        assert block["lq_composite"] == 1.0

    def test_lineage_hash_is_64_hex_chars(self):
        block = create_genesis_block(node_id="node-001")
        h = block["lineage_hash"]
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_prompt_hash_matches_description(self):
        block = create_genesis_block(node_id="node-001")
        expected = hashlib.sha256(GENESIS_DESCRIPTION.encode()).hexdigest()
        assert block["prompt_hash"] == expected

    def test_committed_at_is_timezone_aware(self):
        block = create_genesis_block(node_id="node-001")
        assert block["committed_at"].tzinfo is not None

    def test_node_id_stored_in_block(self):
        block = create_genesis_block(node_id="node-custom-001")
        assert block["node_id"] == "node-custom-001"

    def test_compute_genesis_hash_deterministic_same_inputs(self):
        """Same node_id + timestamp → same hash."""
        ts = "2026-05-20T12:00:00+00:00"
        h1 = _compute_genesis_hash("node-001", ts)
        h2 = _compute_genesis_hash("node-001", ts)
        assert h1 == h2

    def test_compute_genesis_hash_different_timestamps(self):
        """Different timestamps → different hashes."""
        h1 = _compute_genesis_hash("node-001", "2026-05-20T12:00:00+00:00")
        h2 = _compute_genesis_hash("node-001", "2026-05-20T12:00:01+00:00")
        assert h1 != h2

    def test_compute_genesis_hash_different_nodes(self):
        """Different node IDs → different hashes."""
        ts = "2026-05-20T12:00:00+00:00"
        h1 = _compute_genesis_hash("node-001", ts)
        h2 = _compute_genesis_hash("node-002", ts)
        assert h1 != h2

    def test_lineage_hash_not_all_zeros(self):
        """Genesis hash must not be the zero-anchor (that's prev_hash)."""
        block = create_genesis_block(node_id="node-001")
        assert block["lineage_hash"] != "0" * 64


# ══════════════════════════════════════════════════════════════════════════════
# Commit Genesis Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCommitGenesis:

    def _make_block(self):
        return create_genesis_block(node_id="test-node")

    def _make_db(self, existing=None):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = existing
        return mock_db

    def test_commits_fresh_genesis(self):
        """First commit returns (True, hash) and writes to DB."""
        block  = self._make_block()
        mock_db = self._make_db(existing=None)

        committed, h = commit_genesis(block, mock_db)

        assert committed is True
        assert h == block["lineage_hash"]
        assert mock_db.add.called
        assert mock_db.commit.called

    def test_idempotent_skips_existing_genesis(self):
        """Second commit returns (False, existing_hash) without writing."""
        block = self._make_block()
        existing = MagicMock()
        existing.lineage_hash = block["lineage_hash"]
        mock_db = self._make_db(existing=existing)

        committed, h = commit_genesis(block, mock_db)

        assert committed is False
        assert h == block["lineage_hash"]
        assert not mock_db.add.called
        assert not mock_db.commit.called

    def test_returned_hash_matches_block(self):
        block   = self._make_block()
        mock_db = self._make_db(existing=None)

        _, h = commit_genesis(block, mock_db)

        assert h == block["lineage_hash"]

    def test_lineage_record_created_with_correct_fields(self):
        """The LineageRecord added to DB must have correct field values."""
        block   = self._make_block()
        mock_db = self._make_db(existing=None)

        commit_genesis(block, mock_db)

        # Verify add() was called with a LineageRecord-like object
        assert mock_db.add.call_count == 1
        added = mock_db.add.call_args[0][0]
        assert added.task_id      == GENESIS_TASK_ID
        assert added.lq_composite == 1.0
        assert added.prev_hash    == "0" * 64


# ══════════════════════════════════════════════════════════════════════════════
# Full dev_commit_init() Integration Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestDevCommitInit:

    def _make_db(self, genesis_exists=False, tip_count=0):
        mock_db = MagicMock()
        if genesis_exists:
            existing = MagicMock()
            existing.lineage_hash = "a" * 64
            mock_db.query.return_value.filter_by.return_value.first.return_value = existing
        else:
            mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_db.query.return_value.count.return_value = tip_count
        return mock_db

    def _sm_patch(self, state_value="standalone"):
        """Return a mock NodeStateMachine in the given state."""
        from state_machine import NodeState
        mock_sm = MagicMock()
        mock_sm.state = NodeState(state_value)
        return mock_sm

    def test_returns_genesis_committed_on_fresh_node(self):
        mock_db = self._make_db(genesis_exists=False, tip_count=0)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        assert result["status"] == "Genesis_Committed"

    def test_returns_genesis_already_exists_on_restart(self):
        mock_db = self._make_db(genesis_exists=True, tip_count=1)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        assert result["status"] == "Genesis_Already_Exists"

    def test_result_contains_all_required_fields(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        for field in ["status", "tip", "genesis_hash", "node_id",
                      "node_url", "node_state", "peers", "dev_mode",
                      "secrets", "timestamp"]:
            assert field in result, f"Missing field: {field}"

    def test_node_state_is_valid_string(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        from state_machine import NodeState
        assert isinstance(result["node_state"], str)
        assert result["node_state"] in [s.value for s in NodeState]

    def test_genesis_hash_is_64_hex(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        h = result["genesis_hash"]
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_dev_mode_flag_in_result(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch.dict(os.environ, {"COLONY_DEV_MODE": "true"}), \
             patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        assert result["dev_mode"] is True

    def test_state_machine_already_initialised_is_reused(self):
        """If SM is already initialised, get_node_state_machine() is used."""
        mock_db = self._make_db(genesis_exists=True, tip_count=5)
        mock_sm = self._sm_patch("live")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine") as mock_init, \
             patch("dev_commit_init.get_node_state_machine", return_value=mock_sm):
            result = dev_commit_init(db=mock_db)

        mock_init.assert_not_called()
        assert result["node_state"] == "live"

    def test_federation_tables_init_failure_does_not_crash(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables", side_effect=Exception("DB error")), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        assert result["status"] == "Genesis_Committed"

    def test_biometric_tables_init_failure_does_not_crash(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables", side_effect=Exception("bio error")), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        assert result["status"] == "Genesis_Committed"

    def test_tip_reflects_db_count(self):
        mock_db = self._make_db(genesis_exists=True, tip_count=42)
        mock_sm = self._sm_patch("live")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine") as mock_init, \
             patch("dev_commit_init.get_node_state_machine", return_value=mock_sm):
            result = dev_commit_init(db=mock_db)

        assert result["tip"] == 42

    def test_timestamp_is_iso_string(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        dt = datetime.fromisoformat(result["timestamp"])
        assert dt.tzinfo is not None

    def test_peers_count_in_result(self):
        mock_db = self._make_db(genesis_exists=False)
        mock_sm = self._sm_patch("standalone")

        with patch.dict(os.environ, {"COLONY_PEERS": "http://p1,http://p2"}), \
             patch("dev_commit_init.init_federation_tables"), \
             patch("dev_commit_init.init_biometric_tables"), \
             patch("dev_commit_init.init_node_state_machine", return_value=mock_sm), \
             patch("dev_commit_init.get_node_state_machine", side_effect=RuntimeError("not init")):
            result = dev_commit_init(db=mock_db)

        assert isinstance(result["peers"], int)