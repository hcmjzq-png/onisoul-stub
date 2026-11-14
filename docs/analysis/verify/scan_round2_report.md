# 扫描层 round2 结项报告（2026-11-14 夜）

分支 `feature/scan-round2`，**未推送、未合 main**。基线仍是 `main = 72a4a02`。

## 一、结论

1. **候选缺口清零为「纯归属错」**：过滤后 33 行 / 25 端点，全部 `other_endpoint`；
   真缺口 0（最后一条 `debug/resetDedication.score` 已补）。
2. 104 行台账新增 `covered_nested` 判决 2 行（`deck/extendCharacterStore` 的根键 `character`、
   `quest/clearObstacle` 的根键 `category`）——都是「客户端读的是已声明子表，扫描器把根键当成了新键」。
3. 契约：402 端点 / **1108 键（627 带类型）** / 83→88 tests / `contract_check` 0 问题。
4. 剩余两块宽度工作已量化，均**未动契约**（见三）。

## 二、本批改动

| 文件 | 改动 |
|---|---|
| `docs/analysis/api_contract.tsv` | `debug/resetDedication` 补 `score:double` |
| `docs/analysis/verify/gap_origins.tsv` | 新增 `nested_child` 类别 2 行（`DeckAddMaxCharacter.createAddCharacterWindow|hashtable3`、`QuestScriptCommand.clearObstacle|uses`） |
| `tools/unguarded_reads.py` | `ORIGINS` 词表加 `nested_child` |
| `docs/analysis/unguarded_gaps.tsv` | 36 → 33 行 / 25 端点 |
| `docs/analysis/unguarded_gaps_verdicts.tsv` | 2 行改判 `covered_nested`；filter 列 67 dropped / 33 kept / 2 mixed / 2 nested |
| `docs/analysis/verify/zero_field_triage.tsv` | 新增，122 行分诊 |
| `docs/analysis/verify/untyped_backlog.tsv` | 新增，481 行 backlog |
| `tests/test_gap_verdicts.py` | 词表/计数/长度断言同步（33 行、25 端点、67/33/2/2） |

## 三、没做的（留给白天决策）

1. **122 个零字段端点**：分诊结果 `no_call_site` 53 / `no_literal_read` 61 / `reads_present` 8。
   **8 个已逐个核实并改判（需补键 0）**：6 个误报（配置表 `items`/`enable`、写侧自造
   `color1..color5`、写侧+本地 UI `atk/grade/level`、入参 `mailIds`、入参+写侧 `turn/aroundRank`），
   2 个归属错（`DeckScene.OnEnable` 读 `getDeckBonus`/`getDecks` 回包）。
2. **481 个无类型键**：`cast` 列能唯一定型 31 个，**450 个没有 cast 证据**。
   → 建议：这 31 个可以直接补（机械依据充分）；450 个要么回客户端看 `HashAccessor.getXxx`
   访问器调用（工作量大），要么明确接受「裸键照旧」并在文档里写死这个限制。
3. `eventInfo` 其余事件分支、`getStrategyStatus.map` 两类嵌套子表仍未取证。

## 四、复跑命令

```bash
cd /tmp/onisoul-push && git checkout feature/scan-round2
python3 tools/unguarded_reads.py gap --dump /tmp/pairs.tsv \
    --contract docs/analysis/api_contract.tsv \
    --receivers docs/analysis/verify/gap_receivers.tsv \
    --origins docs/analysis/verify/gap_origins.tsv \
    --filter origin --out /tmp/check_gaps.tsv   # 应 33 行
PYTHONPATH=. python3 -m unittest discover -s tests   # 88 tests
python3 tools/contract_check.py                       # 1108 键 / 627 带类型 / 0 问题
```
