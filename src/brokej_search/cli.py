from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import uvicorn
from alembic.config import Config

from alembic import command
from brokej_search.core.logging import configure_logging
from brokej_search.discovery.scheduler import DiscoveryScheduler
from brokej_search.discovery.schemas import SourceCreate
from brokej_search.runtime import create_runtime


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brokej", description="BrokeJ-Search backend")
    commands = parser.add_subparsers(dest="command", required=True)

    db = commands.add_parser("db")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("upgrade")
    backup = db_commands.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)
    verify = db_commands.add_parser("verify-backup")
    verify.add_argument("--input", type=Path, required=True)

    profile = commands.add_parser("profile")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    ingest = profile_commands.add_parser("ingest")
    ingest.add_argument("--candidate", required=True)
    ingest.add_argument("--resume", type=Path, required=True)
    show = profile_commands.add_parser("show")
    show.add_argument("--candidate", required=True)
    show.add_argument("--private", action="store_true")
    validate = profile_commands.add_parser("validate")
    validate.add_argument("--candidate", required=True)
    evidence = profile_commands.add_parser("evidence")
    evidence.add_argument("--candidate", required=True)
    evidence.add_argument("--skill", required=True)
    diff = profile_commands.add_parser("diff")
    diff.add_argument("--candidate", required=True)
    diff.add_argument("--from", dest="from_version", type=int, required=True)
    diff.add_argument("--to", dest="to_version", type=int, required=True)

    discovery = commands.add_parser("discovery")
    discovery_commands = discovery.add_subparsers(dest="discovery_command", required=True)
    add = discovery_commands.add_parser("source-add")
    add.add_argument("--name", required=True)
    add.add_argument("--type", choices=["greenhouse", "lever", "ashby"], required=True)
    add.add_argument("--board", required=True)
    add.add_argument("--company", required=True)
    add.add_argument("--region", choices=["global", "eu"], default="global")
    discovery_commands.add_parser("source-list")
    enable = discovery_commands.add_parser("source-enable")
    enable.add_argument("--source-id", required=True)
    disable = discovery_commands.add_parser("source-disable")
    disable.add_argument("--source-id", required=True)
    run = discovery_commands.add_parser("run")
    run.add_argument("--source-id", action="append")
    discovery_commands.add_parser("worker")

    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def _database_path(url: str) -> Path:
    if not url.startswith("sqlite:///"):
        raise ValueError("Backup commands currently support SQLite only")
    return Path(url.removeprefix("sqlite:///"))


def main() -> None:
    args = _parser().parse_args()
    runtime = create_runtime()
    configure_logging(runtime.settings.log_level)
    if args.command == "db":
        if args.db_command == "upgrade":
            command.upgrade(Config("alembic.ini"), "head")
            return
        source = _database_path(runtime.settings.database_url)
        if args.db_command == "backup":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(source) as source_db, sqlite3.connect(args.output) as target_db:
                source_db.backup(target_db)
            _print({"status": "created", "path": str(args.output)})
            return
        with sqlite3.connect(args.input) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        _print({"integrity": integrity, "foreign_key_violations": len(foreign_keys)})
        if integrity != "ok" or foreign_keys:
            raise SystemExit(1)
        return
    if args.command == "profile":
        if args.profile_command == "ingest":
            _print(
                runtime.profiles.ingest_resume(args.candidate, args.resume).model_dump(mode="json")
            )
        elif args.profile_command == "show":
            _print(runtime.profiles.get_profile(args.candidate, include_private=args.private))
        elif args.profile_command == "validate":
            _print(runtime.profiles.validate(args.candidate).model_dump(mode="json"))
        elif args.profile_command == "evidence":
            _print(runtime.profiles.evidence_for_skill(args.candidate, args.skill))
        else:
            _print(runtime.profiles.diff(args.candidate, args.from_version, args.to_version))
        return
    if args.command == "discovery":
        if args.discovery_command == "source-add":
            source_id = runtime.discovery.add_source(
                SourceCreate(
                    name=args.name,
                    connector_type=args.type,
                    board_identifier=args.board,
                    company_name=args.company,
                    config={"region": args.region} if args.type == "lever" else {},
                )
            )
            _print({"id": source_id})
        elif args.discovery_command == "source-list":
            _print(runtime.discovery.list_sources())
        elif args.discovery_command in {"source-enable", "source-disable"}:
            enabled = args.discovery_command == "source-enable"
            runtime.discovery.set_source_enabled(args.source_id, enabled)
            _print({"source_id": args.source_id, "enabled": enabled})
        elif args.discovery_command == "run":
            _print(asyncio.run(runtime.discovery.run(args.source_id)).model_dump(mode="json"))
        else:
            DiscoveryScheduler(
                runtime.discovery,
                runtime.settings.discovery_interval_minutes,
                runtime.settings.scheduler_timezone,
            ).start()
        return
    uvicorn.run("brokej_search.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
