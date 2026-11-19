"""Adapt the isolated tutorial settlement to the PC battle feed supplied for QA."""
from __future__ import annotations

from app.business.adventure_battles import AdventureBattles, FACTION_BONUS
from app.business.adventure_services import mapping
from app.business.player_services import integer


ORDERS = ("1st", "2nd", "3rd", "4th", "5th")
STATS = ("atk", "def", "int")


class NativeStoryBattle(AdventureBattles):
    def __init__(self, service, messages):
        super().__init__(service)
        self.messages = messages

    def name(self, table, key):
        row = mapping(self.messages[table].get(key))
        name = row.get("tw") or row.get("jp")
        if not isinstance(name, str) or not name:
            raise ValueError(f"stub has no assets: missing {table} entry {key}")
        return name

    def execute(self, player, params):
        step = self.lifecycle(player)["events"].get("5", {})
        if step.get("status") == "resolved":
            self.settle_tutorial_win(player, params)  # Revalidate request before returning its receipt.
            return mapping(step["battle"].get("clientFeed"))

        inputs = self.prepare_quest_battle(player, params)
        receipt = self.settle_tutorial_win(player, params)
        feed = self.make_feed(player, inputs, receipt, step["createdAt"])
        player["adventureV1"]["storyLifecycle"]["events"]["5"]["battle"]["clientFeed"] = feed
        return feed

    def make_feed(self, player, inputs, receipt, created_at):
        entity = player["entity"]
        country = entity["country"]
        faction = self.table("country_setting")[country]["attribute"]
        monster_id = inputs["encounter"]["monsterId"]
        monster = inputs["encounter"]["monster"]
        monster_name = self.name("monsterMessage", monster["name"])
        hp = integer(monster["maxHp"], 1)
        # The source only supplies monster HP. Presentation zeros from the
        # supplied offline format are never used to simulate an enemy action.
        zero = dict.fromkeys(STATS, 0)
        monster_card = dict(zero, id=monster_id, name=monster_name, category="class1", level=1,
                            attribute="evil", maxHp=hp, voice=monster["voice"],
                            work=dict(zero, tactics="empty"), skills={})

        cards, current = {}, {}
        definitions = self.table("character")
        item_rows = self.table("item01").values()
        for row in inputs["formation"]:
            order = ORDERS[row["position"]]
            char = row["character"]
            base = definitions[char["baseId"]]
            variants = [item for item in item_rows if item.get("parameterId") == char["baseId"]
                        and item.get("grade", 1) == 1]
            name_keys = {item.get("nameId") for item in variants}
            if len(name_keys) != 1:
                raise ValueError("stub has no assets: grade-one character display name is ambiguous")
            stats = current[order] = {name: integer(char[name]) for name in STATS}
            cards[order] = dict(stats, name=self.name("item01Message", name_keys.pop()),
                                characterCode=str(base["characterCode"]), troopClass=base["troopClass"],
                                attribute=base["attribute"], sex=base["sex"], baseId=char["baseId"],
                                grade=1, level=1, voice=char["voice"], skills={}, bonus={})

        def total():
            return {name: sum(row[name] for row in current.values()) for name in STATS}

        initial = total()
        process = {}

        def add(event, **value):
            process[str(len(process))] = {"event": event, "value": value}

        add("beginBattle")
        for order, card in cards.items():
            if card["attribute"] == faction:
                owner = {"attacker": {"0": order}}
                add("execCommonEffect", id=FACTION_BONUS, owner=owner, target={"target1": owner, "target2": {}})
                current[order]["atk"] = card["atk"] * 125 // 100
                add("changeParam", type="attacker", position=order, param=dict(current[order]))
                add("updateTotalParam", type="attacker", param=total())
                add("endExecCommonEffect")
            card["work"] = dict(current[order], tactics="empty")
        add("beginTurn", turn=0)
        round_damage = dict.fromkeys(ORDERS, 0)
        for row in receipt["damage"]:
            order = ORDERS[row["position"]]
            damage = row["damage"]
            if damage != current[order]["atk"]:
                raise ValueError("no stub response: receipt damage does not match the first-turn feed")
            round_damage[order] = damage
            add("beginRound", roundNumber=order, attacker=order, defender="monster",
                attackerParam=current[order], defenderParam=zero)
            add("beginPlayer")
            add("playerAttack", turn=0, round=order, damage=damage, critical=False, coef={}, additionalDamage={})
            add("endPlayer")
            add("endRound")
        add("endTurn")
        winner = receipt["winner"]
        add("endBattle", winner=winner)

        damage = sum(round_damage.values())
        player_hp = sum(initial.values())
        attacker = dict(category="troops", name=entity["username"], level=entity["level"], attribute=faction,
                        country=country, leaderPosition=max(cards, key=ORDERS.index), maxHp=player_hp,
                        initHp=player_hp, hp=player_hp, defaultTotal=initial, totalParameter=total(),
                        maxDamage=max(round_damage.values()), totalDamage=damage, roundDamage=round_damage,
                        characters=cards, positions={order: order for order in ORDERS})
        defender = dict(category="monster", name=monster_name, level=1, attribute="evil", country="0",
                        leaderPosition="monster", maxHp=hp, initHp=hp, hp=hp - damage, defaultTotal=zero,
                        totalParameter=zero, roundDamage=dict.fromkeys(ORDERS, 0), characters={"monster": monster_card},
                        positions=dict.fromkeys(ORDERS, "monster"))
        record = {key: {"update": False, "value": val} for key, val in {
            "skillCount": 0, "comboCount": 0, "totalDamage": damage,
            "maxAttack": max(row["atk"] for row in current.values()), "totalWin": 0, "consecutiveWin": 0,
        }.items()}
        return dict(log=dict(time=str(created_at), battleType="MonsterBattle", battleRule="hpBattle", isBot=False,
                             battleField=0, attackerId=inputs["ownerId"], attackerName=entity["username"],
                             attackerCountryId=country, defenderId=monster_id, defenderName=monster_name,
                             defenderCountryId="0", winner=winner, decision={}),
                    information=dict(attacker=attacker, defender=defender, battle=dict(isSettled=True,
                                     prevWinner="none", roundDecision={order: "attacker" for order in ORDERS
                                                                       if round_damage[order]}, effects={},
                                     usedTactics={"attacker": {}, "defender": {}})),
                    process=process, result=dict(payment=receipt["reward"], bonus={}, record=record, skill={}))
