"""Hash original installer cache and bridge bodies; never export URLs' queries.

Prerequisite (Windows innoextract 1.9):
innoextract -s -I data7 -d <this-dir>/war_campaigns_local <original installer>
Extraction is local/ignored. This script does not upload original code or caches.
"""
import hashlib
import json
from pathlib import Path
import struct
from urllib.parse import urlsplit, urlunsplit
import zlib

HERE = Path(__file__).resolve().parent
LOCAL = HERE / "war_campaigns_local"
INSTALLER = Path.home() / "Downloads" / "OniSoul_Setup_20140712.exe"
SOURCE = Path(r"C:\Users\74378\AppData\Local\Temp\onisoul-static-original-20261115")


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


installer_hash = sha(INSTALLER)
assert installer_hash == "ad34a14e3dd67b30c59d5abd9ed2a82b2ab53161e24f3be654a63175e6d890ad"
records = []
selected = {}
for path in sorted((LOCAL / "app" / "cache" / "data7").rglob("*.d")):
    with path.open("rb") as handle:
        head = handle.read(4096)
    size = struct.unpack(">I", head[8:12])[0]
    assert 0 < size < 4000
    parsed = urlsplit(head[12:12+size].decode("ascii"))
    # Deliberately remove all query/fragment data, including historical tokens.
    public_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    records.append(dict(record=path.relative_to(LOCAL).as_posix(), url_without_query=public_url, sha256=sha(path)))
    if parsed.path in ("/client/js/app.js", "/client/js/unityProxy.js", "/client/js/commontool.js", "/client/app.html"):
        blob = path.read_bytes()
        if parsed.path.endswith(".js"):
            offset = blob.index(b"\xef\xbb\xbf", 12+size)
            body = blob[offset:]
            how = "plain UTF-8 BOM"
        else:
            for offset in range(12+size, len(blob)-2):
                if blob[offset] != 0x78:
                    continue
                try:
                    body = zlib.decompress(blob[offset:])
                except zlib.error:
                    continue
                if body.startswith(b"<!DOCTYPE html"):
                    break
            else:
                raise ValueError("original app.html body not found")
            how = "zlib"
        filename = parsed.path.rsplit("/", 1)[1]
        (LOCAL / filename).write_bytes(body)
        selected[filename] = dict(record=path.relative_to(LOCAL).as_posix(), record_sha256=sha(path),
            body_sha256=hashlib.sha256(body).hexdigest(), offset=offset, decoding=how,
            line_count=len(body.decode("utf-8-sig").splitlines()))

assert len(records) == 159
required = ["strategy/strategymatch.html", "strategy/strategy.html", "siege/siege.html",
            "siegeResult/siegeResult.html", "turfWarResult/turfWarResult.html"]
missing = [name for name in required if not any(r["url_without_query"].endswith("/"+name) for r in records)]
cs_names = ["BrowserProxy", "HTMLSiegeMediator", "HTMLStrategyMatchMediator", "HTMLStrategyMatchMediator_History",
            "HTMLStrategy", "HTMLStrategyMediator2", "HTMLStrategyMediatorPlayer", "HTMLStrategyMediatorPlayer2",
            "HTMLStrategyMediatorPlayerBattle", "StrategyLogAnalizer", "StrategyResultWindow2", "StrategyResultPoliticWindow",
            "SiegeResultRenderer", "TurfWarResultRenderer", "StrategySelect", "StrategySelect_army", "StrategyMoveableRegionSelector",
            "PoliticButton", "PoliticEventStrategyButton", "PoliticEventSiegeButton", "PoliticEventTurfWarButton",
            "TurfWarWorldMap", "TurfWarBriefCache", "siegeBriefMenu", "vsSetting_Siege", "HashAccessFuncs", "HashAccessor", "TimeFuncs"]
proof = dict(installer_path=str(INSTALLER), installer_sha256=installer_hash, cache_record_count=len(records),
    query_strings_removed=True, original_cache_inventory=records, original_bridges=selected,
    missing_page_bodies=missing, absence_scope="Only this original installer cache; not proof pages never existed or all client assets were searched",
    original_cs=[dict(path=str(SOURCE/(name+".cs")), sha256=sha(SOURCE/(name+".cs"))) for name in cs_names],
    evidence_lines={"app.js": ["15-31 SendMessage forwarding", "53-80 iframe paths", "169-173 reseiveMessage postMessage"],
        "unityProxy.js": ["76-85 open iframe", "103-140 receive/send responseId"],
        "HTMLSiegeMediator.cs": ["61-118 request -> pairings -> derived rows"],
        "HTMLStrategyMatchMediator.cs": ["134-221 analize actual data (exclude getDebugHash)"],
        "HTMLStrategyMatchMediator_History.cs": ["179-248 totalCount -> records -> decisions -> winner"],
        "TurfWarWorldMap.cs": ["291-328 optimistic Battlefield change BEFORE request"],
        "StrategyMoveableRegionSelector.cs": ["145-168 reachable/route/coolTime/seqId"]},
    limitations=["Missing iframe DOM/JS consumers remain unverified", "Bridge-derived display keys are not API fields", "No server matching, cycle, reward or claim idempotency inferred", "New record projections need a trusted producer and are not mounted"])
(HERE / "web-evidence.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
print(f"original records={len(records)}, bridge bodies={len(selected)}, missing requested page bodies={len(missing)}; no query strings exported")
