"""Read-only source audit; emit small proofs/rows and the 41-entry handoff matrix."""
import csv
import hashlib
import json
from pathlib import Path
import re
import struct
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
CS = Path("C:/Users/74378/AppData/Local/Temp/onisoul-static-original-20261115")
TABLES = Path("D:/onisoul/work/quest-contract-20261115/all-tables")
CACHE = Path("D:/onisoul-worktrees/parallel-342-f-war-campaigns/docs/analysis/parallel-342/f-war-campaigns/war_campaigns_local")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    files = {
        "FriendConfirmationWindow.cs": "168-187 remove membership; 195-299 mutation callback increments",
        "FriendData.cs": "40-94 public friend/profile projection",
        "FriendListWindow.cs": "38-116 root rows and option",
        "FriendWindowControll.cs": "118-127 absolute counts",
        "FriendSpecWindow.cs": "102-174 capacity UI",
        "WebApiClient.cs": "2604-2734 friends; 3352-3394 mailbox; 3451-3468 inbox; 190-216 network retry",
        "UserStatus.cs": "148-164 absolute periodic social counts; 648-656 reward display",
        "PoliticFSMFriendMap.cs": "62-78 distinct friend/nonfriend visit scripts",
        "PoliticUserInfo.cs": "IsFriend is set by status == ok in friend constructors",
        "Politic.cs": "312-352 Data2 then visit; 362-368 profile",
        "HTMLMailCore.cs": "30-149 bridge, to/subject/body have no attachment field",
        "HTMLBbsMediator.cs": "318-329 sess_key; 388-667 commit/text/forwarding",
        "InboxReader.cs": "92-177 parcels/time/rewards; makeDummy excluded",
        "InboxResolveWorker.cs": "11-105 successful rewards and failed.Count",
        "PluginRunner_DoReceiveMail.cs": "12-66 query 0..499 then accept all",
        "RewardProcessor.cs": "51-73,164-185,239-246 four resource IDs and incremental display",
    }
    proof = {"access_date": "2026-11-15", "baseline": "8023c3fee8e525040d101fee8bf843b48b3256d3",
        "original_cs": [{"path": str(CS / name), "sha256": sha(CS / name), "evidence": lines}
                        for name, lines in files.items()], "original_tables": []}
    rows = {}
    for name, keys in (("defines", ("friendoffer_send_max", "friendoffer_receive_max", "friendoffer_expire_time")),
                       ("playerLevel", ("1", "2"))):
        path = TABLES / (name + ".json")
        source = json.loads(path.read_text(encoding="utf-8-sig"))[name]
        rows[name] = {key: source[key] for key in keys}
        existing = json.loads((ROOT / "tests/fixtures/social" / (name + ".json")).read_text())
        for key, subset in existing.items():
            for field, value in subset.items():
                assert source[key][field] == value, (name, key, field)
        proof["original_tables"].append({"path": str(path), "sha256": sha(path), "row_ids": keys})
    fixture = ROOT / "tests/fixtures/research331/e-social/original-social-rows.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old = json.loads((ROOT / "docs/analysis/parallel-342/f-war-campaigns/web-evidence.json").read_text(encoding="utf-8"))
    assert sha(CACHE / "app.js") == old["original_bridges"]["app.js"]["body_sha256"]
    records = []
    for path in sorted((CACHE / "app/cache/data7").rglob("*.d")):
        with path.open("rb") as f:
            head = f.read(4096)
        size = struct.unpack(">I", head[8:12])[0]
        assert 0 < size < 4000
        parsed = urlsplit(head[12:12 + size].decode("ascii"))
        records.append(parsed.path)  # never log queries/fragments/historical tokens
    wanted = ("bbs/bbs.html", "mailbox/mailbox.html", "mail/mail.html", "reward/reward.html")
    proof["web_bridge"] = {"path": str(CACHE / "app.js"), "sha256": sha(CACHE / "app.js"),
        "lines": "39-50 BBS; 94-114 mailbox/mail; 144-153 reward",
        "cache_records_checked": len(records),
        "missing_body_paths": [name for name in wanted if not any(p.endswith("/" + name) for p in records)],
        "scope": "original installer cache only; no runtime 404 or universal asset absence implied",
        "installer_sha256": old["installer_sha256"]}
    (HERE / "source-proof.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (ROOT / "docs/analysis/parallel-342/e-social/reviewed-endpoints.tsv").open(encoding="utf-8") as f:
        previous = list(csv.DictReader(f, delimiter="\t"))
    task = Path("D:/onisoul-worktrees/research-331-plan-20261115/docs/analysis/research-331/tasks/E-social.txt").read_text(encoding="utf-8")
    owned = re.findall(r"^\d{2}\. (\S+)$", task, flags=re.M)
    assert len(owned) == 41 and set(owned) == {r["endpoint"] for r in previous}
    by_api = {r["endpoint"]: r for r in previous}
    friend_names = {"sendFriendOffer", "feedbackFriendOffer", "cancelFriendOffer", "dissolutionFriend",
                    "getFriends", "getFriendProfile", "updateFriendData"}
    fields = ["endpoint", "request", "response", "client_evidence", "rules", "assets", "state_transaction",
              "status", "runtime_acceptance", "remaining"]
    with (HERE / "endpoints.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for api in owned:
            oldrow = by_api[api]
            row = dict(endpoint=api, request=oldrow["request"], response=oldrow["response"],
                client_evidence=oldrow["evidence"], rules="hypothesis/unsupported: " + oldrow["next_step"],
                assets="已有原C#；所需原表/页面/场景各自待验", state_transaction="未实现状态生产",
                status="需抓取/未实现占位", runtime_acceptance="Unity未验收；HTTP未部署", remaining=oldrow["next_step"])
            if api.startswith("friend/") and api.split("/")[-1] in friend_names:
                row.update(rules="verified协议/容量；compatibility-policy惰性到期>=原表期限及remove通知",
                    assets="原defines/playerLevel小样本逐字段核对通过；HTML profile未支持",
                    state_transaction="I atomic_players；friends/socialOffers/socialRemovals同事务",
                    status="组件完成/待总集成补丁", runtime_acceptance="6项I适配MySQL测试覆盖生命周期/竞争/回滚；Unity未验收",
                    remaining="forHTML=true、跨新申请周期延迟重放、通知原服值；最大256记录为I支持范围")
            elif api.startswith("inbox/"):
                row.update(rules="verified四资源ID及原回调；compatibility-policy无期限发行/满额整包保留/重试空增量",
                    assets="原InboxReader/ResolveWorker；reward/reward.html正文未见于159条原缓存",
                    state_transaction="可信主机管理员CLI→stage_parcel来源收据→同玩家CAS领取→periodic绝对数量",
                    status="组件完成/待总集成补丁", runtime_acceptance="6项I适配MySQL测试含发行领取；注册补丁验证通过；Unity未验收",
                    remaining="原收件箱页面/其他奖励类型/原包裹期限；丢回包后须刷新资源或重登")
            elif api.startswith("community/") or api.startswith("mailbox/"):
                row["assets"] = "原app.js桥接已校验；bbs/mail/mailbox iframe正文未见于159条原缓存"
                row["state_transaction"] = "未实现；不复用旧AI网页或inbox奖励账本"
                if api == "mailbox/sendMails":
                    row["remaining"] = "原请求没有附件字段；收件人解析/完整页消费/发送事务待证；不发奖励"
            writer.writerow(row)
    print("41 endpoints; original tables checked;", len(records), "original cache records; no raw bodies exported")


if __name__ == "__main__":
    main()
