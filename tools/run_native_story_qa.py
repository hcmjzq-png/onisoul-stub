"""Run the native story candidate from a dedicated loopback port and QA schema."""
from __future__ import annotations

import argparse
from functools import partial
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def register_step(registry, service, max_step):
    from app.business.adventure_events import AdventureEvents, StepIntent
    from app.business.player_services import integer

    route = "quest/executeQuestEx"
    producer = AdventureEvents(service)

    def execute(params, session):
        item = params.get("operationId")
        try:
            step = integer(params.get("expectedStep"), 0, max_step - 1)
        except ValueError:
            return service._failure(route, f"no stub response: native tutorial only supports steps 1–{max_step}")
        if not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{32}", item):
            return service._failure(route, "no stub response: stable step ID required")
        return producer.execute_trusted(params, session, StepIntent(service._player_id(session), item, step))

    registry.register(route, execute)


def register_battle(registry, service, message_dir):
    from tools.native_story_battle import NativeStoryBattle

    keys = ("monsterMessage", "item01Message")
    messages = {key: json.loads((message_dir / (key + ".json")).read_bytes())["message"] for key in keys}
    producer = NativeStoryBattle(service, messages)
    route = "battle/executeBattle"
    registry.register(route, service._guard(route, partial(producer.call, route, producer.execute)))


def prepare_story_fixture(service, player_id):
    """Give the isolated player the city unlocks needed to start story QA."""
    from app.business.mission_chain import STATE_TO_LETTER, UNLOCK_BITS
    from app.business.mission_validation import validate_progress

    player, _ = service._load(player_id)
    quest_unlock = UNLOCK_BITS["unlockQuest"]
    if service._unlock_bits(player) & quest_unlock:
        return
    if player.get("adventureV1"):
        raise RuntimeError("refusing to prepare a fixture with existing adventure progress")

    rows = service.missions.rows()
    pending = ["po_mission_00001", "po_mission_00012"]
    prerequisites = set()
    while pending:
        code = pending.pop()
        if code in prerequisites:
            continue
        row = rows[code]
        prerequisites.add(code)
        if row["bootCheckFunc"] == "clear_mission":
            pending.extend(row["bootCheckData"])
        elif row["bootCheckFunc"] != "none":
            raise RuntimeError(f"unsupported fixture prerequisite: {code}")

    # Seed city completion directly so it gives no items and spends no story points.
    for code in sorted(prerequisites):
        index = str(int(rows[code]["index"]))
        player["missions"][index] = STATE_TO_LETTER["closed"]
        player.get("missionProgress", {}).pop(code, None)
    validate_progress(player, rows)
    if not service._unlock_bits(player) & quest_unlock:
        raise RuntimeError("fixture did not unlock the native story button")
    service._save(player, player_id)
    print(f"prepared {len(prerequisites)} city missions for native story QA", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("profiles", "assets", "candidate", "scene", "prefabs"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--battle-messages", type=Path)
    p.add_argument("--chapter-preview", action="store_true")
    p.add_argument("--port", type=int, default=18119)
    p.add_argument("--schema", default="onisoul_native_story_qa_20261118")
    args = p.parse_args()
    if not re.fullmatch(r"onisoul_native_story_qa_[0-9]+", args.schema) or args.port in (80, 18080, 18081, 18082):
        p.error("fixture requires a dedicated native story QA schema and port")
    if args.chapter_preview and args.battle_messages:
        p.error("chapter preview is read-only")
    stage = args.candidate.resolve()
    manifest = json.loads((stage / "manifest.json").read_bytes())
    if args.chapter_preview != ("previewBackgrounds" in manifest):
        p.error("fixture and client chapter preview modes differ")
    profile = json.loads(args.profiles.read_bytes())
    for key in list(os.environ):
        if key.startswith(("ONI_", "STUB_")):
            del os.environ[key]
    os.environ.update(
        ONI_ENVIRONMENT="local-test", ONI_INSTANCE_ID="native-story-qa",
        ONI_BUILD_ID="native-story-qa-20261118",
        ONI_DB_HOST="127.0.0.1", ONI_DB_PORT="3307", ONI_DB_NAME=args.schema,
        ONI_DB_USER="root", ONI_DB_PASSWORD=profile["mysql_root_password"],
        ONI_ROOT=str(Path(__file__).resolve().parents[1]),
        ONI_TABLE_DIR=str(args.assets / "tables"), ONI_PC_WEB_DIR=str(args.assets / "web"),
        ONI_PC_BUNDLE_DIR=str(args.assets / "bundles"), AUTH_MODE="strict",
    )
    from app import db, sessions, state
    from app.main import build_registry
    from app.business.gameplay import GameplayService
    from app.transport import http_server
    from app.transport.static import StaticFiles

    db.init_schema()
    db_config = os.environ.pop("ONI_DB_PASSWORD")
    qa_user = "oni_" + secrets.token_hex(8)
    qa_secret = secrets.token_hex(24)
    os.environ["ONI_DB_PASSWORD"] = db_config
    with db.connection() as con:
        with con.cursor() as q:
            q.execute(f"CREATE USER '{qa_user}'@'127.0.0.1' IDENTIFIED BY %s", (qa_secret,))
            q.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE ON `{args.schema}`.* TO '{qa_user}'@'127.0.0.1'")
    os.environ.update(ONI_DB_USER=qa_user, ONI_DB_PASSWORD=qa_secret)
    service = GameplayService()
    # In this database, this server creates and exposes just its own test player.
    account = "oni-native-fixture"
    issued, exists = service._issue_login(account)
    player_id = issued["playerId"]
    if not exists:
        result = service.create_player(dict(username="原生物语验证", countryId="country01",
                         navigatorId="navi8000101", colorIndex="color1"), issued)
        if not result["succeeded"]:
            raise RuntimeError("fixture bootstrap failed")
    prepare_story_fixture(service, player_id)
    startkey = secrets.token_urlsafe(24)
    stage.joinpath("fixture-start.txt").write_text(
        f"http://127.0.0.1:{args.port}/fixture/{startkey}", encoding="ascii")

    # Block stepping outside this runner; normal app.main registers no write.
    registry = build_registry()
    if args.chapter_preview:
        from tools.native_story_preview import NativeStoryPreview

        NativeStoryPreview(service).register(registry)
    else:
        from app.business.local_quest_menu import LocalQuestMenu

        LocalQuestMenu(service).register(registry)
        register_step(registry, service, 5 if args.battle_messages else 4)
    assets = {
        "/client/app.unity3d": stage / "app.unity3d",
        "/client/pc/jp/assets/scene/" + args.scene.name: args.scene,
        "/client/pc/jp/assets/scene/" + args.prefabs.name: args.prefabs,
        "/client/pc/jp/assets/stq/da83c61a24cb68a768ad88bcaa95fc05.unity3d":
            stage / "da83c61a24cb68a768ad88bcaa95fc05.unity3d",
    }
    portrait_name = "f3eaafecee830797b986b70b2b16ee08.unity3d"
    if (stage / portrait_name).is_file():
        assets["/client/pc/jp/assets/cch/" + portrait_name] = stage / portrait_name
    if args.chapter_preview:
        from hashlib import md5

        for name in manifest["previewBackgrounds"]:
            if not re.fullmatch(r"qbg\d+_\d+_\d+", name):
                p.error(f"invalid preview background name: {name}")
            filename = md5(name.encode("utf-16le")).hexdigest() + ".unity3d"
            file = stage / "qbg" / filename
            if not file.is_file():
                file = args.assets / "bundles" / "qbg" / filename
            if not file.is_file():
                p.error(f"stub has no assets: {file}")
            for root in ("assets", "assets2"):
                assets[f"/client/pc/jp/{root}/qbg/{filename}"] = file
    if args.battle_messages:
        if not manifest.get("battle"):
            p.error("expected a battle-enabled client script")
        battle_files = {
            "scene/ec7eb72b0c3a6d0d07f2445ffe4645e9.unity3d",
            "scene/56f270161dfd00d357c585cd7c9f4407.unity3d",
            "scene/00a497ac4a5104413178b565d9ebe4f2.unity3d",
            "cch/f4ce93ca57fd9ca98622d49ca59a92b4.unity3d",
            "item/cd6b7286bf976baf30439a753339f163.unity3d",
            "item/f763fab45a6b821f0495af3516b257e0.unity3d",
        }
        for name in battle_files:
            file = stage / name
            if not file.is_file():
                p.error(f"stub has no assets: {file}")
            for root in ("assets", "assets2"):
                assets[f"/client/pc/jp/{root}/{name}"] = file
        register_battle(registry, service, args.battle_messages)

    class Overlay(StaticFiles):
        def resolve(self, target):
            path = urlsplit(target).path
            if path in assets:
                file = assets[path]
                return self._file(file.parent, Path(file.name), cache_control="no-store")
            return super().resolve(target)

    base = http_server.make_handler(registry, Overlay())
    from http.server import ThreadingHTTPServer

    class Handler(base):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/fixture/" + startkey:
                token = sessions.issue(account)["token"]
                target = "/client/app.html?" + urlencode(dict(token=token, id=secrets.token_hex(20),
                         container="cog", now=int(time.time())))
                return http_server._html_response(self, 302, b"", location=target)
            if path == "/fixture/" + startkey + "/check":
                row = state.load(player_id)
                events = row.get("adventureV1", {}).get("storyLifecycle", {}).get("events", {})
                data = {"missionPoint": row["actionPoints"]["missionPoint"]["point"],
                        "experience": row["entity"].get("exp", 0),
                        "purpleSoul": row.get("souls", {}).get("purple", 0),
                        "battle": [{"event": event["step"], "status": event["status"],
                                    "reward": (event.get("battle") or {}).get("reward", {})}
                                   for event in events.values() if event.get("encounter")],
                        "jin": row["items"].get("item08_0102701", 0),
                        "maeda": sum(c.get("baseId") == "chara1_00324_01" for c in row["characters"].values()),
                        "story": [{"step": event["step"], "cost": event["cost"], "reward": event["reward"]}
                                  for event in events.values()]}
                return http_server._json_response(self, 200, data)
            super().do_GET()

        def log_request(self, code="-", size="-"):
            path = urlsplit(self.path).path
            if path.startswith("/fixture/"):
                path = "/fixture"
            print(self.command, path, code, flush=True)

    host = ("127.0.0.1", args.port)
    with ThreadingHTTPServer(host, Handler) as server:
        print("native story fixture ready on loopback", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
