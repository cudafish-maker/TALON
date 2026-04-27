"""Regression tests for core-owned attribution flows.

Kivy screen tests used to cover these paths indirectly. Active desktop work now
targets PySide6, so attribution belongs at the ``talon-core`` command boundary.
"""

import pathlib
import time

import pytest

from talon_core import TalonCoreSession
from talon_core.operators import LocalOperatorResolutionError

TEST_KEY = bytes(range(32))


def _write_config(tmp_path: pathlib.Path, mode: str) -> pathlib.Path:
    data_dir = tmp_path / f"{mode}-data"
    rns_dir = tmp_path / f"{mode}-rns"
    documents_dir = tmp_path / f"{mode}-documents"
    config_path = tmp_path / f"{mode}.ini"
    config_path.write_text(
        "\n".join(
            [
                "[talon]",
                f"mode = {mode}",
                "",
                "[paths]",
                f"data_dir = {data_dir}",
                f"rns_config_dir = {rns_dir}",
                "",
                "[documents]",
                f"storage_path = {documents_dir}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def _seed_client_operator(session: TalonCoreSession, operator_id: int = 2) -> None:
    now = int(time.time())
    session.conn.execute(
        "INSERT OR REPLACE INTO operators "
        "(id, callsign, rns_hash, skills, profile, enrolled_at, lease_expires_at, revoked) "
        "VALUES (?, ?, ?, '[]', '{}', ?, ?, 0)",
        (
            operator_id,
            f"ALPHA-{operator_id}",
            f"client-rns-hash-{operator_id}",
            now,
            now + 3600,
        ),
    )
    session.conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('my_operator_id', ?)",
        (str(operator_id),),
    )
    session.conn.commit()


def test_client_asset_sitrep_and_mission_commands_use_local_operator(
    tmp_path: pathlib.Path,
) -> None:
    session = TalonCoreSession(config_path=_write_config(tmp_path, "client")).start()
    session.unlock_with_key(TEST_KEY)
    _seed_client_operator(session, operator_id=2)

    asset = session.command(
        "assets.create",
        category="cache",
        label="Client Cache",
        description="",
    )
    sitrep = session.command(
        "sitreps.create",
        level="ROUTINE",
        body="client-authored sitrep",
        asset_id=asset.asset_id,
    )
    mission = session.command(
        "missions.create",
        title="Client Mission",
        description="client-authored mission",
        asset_ids=[asset.asset_id],
    )

    asset_row = session.conn.execute(
        "SELECT created_by FROM assets WHERE id = ?",
        (asset.asset_id,),
    ).fetchone()
    sitrep_row = session.conn.execute(
        "SELECT author_id FROM sitreps WHERE id = ?",
        (sitrep.record_id,),
    ).fetchone()
    mission_row = session.conn.execute(
        "SELECT created_by FROM missions WHERE id = ?",
        (mission.mission.id,),
    ).fetchone()

    assert asset_row == (2,)
    assert sitrep_row == (2,)
    assert mission_row == (2,)

    session.close()


def test_server_asset_sitrep_and_mission_commands_use_server_sentinel(
    tmp_path: pathlib.Path,
) -> None:
    session = TalonCoreSession(config_path=_write_config(tmp_path, "server")).start()
    session.unlock_with_key(TEST_KEY)

    asset = session.command(
        "assets.create",
        category="cache",
        label="Server Cache",
        description="",
    )
    sitrep = session.command(
        "sitreps.create",
        level="ROUTINE",
        body="server-authored sitrep",
        asset_id=asset.asset_id,
    )
    mission = session.command(
        "missions.create",
        title="Server Mission",
        description="server-authored mission",
        asset_ids=[asset.asset_id],
    )

    asset_row = session.conn.execute(
        "SELECT created_by FROM assets WHERE id = ?",
        (asset.asset_id,),
    ).fetchone()
    sitrep_row = session.conn.execute(
        "SELECT author_id FROM sitreps WHERE id = ?",
        (sitrep.record_id,),
    ).fetchone()
    mission_row = session.conn.execute(
        "SELECT created_by FROM missions WHERE id = ?",
        (mission.mission.id,),
    ).fetchone()

    assert asset_row == (1,)
    assert sitrep_row == (1,)
    assert mission_row == (1,)

    session.close()


def test_client_commands_require_enrolled_local_operator(
    tmp_path: pathlib.Path,
) -> None:
    session = TalonCoreSession(config_path=_write_config(tmp_path, "client")).start()
    session.unlock_with_key(TEST_KEY)

    with pytest.raises(LocalOperatorResolutionError):
        session.command(
            "assets.create",
            category="cache",
            label="Unattributed Cache",
            description="",
        )

    with pytest.raises(LocalOperatorResolutionError):
        session.command(
            "sitreps.create",
            level="ROUTINE",
            body="unattributed sitrep",
        )

    with pytest.raises(LocalOperatorResolutionError):
        session.command(
            "missions.create",
            title="Unattributed Mission",
            description="",
        )

    session.close()
