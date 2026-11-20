"""Commission repair only emits scripts supported by all navigator tables."""
import unittest
from xml.etree import ElementTree

from tools.audit_pc_mission_dialogues import dialogue_for
from tools.build_mission14_dialogue import script


class MissionDialogueAuditTest(unittest.TestCase):
    def setUp(self):
        self.row = {
            "id": "po_mission_00021", "iconIndex": -1, "iconFileName": "none",
            "enterScript": "scr1_000021_01", "exitScript": "scr1_000021_03",
            "conditionCount1": 1, "conditionCount2": 0, "conditionCount3": 0,
        }
        self.texts = {
            "01_001": "开场对白@", "01_002": "内政委托　内文@",
            "02_001": "委托标题", "02_002": "条件说明",
            "03_001": "完成对白@", "03_002": "委托标题　达成！",
            "03_003": "「内政委托内容」@",
        }

    def messages(self, **variant):
        def keys(texts):
            return {"POM_MES_000021_" + suffix: {"tw": text} for suffix, text in texts.items()}

        return {"first.json": keys(self.texts), "second.json": keys({**self.texts, **variant})}

    def test_keeps_original_keys_and_hides_disabled_menu_rows(self):
        dialogue, skipped = dialogue_for(self.row, [self.row], self.messages(**{"03_001": "完成对白"}))
        self.assertEqual((dialogue.enter_pages, dialogue.reward_title, skipped), (1, 2, 1))
        menu = ElementTree.fromstring(script(dialogue, "02")).find(".//block/call/value_list")
        self.assertEqual([node.tag for node in menu], ["call", "call", "string", "string"])
        self.assertEqual(menu[0].find(".//string").text, "POM_MES_000021_02_001")
        self.assertEqual(len(ElementTree.fromstring(script(dialogue, "03"))
                             .findall(".//call[@id='politic_drawNavigatorMessage']")), 1)

    def test_requires_labels_for_each_active_condition_on_shared_scripts(self):
        shared = {**self.row, "conditionCount2": 1}
        with self.assertRaisesRegex(ValueError, "missing substantive mission menu"):
            dialogue_for(self.row, [self.row, shared], self.messages())

    def test_requires_visible_opening_and_consistent_reward_key(self):
        with self.assertRaisesRegex(ValueError, "opening dialogue"):
            dialogue_for(self.row, [self.row], self.messages(**{"01_001": "开场对白"}))
        with self.assertRaisesRegex(ValueError, "navigator variants disagree"):
            dialogue_for(self.row, [self.row], self.messages(**{
                "03_002": "追加对白@", "03_003": "委托标题　达成！",
            }))
