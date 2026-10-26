# Trial 3 轻量真实 LLM 回归（Beta V0.1.3.3）

- **评价时间（Asia/Shanghai）**：2026-10-26T10:53:27+08:00（修复后重跑）
- **代码版本**：`0.1.3.3`（含本轮阻断级可靠性热修：expand 失败不丢首轮 findings；`extract_json_object` 容忍 preamble fence）
- **模式**：真实 LLM（glm-4.6）；**不调参、不加科学规则、不改科学 Prompt**
- **Prompt 哈希**：与 V0.1.2-freeze **一致**
- **输入**：`real-trials/trial3.docx`
- **产物**：`real-trials/beta-spotcheck-t1-t3/trial3/`
- **对照**：`real-trials/regression-v0131-llm/Trial3-真实LLM回归报告.md`、`blind-trial3/Trial3-盲测评价.md`
- **失败对照归档**：`trial3-pre-fix/`（热修前：审查 expand 后 JSON 解析失败 → llm_review=0，但 boundary **正确声明非完整 LLM 审查**，无静默伪装）

## 0. 调用可靠性

| 项 | 热修前 | 热修后（本评价） |
|----|--------|------------------|
| 墙钟 | 853.4 s | 677.6 s |
| finish_reason | stop×3 | stop×3 |
| expand | 1 | 1 |
| llm_review findings | **0** | **6** |
| review 声明 | failed（诚实） | **完整** |
| facade | False | False |
| schema | OK | OK |

**结论：热修前属发布阻断级「审查解析失败丢成果」；热修后调用/解析恢复。无静默伪装完整报告。**

## 1. 关键 finding（相对既往 Trial3 Gold 口径）

| ID | 金标准问题 | 期望 | 本轮 | 判定 |
|----|------------|------|------|------|
| G1 | 水分×台面/长台位置混杂 | blocker | F05 confirmed/blocker | **检出** |
| G2 | 代表盆指导整组灌水 | needs_info | F03 needs_info/medium | **检出** |
| G3 | 盆单位/株子样本伪重复风险 | needs_info | 无独立「伪重复」标题；仅间接 | **偏软/弱检出**（非整链失败） |
| G4 | 海藻糖保护剂混杂 | high | F06 confirmed/high | **检出** |
| G5 | 灭活菌/工艺空白 | 次要 | — | **漏报**（与既往一致，次要） |
| G6 | 单批次菌液 | needs_info | F04 needs_info/medium | **检出且未误升 blocker** |
| G7 | 破坏性取土+石英砂 | blocker | F07 confirmed/blocker | **检出** |
| G8 | 时间序列 one-way / 缺交互 | high | F08 confirmed/high | **检出** |
| G9 | 相关≠因果（EPS） | confirmed | F01+F09 | **检出** |
| G10 | 盆栽→旱地/大田外推 | blocker | F02+F10 | **检出** |

- 关键检出大体符合：**8–9 / 10**（G5 次要漏；G3 偏软）
- 台面 vs 海藻糖：F05/F06 均为 `duplicate_relation=none` → **独立**
- 串台（UV/水槽/挂板/生物炭/96孔/缺空白）：**0**
- 相对 V0.1.3.1：**无严重退化**（热修后）

## 2. CE / Plan A

- CE：按 H1/H2/H3 分行；supports 与机制/外推缺口方向正确；未见限制句误作 EXTRAP。
- confirmed blocker：**4**；`blocker_action_map` **4/4**；`optimizer_incomplete=False`
- suggestion **未**进入 blocker_action_map（符合决策）

## 3. 总判

| 门槛 | 判定 |
|------|------|
| 调用可靠性（含截断扩容） | **通过**（热修后） |
| 无 facade | **通过** |
| 关键检出无严重退化 | **通过** |
| 单批次不误升 blocker | **通过** |
| 台面 vs 海藻糖独立 | **通过** |
| Plan A blocker 覆盖 | **通过** 4/4 |

**Trial 3 轻量回归（热修后）：通过。**  
热修前失败样本保留为发布阻断证据与回归锚点。
