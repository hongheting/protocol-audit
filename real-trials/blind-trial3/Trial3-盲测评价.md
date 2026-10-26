# Trial 3 盲测评价（V0.1.2 科学冻结 + V0.1.2.1 可靠性补丁）

- **评价时间（Asia/Shanghai）**：2026-10-25T21:47:07+08:00
- **代码版本**：`0.1.2.1`（= V0.1.2 + reliability patch）
- **科学 Prompt 哈希（正文）**：
  - design_extract：`241f78e5f12e53bb7da427dfe40722ab4ad928d53f2b28c45c466df7fdd4713b`
  - scientific_review：`26285e01f779200741af462d998367bab72158191fb533499f53a468bfd64705`
  - **与 V0.1.2-freeze 对照**：`True`（必须为 True）
- **模式**：真实 LLM 实测（智谱 Coding / glm-4.6）；**未**注入人工 gold；**未**为 Trial3 增加临时规则；**未**改科学 Prompt。
- **通过类型标注**（本文件）：以下「检出」均指 **LLM 实测流水线产出**（解析+规则+LLM审查+CE+PlanA），不是离线重放、也不是仅规则单测。

## 0. 运行可靠性（本轮补丁验收）

| 项 | 结果 |
|----|------|
| 首次 design_extract | `finish_reason=length`，completion_tokens=8192，JSON 解析失败 |
| 扩容重试 | **一次** → max_tokens **16384**，`finish_reason=stop`，JSON **成功** |
| 静默启发式回退 | **未发生**（`fallback=false`，`hard_fail=false`，`ok=true`） |
| boundary | `引擎：V0.1.2.1 结构规则（可靠性补丁；科学 Prompt 未改）+ LLM 解析+ LLM 科学审查` |
| schema | OK |
| 调用 | 3 次：`design_extract` + `design_extract_expand_retry` + `scientific_review` |
| token | prompt=10873 / completion=21026 / reasoning=11961 / total=31899 |
| 墙钟 | 539.6 s（Asia/Shanghai 起止见 call-summary） |
| 成本 | 未知（按决策不补单价表） |

产物目录：`real-trials/blind-trial3/`（design-extract / parse-preview / audit-report / call-summary / run.log / cli-summary / trial3_raw.txt）。

---

## 1. 执行者独立科学阅读（评价用金标准，仅存本文，未写入生产）

方案：`Bacillus velezensis` EPS 菌剂 × 土壤(L/R) × 水分(W/D) 的 2×2×2 温室盆栽（28 d，每组合 4 盆，每盆 3 株）。

### 1.1 实验单位与空间布局（应检出）
1. **水分处理与台面位置完全混杂**：W 统一上层长台、D 统一下层长台，且保持原位 → 水分效应与垂直光温微气候不可分（**blocker 级**）。
2. **组内灌水非独立**：按「代表盆」质量调整同组补水 → 盆间伪独立风险。
3. 分配单位为盆、株为盆内子样本；若以株作 n 会伪重复（方案写清 4 盆，但统计段落对重复测量用 one-way，单位风险仍在）。

### 1.2 菌剂处理及对照（应检出）
4. **I+ 含海藻糖保护剂，I− 仅无菌生理盐水** → 活菌与海藻糖助剂混杂（**high/blocker**）。
5. 缺少灭活菌/无菌培养上清等工艺对照（次要于海藻糖，但机制主张需要）。
6. **同一批培养菌液**用于全部接种 → 跨批次推广受限（按冻结决策：宜 **needs_info**，不一律 confirmed）。

### 1.3 重复测量（应检出）
7. 株高/SPAD 同株重复测量，却按日做 **one-way ANOVA** → 忽略重复测量相关与析因交互。
8. **D7–D21 取根际土后补石英砂** + **D14 拔除 1 株** → 破坏终点土壤结构与盆内密度可比性（**blocker**）。

### 1.4 统计模型（应检出）
9. 终点三因素 ANOVA 合理；动态指标 one-way 不合理；应 RM / 混合模型并报告水分×菌剂等交互（H1「缓解干旱」依赖交互）。

### 1.5 机制证据（应检出）
10. H2 以 Pearson 相关 +「同向增加」作 EPS 主机制证据 → **相关≠因果**（confirmed）。

### 1.6 工程外推（应检出）
11. H3：28 d 盆栽 → 退化旱地推广 → 过度外推（至少 suggestion/confirmed 边界收紧）。

---

## 2. 流水线产出对照

### 2.1 Findings 一览（报告内；rule_id 写出前被 schema 剥离，起源由离线对照规则集重建）

| ID | category/severity | 标题 | 起源（重建） | 评价 |
|----|-------------------|------|--------------|------|
| F01 | confirmed/high | 相关性/表征共变不足以支持主要机制主张 | **规则** `structural_corr_not_cause`（merge 主题去重可能抑制同类 LLM 条） | **真阳**（机制） |
| F02 | needs_info/high | 「平行/重复」独立性未写清 | **规则** `legacy_ambiguous_parallel` | **部分合理 needs_info**（盆 n=4 已写清；株/技术重复边界仍值得追问） |
| F03 | confirmed/blocker | 灌水处理与温室台面位置完全混杂 | **LLM 审查** | **真阳**（布局，关键） |
| F04 | confirmed/high | 接种液助剂海藻糖与菌剂效应混杂 | **LLM 审查** | **真阳**（对照） |
| F05 | confirmed/blocker | 破坏性采样破坏终点完整性 | **LLM 审查** | **真阳**（重复测量/终点） |
| F06 | confirmed/high | 时间序列 one-way 丧失析因交互 | **LLM 审查** | **真阳**（统计） |
| F07 | suggestion/medium | 盆栽外推田间退化旱地缺乏依据 | **LLM 审查** | **真阳偏弱分级**（外推；宜至少 high/confirmed 边界，但方向正确） |

离线规则集对本方案额外触发（写入前）：[["structural_corr_not_cause", "confirmed", "相关性/表征共变不足以支持主要机制主张"], ["legacy_ambiguous_parallel", "needs_info", "「平行/重复」独立性未写清"]]

结构规则**未**命中台面混杂/海藻糖/石英砂破坏（关键词面向挂板/助溶剂/结晶紫等），本轮由 LLM 补上——符合「冻结规则、不扩规则」的盲测设定。

### 2.2 规则 × LLM 重复情况（决策 2：只记录，不去重改造）

- 最终报告 **无同标题双条**。
- `merge_findings` 会按标题 token（机制/混杂/破坏性/外推等）做**软去重**：F01 为规则条后，同类 LLM「机制」意见可能被跳过。
- 本轮 **未见**「同一缺陷规则条 + LLM 条并列」的硬重复；与 Trial2 体积/鸡尾酒类重复不同。
- **记录结论**：Trial3 最终 findings 层重复 = **0**；软去重可能减少 LLM 机制表述多样性（信息损失风险，非本轮修复范围）。

### 2.3 真阳 / 漏报 / 误报统计（相对 §1 评价金标准）

| 类别 | 计数 | 说明 |
|------|------|------|
| **真阳（confirmed 命中真实缺陷）** | **5** | F01 机制；F03 台面；F04 海藻糖；F05 破坏性取样；F06 错误 ANOVA |
| **真阳（suggestion/边界）** | **1** | F07 外推（方向对，严重度偏低） |
| **needs_info 合理** | **1** | F02 单位边界追问（非误报） |
| **误报** | **0** | 未出现「缺空白对照」「96 孔伪重复」；未串 UV/水槽/挂板话术 |
| **漏报（重要）** | **2–3** | ①「代表盆」灌水导致组内盆非独立；② 单批次菌液对跨批次推广的限制（宜 needs_info，本轮未出）；③ 灭活菌/工艺空白相对海藻糖为次要漏报 |
| **Plan A 未覆盖的已检出 blocker** | **2** | F03 台面随机化/区组；F04 海藻糖载体对照——**findings 已抓到但 change_notes 未地址化** |

### 2.4 六焦点核对

| 焦点 | 结果 |
|------|------|
| 实验单位与空间布局 | **通过（LLM）**：F03 精准引用上层/下层长台原文；F02 追问单位。漏：代表盆灌水。 |
| 菌剂处理及对照 | **通过（LLM）**：F04 海藻糖 vs 盐水。漏：单批次 needs_info；灭活对照。 |
| 重复测量 | **通过（LLM）**：F05 石英砂+拔株；F06 RM/析因。 |
| 统计模型 | **通过（LLM）**：F06；终点三因素未被误杀。 |
| 机制证据 | **通过（规则）**：F01 + CE02 supports=no。 |
| 工程外推 | **部分通过**：F07 suggestion + CE03 supports=no；严重度可上调。 |

### 2.5 Claim–Evidence 科学一致性

| 行 | 主张 | design_supports | 评价 |
|----|------|-----------------|------|
| CE01 | H1 促生/缓旱 | partial | **有实质内容**（8 组比较、三因素、生长终点）。缺口仅写 F02 单位，**未把 F03/F04 blocker 写入 H1 gap** → 一致性偏弱。 |
| CE02 | H2 EPS 主机制 | no | **正确**：相关≠机制；指标对齐 EPS/MWD。 |
| CE03 | H3 双土壤+外推 | no | **正确**：短周期/简化体系外推。无 UV/水槽串台。 |

**结论**：CE **具备实质科学内容**（非仅去词），H 编号与比较/指标大体对齐；H1 对混杂 blocker 的 gap 覆盖不足。

### 2.6 Plan A 必要性 / 可执行性 / 与 findings 对应

| 笔记 | 对应 finding | 评价 |
|------|--------------|------|
| C01 析因交互，停 one-way 作协同 | F06 | 必要、可执行 |
| C02 独立牺牲样/终点破坏性 | F05 | 必要、可执行 |
| C03 收紧机制与外推主张 | F01, F07 | 必要、低负担 |
| C04 明确实验单位=盆 | F02 | 必要 |
| **缺失** | **F03, F04** | **不可接受缺口**：台面解耦与海藻糖载体对照是本方案最硬的设计修改，Plan A 未生成对应 change_note |

修订分组表保留 8 组并以「盆」为重复单位，**无串台**；未引入不必要新实验组堆叠——好。但因缺失 F03/F04，**Plan A 总评：部分合格**。

### 2.7 原文定位

F03/F04/F05/F06/F07 均带 paragraph_id 或 table_id 与可核对摘录；F01 摘录窗口略宽（含 H3 邻近句）但仍落到机制表述。**定位总体合格**。

---

## 3. 串方案污染检查

- Plan A / CE / findings **未**出现 Trial1 水槽/UV/挂板，或 Trial2 锥形瓶吸附专有模具误套。
- 单位用语为「盆」、对照为海藻糖/生理盐水——与本方案一致。
- **无严重跨方案污染**。

---

## 4. 总判与验收口径

| 口径 | 判定 |
|------|------|
| 关键科学判断稳定（六焦点） | **大体通过**（5 真阳 confirmed + 外推方向正确） |
| 原文证据可追溯 | **通过** |
| 修改建议有效 | **部分通过**（Plan A 漏 F03/F04） |
| 无严重跨方案污染 | **通过** |
| 可靠性补丁在盲测中生效 | **通过**（截断→扩容成功，无伪装启发式成功） |
| **Trial3 盲测总评** | **有条件通过**：审查层强；交付层 Plan A 对已确认 blocker 覆盖不全；存在代表盆灌水与单批次 needs_info 漏报 |

**一句话**：Trial3 在真实 GLM 下抓住了台面×水分混杂、海藻糖对照、破坏性取样和错误 ANOVA，且可靠性扩容重试成功；但 Plan A 未落地前两项 blocker，并漏报代表盆灌水非独立。

---

## 5. 待决策（不在本轮改科学逻辑）

1. **Plan A 生成**：是否在下一版本让 change_notes **强制覆盖全部 confirmed blocker**（F03/F04 类）——属优化器逻辑，非科学 Prompt。
2. **外推分级**：F07 是否默认至少 `confirmed/high` 当 H3 含「推广应用依据」。
3. **代表盆灌水**：靠 LLM 偶发还是将来加通用结构规则（冻结期后另议）。
4. **单批次材料**：维持 needs_info 文案模板是否在 CE/追问中固定出现（决策 3 已定不升 confirmed）。
5. **merge 软去重**：是否改为「记录重复对」而非丢弃 LLM 条（决策 2 说 Trial3 先记录；本轮最终层重复为 0）。

---

## 6. 产物路径

- 评价：`real-trials/blind-trial3/Trial3-盲测评价.md`
- 报告：`real-trials/blind-trial3/audit-report.json`
- 解析：`real-trials/blind-trial3/design-extract.json`
- 调用：`real-trials/blind-trial3/call-summary.json`
- 日志：`real-trials/blind-trial3/run.log`
- 可靠性说明：`real-trials/regression-v012/V0.1.2.1-reliability-note.md`
