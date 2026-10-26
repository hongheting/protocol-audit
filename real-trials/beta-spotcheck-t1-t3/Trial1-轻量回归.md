# Trial 1 轻量真实 LLM 回归（Beta V0.1.3.3）

- **评价时间（Asia/Shanghai）**：2026-10-26T10:26:28+08:00
- **代码版本**：`0.1.3.3`
- **模式**：真实 LLM（智谱 Coding / glm-4.6）；**不调参、不加规则、不改科学 Prompt**
- **Prompt 哈希**：design `241f78e5…` / review `26285e01…` — 与 V0.1.2-freeze **一致**
- **输入**：`real-trials/trial1.docx`
- **产物**：`real-trials/beta-spotcheck-t1-t3/trial1/`
- **对照**：`real-trials/gold/trial1.gold.json`、`real-trials/trial1-retest-report.md`（评价用，未注入生产）

## 0. 调用可靠性

| 项 | 结果 |
|----|------|
| 墙钟 | 361.6 s |
| 调用 | 2：`design_extract` + `scientific_review` |
| finish_reason | 均为 **`stop`** |
| expand 重试 | 0 |
| parse | ok=True；hard_fail=False |
| schema | OK |
| facade | **False**（boundary 声明完整 LLM 审查；origin llm_review=7 / rule=10） |
| Prompt 匹配 freeze | **True** |

**结论：调用与解析可靠；无静默空 findings 伪装。**

## 1. 关键 finding（相对 gold 核心 G1–G6）

| ID | 金标准 | 本轮命中 | 判定 |
|----|--------|----------|------|
| G1 | UV×水槽混杂 | F01 + F11（confirmed/blocker） | **检出** |
| G2 | 伪重复 | F02 + F12（confirmed/blocker） | **检出** |
| G3 | 助溶剂混杂 | F03 + F13（confirmed/high） | **检出** |
| G4 | 析因/协同 | F04 + F14（confirmed/high） | **检出** |
| G5 | 破坏性×重复测量 | F05 + F15（confirmed/high） | **检出** |
| G6 | 机制相关 + 工程外推 | F06/F16 + F07/F17 | **检出** |

- 核心召回：**6/6**
- 经典误报 S1（96 孔）/ S2（缺空白）：**0**
- 相对既有 Trial1 重测：**无严重退化**

## 2. Claim–Evidence

| 行 | supports | 说明 |
|----|----------|------|
| CE01 H1 | no | 附着生物量主张 |
| CE02 H2 | no | 联用/协同主张 |
| CE03 H3 | no | 润湿性机制 |
| CE04 EXTRAP | no | 长期工程外推 |

未把限制句误标为 EXTRAP 否定主张（本方案无此类 SCOPE 句触发）。**CE 未严重退化。**

## 3. Plan A

- confirmed blocker：**6**；`blocker_action_map` **6/6 covered**；`optimizer_incomplete=False`
- 水槽层重复 / 主张降级、助溶剂、析因交互、破坏性改设计、外推收紧均有对应动作
- **非阻断观察**：非 blocker 的 F15 对应 C04 文案出现「再生/循环称量」串台（Trial2 话术残留）；blocker 覆盖本身仍正确。记入已知限制，本轮不调参。

## 4. 总判

**Trial 1 轻量回归：通过（无严重退化）。**
