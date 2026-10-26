# Trial 3 真实 LLM 回归报告（V0.1.3）

- **评价时间（Asia/Shanghai）**：2026-10-25T22:09:33+08:00
- **代码版本**：`0.1.3`
- **模式**：**LLM 实测**（智谱 Coding / glm-4.6）；**非**离线重放、**非**仅规则单测
- **科学 Prompt 哈希**：design `241f78e5f12e53bb…` / review `26285e01f7792007…`（与 V0.1.2-freeze **一致**）
- **输入**：`real-trials/trial3.docx`（与 blind-trial3 同源）
- **产物**：`real-trials/regression-v013-llm/trial3/`（extract / preview / audit-report / call-summary / run.log / cli-summary）
- **严禁项核对**：未注入金标准；未改科学 Prompt；未把旧 findings/Plan A 当作本次模型输出

## 0. 调用与可靠性

| 项 | 结果 |
|----|------|
| 墙钟 | 380.2 s |
| 调用 | 2 次：['design_extract', 'scientific_review'] |
| expand 重试 | 0（本轮解析一次成功，未触顶） |
| parse | ok=True fallback=False hard_fail=False |
| token | prompt=7753 / completion=13673 / reasoning=8051 / total=21426 |
| 成本 | 未知（按既定决策不补单价表） |
| schema | OK |
| boundary | V0.1.3 结构规则/后处理 + LLM 解析+审查；科学 Prompt 仍冻结于 V0.1.2 |

## 1. 重点验证（任务一）

| # | 检查项 | 结果 | 说明 |
|---|--------|------|------|
| 1 | 代表盆灌水规则 | **通过** | `F03` `structural_representative_unit_dosing` → **needs_info/medium**；追问已生成。LLM 另出 `F12` suggestion（未升 confirmed 伪重复） |
| 2 | 单批次 → CE/追问 | **部分失败** | 追问与 CE01/CE03 gap **已写入**；但 `F04` 被误升为 **confirmed/blocker**（见 §4），**不符合**「维持 needs_info、不自动升 blocker」设计 |
| 3 | confirmed blocker → Plan A 动作 | **通过** | `blocker_action_map` 覆盖率 **5/5=100%**；`optimizer_incomplete=false` |
| 4 | 软去重保留关系 | **部分通过** | `F01↔F07`、`F02↔F11` 关系合理；**`F08` 误标 `duplicate_of=F05`**（海藻糖 vs 台面，主题「混杂」过宽）——条均保留未丢证据 |
| 5 | optimizer_incomplete 路径 | **本轮未触发**（全覆盖）；单测 `tests/test_v013_features.py::test_blocker_coverage_*` / incomplete 断言覆盖该路径 |
| 6 | 误报/漏报/串台 | **无严重串台** | 未出现 UV/水槽/挂板/锥形瓶/生物炭话术；无「缺空白」「96 孔伪重复」。漏报：灭活菌工艺空白（次要） |

## 2. Gold finding recall（相对盲测评价 §1，仅用于评价）

> 金标准仅来自 `blind-trial3/Trial3-盲测评价.md` §1，**未**写入生产 Prompt。

| ID | 金标准问题 | 期望级别 | 本轮命中 | 判定 | 备注 |
|----|------------|----------|----------|------|------|
| G1 | 水分×台面位置完全混杂 | blocker | F05 | **检出** | confirmed/blocker |
| G2 | 代表盆指导整组灌水（组内非独立风险） | needs_info | F03(+F12) | **检出** | F03=needs_info（符合设计）；F12=LLM suggestion 并行，未升 confirmed 伪重复 |
| G3 | 实验单位=盆；株为子样本伪重复风险 | needs_info/边界 | F10 | **检出** | needs_info |
| G4 | 海藻糖保护剂与菌剂混杂 | high/blocker | F08 | **检出** | confirmed/high |
| G5 | 灭活菌/工艺空白对照缺失 | 次要 | — | **漏报** | 相对海藻糖为次要；本轮未出独立条 |
| G6 | 单批次菌液→跨批次推广限制 | needs_info | F04 | **检出但分级错误** | 规则应为 needs_info；被 adjust_extrapolation_severity 因标题含「推广」误升 confirmed/blocker |
| G7 | 破坏性取样+补石英砂 | blocker | F06 | **检出** | confirmed/blocker |
| G8 | 时间序列 one-way ANOVA / 缺交互 | high | F09 | **检出** | confirmed/high |
| G9 | 相关≠因果（EPS机制） | confirmed | F01+F07 | **检出** | 规则+LLM；soft-dup similar_different_mechanism |
| G10 | 28d盆栽→退化旱地外推 | major→可blocker | F02+F11 | **检出** | H3 为核心主张+短周期，升 blocker 符合 V0.1.3 外推策略 |

### Gold recall 汇总

| 口径 | 计数 |
|------|------|
| 关键问题正确检出（级别大体符合） | **8 / 10**（G1–G4,G7–G10） |
| 检出但级别/category 违反设计 | **1**（G6/F04） |
| 次要漏报 | **1**（G5 灭活/工艺空白） |
| 经典误报（缺空白 / 96孔伪重复 / 跨方案模具） | **0** |
| 软去重误关联 | **1 对**（F08→F05） |

**不要只看 Plan A：** 即使 blocker 动作覆盖 100%，科学检出仍有「单批次分级错误」与「次要对照漏报」。

## 3. Plan A blocker coverage（当前报告内 confirmed blocker）

| finding_id | severity | 标题摘要 | covered | change_note | 评价 |
|------------|----------|----------|---------|-------------|------|
| F02 | blocker | 由短周期/简化工况试验外推长期或工程依据过度 | True | C04 | 动作可执行 |
| F04 | blocker | 材料/菌剂为单批次制备，跨批次推广边界待明确 | True | C06 | 动作可执行；**但 F04 本不应是 blocker** |
| F05 | blocker | 水分处理与温室空间位置（长台层级）完全混杂 | True | C02 | 动作可执行 |
| F06 | blocker | 根际土壤取样后补入石英砂破坏土壤结构连续性，严重干扰团聚体与水分指标测定 | True | C07 | 动作可执行 |
| F11 | blocker | 将短期温室盆栽结果直接外推至退化旱地应用缺乏充分依据 | True | C08 | 动作可执行 |

- **Plan A blocker coverage** = **5/5 = 100%**
- `optimizer_incomplete` = `False`
- 非 blocker 的 high 项（F01/F07/F08/F09）亦有 C01/C03/C04 等对应笔记

## 4. 未通过门槛的根因（阻断 Trial 4）

**通过门槛**：关键科学判断稳定、blocker 有动作、无严重串台、**代表盆/单批次行为符合设计**。

| 门槛 | 判定 |
|------|------|
| 关键科学判断稳定 | **大体通过**（台面/海藻糖/破坏性/ANOVA/机制/外推均抓住） |
| blocker 有动作 | **通过**（100%） |
| 无严重串台 | **通过** |
| 代表盆符合设计 | **通过**（needs_info） |
| 单批次符合设计 | **失败** |

**根因（可复现）**：`adjust_extrapolation_severity()` 用标题/why 中是否含「推广/外推/工程…」决定是否改写严重度；`structural_single_batch_material` 标题含「跨批次**推广**边界」，在全文存在「退化旱地推广 + 28 d 盆栽」时被误升为 `confirmed/blocker`。离线复现：同 finding → 输出 `confirmed blocker`。

按用户拍板：**未通过则停止，不开 Trial 4**。本轮**不**为修此 bug 改科学 Prompt，也**不**针对 Trial3 加临时规则（修复属后处理收窄，留待决策）。

## 5. Claim–Evidence / Plan A 质量（摘要）

- CE01–03 有实质比较与指标；H2 `supports=no` 正确；单批次与代表盆进入 H1/H3 gap。
- Plan A：台面解耦、海藻糖助剂对照、牺牲盆、主张收紧、批次边界均有对应；**无** UV/水槽串台。
- 代价：因 F04 被当成 blocker，Plan A 多了一条「批次」动作（方向合理，但严重度叙事过重）。

## 6. 总判

| 项 | 结论 |
|----|------|
| 分层标注 | **LLM 实测** |
| Trial 3 V0.1.3 回归 | **未通过冻结验收门槛**（单批次误升 blocker） |
| Trial 4 | **blocked**（见同目录说明） |

