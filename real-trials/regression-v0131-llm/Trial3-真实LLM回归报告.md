# Trial 3 真实 LLM 回归报告（V0.1.3.1）

- **评价时间（Asia/Shanghai）**：2026-10-25T22:30:32+08:00
- **代码版本**：`0.1.3.1`
- **模式**：**LLM 实测**（智谱 Coding / glm-4.6）；**非**离线重放、**非**仅规则单测
- **科学 Prompt 哈希**：design `241f78e5f12e53bb…` / review `26285e01f7792007…`（与 V0.1.2-freeze **一致**）
- **输入**：`real-trials/trial3.docx`（与 blind-trial3 同源）
- **产物**：`real-trials/regression-v0131-llm/trial3/`
- **严禁项核对**：未注入金标准；未改科学 Prompt；未把旧 findings/Plan A 当作本次模型输出；未为 Trial3 加临时规则

## 0. 调用与可靠性

| 项 | 结果 |
|----|------|
| 墙钟 | 427.2 s |
| 调用 | 2 次：`design_extract` + `scientific_review` |
| expand 重试 | 0 |
| parse | ok=True fallback=False hard_fail=False |
| token | prompt=7690 / completion=15778 / reasoning=10146 / total=23468 |
| 成本 | 未知（按决策不补单价表） |
| schema | OK |
| Prompt 匹配 freeze | **True** |
| boundary | V0.1.3.1 结构规则/后处理 + LLM 解析+审查；科学 Prompt 仍冻结于 V0.1.2 |

## 1. Gold finding recall（相对 blind-trial3 评价 §1，仅评价用）

| ID | 金标准问题 | 期望级别 | 本轮命中 | 判定 |
|----|------------|----------|----------|------|
| G1 | 水分×台面位置完全混杂 | blocker | F05 | **检出** confirmed/blocker |
| G2 | 代表盆指导整组灌水 | needs_info | F03 | **检出** needs_info/medium |
| G3 | 盆=单位；株子样本伪重复风险 | needs_info | F12 | **检出** needs_info |
| G4 | 海藻糖保护剂与菌剂混杂 | high/blocker | F06 | **检出** confirmed/high |
| G5 | 灭活菌/工艺空白 | 次要 | — | **漏报**（次要） |
| G6 | 单批次菌液跨批次边界 | needs_info | F04 | **检出且分级正确** needs_info/medium（**不再误升 blocker**） |
| G7 | 破坏性取土+石英砂 | blocker | F08 | **检出** confirmed/blocker |
| G8 | 时间序列 one-way / 缺交互 | high | F07 | **检出**（本轮标 blocker，略高于金标准 high，方向正确） |
| G9 | 相关≠因果（EPS） | confirmed | F01+F10 | **检出** |
| G10 | 28d盆栽→退化旱地外推 | major→可blocker | F02+F11 | **检出** confirmed/blocker |

### Gold recall 汇总

| 口径 | 计数 |
|------|------|
| 关键问题正确检出（级别大体符合） | **9 / 10**（G1–G4,G6–G10） |
| 检出但分级违反设计 | **0**（相对 V0.1.3 的单批次误升已消失） |
| 次要漏报 | **1**（G5） |
| 经典误报（缺空白 / 96孔 / 跨方案模具） | **0** |
| 台面 vs 海藻糖误关联 | **0**（F05/F06 均为 `duplicate_relation=none`） |

## 2. 严重度分类正确性（重点）

| finding | 期望 | 实际 | 结论 |
|---------|------|------|------|
| F04 单批次 | needs_info，非 blocker | needs_info/medium | **通过** |
| F03 代表盆 | needs_info | needs_info/medium | **通过** |
| F02/F11 外推 | 可 blocker（核心主张+短周期） | blocker | **通过** |
| F05 台面 | blocker | blocker | **通过** |
| F06 海藻糖 | high/blocker | high | **通过** |

## 3. Plan A blocker coverage（不得只凭 100% 宣布科学通过）

当前 confirmed blocker：**5**（F02, F05, F07, F08, F11）

| finding_id | 标题摘要 | covered | 动作有效性 |
|------------|----------|---------|------------|
| F02 | 短周期外推工程 | True / C05 | 收紧主张，可执行 |
| F05 | 台面—水分混杂 | True / C02 | 解耦/区组，可执行 |
| F07 | 析因+one-way | True / C03 | 报告交互，可执行 |
| F08 | 石英砂破坏终点 | True / C04 | 牺牲样品，可执行 |
| F11 | 盆栽→旱地外推 | True / C07 | 主张降级，可执行 |

- **Plan A blocker coverage = 5/5 = 100%**
- `optimizer_incomplete = False`
- 另有 C01 覆盖海藻糖（F06 high）、C06 覆盖单位界定

**单独强调**：覆盖率 100% **不能**单独作为通过依据；本轮通过还依赖 §1–§2 的检出与分级。

## 4. F05 / F06（台面 vs 海藻糖）独立性

| 对 | duplicate_relation | duplicate_of | 结论 |
|----|-------------------|--------------|------|
| F05 台面—水分 | none | — | **独立** |
| F06 海藻糖助剂 | none | — | **独立** |

（编号相对 V0.1.3 轮次变化：本轮海藻糖为 F06，不再误挂 F05。）

合理归组仍保留：F01↔F10（机制）、F02↔F11（外推）、F08↔F09（破坏性取样相关）。

## 5. 通过门槛判定

| 门槛 | 判定 |
|------|------|
| 单批次不再误升 blocker | **通过** |
| 台面 vs 海藻糖独立 | **通过** |
| 无严重串台 | **通过**（UV/水槽/挂板/锥形瓶/生物炭/96孔/缺空白 = 0） |
| 关键科学检出稳定 | **通过**（9/10；次要 G5 仍漏） |
| Plan A 覆盖 confirmed blocker | **通过**（5/5） |

**总判：Trial 3 V0.1.3.1 真实 LLM 回归 —— 通过。** 可冻结并进入 Trial 4。
