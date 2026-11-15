"""Generate baseline-scoped shared-file handoff; never edit shared files."""
import difflib
from pathlib import Path
import subprocess

BASE = "8023c3fee8e525040d101fee8bf843b48b3256d3"
ROOT = Path(__file__).resolve().parents[5]


def replacements():
    return {
        "app/main.py": [
            ("from app import config, db", "from app import config, db, state"),
            ("from app.business.gameplay import GameplayService",
             "from app.business.gameplay import GameplayService\nfrom app.business.social_services import SocialServices\nfrom app.business.social_inbox_services import SocialInboxServices"),
            ("    GameplayService().register(registry)",
             "    gameplay = GameplayService()\n    gameplay.register(registry)\n    social = SocialServices(gameplay, atomic_players=state.atomic_players)\n    social.register(registry)\n    SocialInboxServices(gameplay).register(registry)"),
            ("    register_periodic(registry)", "    register_periodic(registry, notification_provider=social.notifications)"),
        ],
        "app/business/periodic.py": [
            ("from typing import Any", "from functools import partial\nfrom typing import Any, Callable\n\nfrom app import state"),
            ("def handler(params: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:",
             "def handler(params: dict[str, Any], session: dict[str, Any] | None, *,\n            notification_provider: Callable | None = None) -> dict[str, Any]:"),
            ("    return response_shapes.success(API, payload)",
             "    if notification_provider is not None:\n        try:\n            payload.update(notification_provider(session))\n        except (ValueError, state.StateConflictError) as exc:\n            payload.update(succeeded=False, errorReason=str(exc))\n    return response_shapes.success(API, payload)"),
            ("def register(registry: Any) -> None:\n    registry.register(API, handler)",
             "def register(registry: Any, *, notification_provider: Callable | None = None) -> None:\n    registry.register(API, partial(handler, notification_provider=notification_provider))"),
        ],
        "tests/test_parallel_342_integration.py": [
            ('    "friend/cancelFriendOffer", "friend/dissolutionFriend", "friend/feedbackFriendOffer",\n    "friend/getFriendProfile", "friend/getFriends", "friend/sendFriendOffer", "friend/updateFriendData",\n', ''),
            ('    "inbox/getParcels", "inbox/resolveParcels", "siege/getPairings",', '    "siege/getPairings",'),
            ('    "trophy/getTrophyProgress", "trophy/completeTrophy", "trophy/messageWindowTrophy",',
             '    "trophy/getTrophyProgress", "trophy/completeTrophy", "trophy/messageWindowTrophy",\n    "friend/cancelFriendOffer", "friend/dissolutionFriend", "friend/feedbackFriendOffer",\n    "friend/getFriendProfile", "friend/getFriends", "friend/sendFriendOffer", "friend/updateFriendData",\n    "inbox/getParcels", "inbox/resolveParcels",'),
            ('for h in self.registry._handlers.values()), 331)', 'for h in self.registry._handlers.values()), 322)'),
            ('            self.assertIn("errorReason", self.registry.dispatch(api, {}, None)[1], api)',
             '            result = self.registry.dispatch(api, {}, None)[1]\n            if api in {"friend/cancelFriendOffer", "friend/dissolutionFriend",\n                       "friend/feedbackFriendOffer", "friend/sendFriendOffer"}:\n                self.assertIs(result["result"], False, api)\n            else:\n                self.assertIn("errorReason", result, api)'),
        ],
    }


def build():
    texts, chunks = {}, []
    for path, edits in replacements().items():
        before = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT).decode("utf-8")
        after = before
        for old, new in edits:
            assert after.count(old) == 1, path + ": expected one replacement"
            after = after.replace(old, new)
        chunks.append("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                fromfile="a/" + path, tofile="b/" + path)))
        texts[path] = after
    # Git accepts an empty context line without its optional leading space;
    # avoid introducing trailing whitespace in the patch artifact itself.
    result = "".join(line if line != " \n" else "\n"
                     for line in "".join(chunks).splitlines(keepends=True))
    return texts, result


if __name__ == "__main__":
    _, patch = build()
    Path(__file__).with_name("integration.patch").write_text(patch, encoding="utf-8", newline="\n")
