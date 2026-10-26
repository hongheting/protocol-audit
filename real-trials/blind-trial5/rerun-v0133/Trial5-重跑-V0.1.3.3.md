# Trial 5 重跑评价（V0.1.3.3 / 真实 glm-4.6）

- **时间（Asia/Shanghai）**：2026-10-25T23:24:58+08:00 → 2026-10-25T23:29:57+08:00（墙钟 **298.8 s**）
- **代码版本**：`0.1.3.3`
- **科学 Prompt**：冻结于 **V0.1.2**；哈希 **匹配** = `True`
  - design_extract `241f78e5f12e53bb7da427dfe40722ab4ad928d53f2b28c45c466df7fdd4713b`
  - scientific_review `26285e01f779200741af462d998367bab72158191fb533499f53a468bfd64705`
- **模型**：glm-4.6（真实调用；无金标准注入；未扩单批次正则；未加灭菌规则；空间混杂规则本轮不纳入）
- **输入**：`real-trials/trial5.docx`（与盲测同一文件）
- **产物目录**：`real-trials/blind-trial5/rerun-v0133/`
- **测试类型标注**：真实LLM实测 / 规则测试 / 离线重放

> **验收纪律**：schema 通过 ≠ 科学审查通过。下文四维分开评价。

---

## 1. 解析完整性

| 项 | 结果 | 类型 |
|----|------|------|
| Word 摄入 | 正常；分组 C0/S3/CA1/3/5、对照、统计计划抽出 | 真实LLM实测 |
| review_coverage | comprehensive=`True`，truncated=`False`，methods_detected=true | 规则/技术 |
| 解析 finish_reason | `stop`（未触顶；expand_retry=false） | 真实LLM实测 |

**解析维：通过。**

---

## 2. 审查可靠性与 LLM 实际贡献

| 项 | 盲测 V0.1.3.2 | 本轮 V0.1.3.3 |
|----|--------------|--------------|
| scientific_review finish_reason | **length**（8192 触顶） | **stop**（completion≈5127） |
| 扩容重试 | 无逻辑 | 未触发（首次即完整） |
| review_status | （旧路径伪装“成功”但 findings≈规则） | **complete** |
| findings.origin | 无 | rule=2，llm_review=2 |
| 相对 rules-only 增量 | ≈0 | **2 条**（空间混杂；破坏性取样扰动） |

调用：n=2，expand_retry=0，tokens={'prompt': 7024, 'completion': 11832, 'reasoning': 8307, 'total': 18856}，耗时解析≈160s / 审查≈138s。

**可靠性维：通过**（本轮未触顶；路径已具备截断→一次扩容→失败标 partial 的能力，单测覆盖）。

**LLM 贡献：有实质增量**（非规则-only 空转）。

---

## 3. 科学判断（对照盲测金标准 G1–G7；金标准仅评价用）

| 金标准 | 本轮输出 | 判定 |
|--------|----------|------|
| G1 处理×台面分区/位置固定混杂 | **F03** llm_review，title「处理效应与空间位置混杂」，原文定位正确；category=**suggestion**/severity=high | **检出**；严重度偏弱（期望 confirmed/high～blocker）→ **非关键漏报，但分级偏软** |
| G2 相关≠机制 | F01 rule confirmed/high | **真阳** |
| G3 单位/重复 | F02 needs_info | **部分合理**（与盲测同类） |
| G4 单批次 | 仍无独立 finding（本轮**不**扩正则，符合决策） | **已知次要缺口，接受** |
| G5 外推 | 无机械升 blocker；限制句改 scope_note | **合理** |
| G6 东湖水不灭菌 | 未报缺陷 | **正确** |
| G7 缺空白/96孔伪重复 | 未误报 | **正确** |
| 额外 | F04 破坏性移除扰动 needs_info/medium | 可接受的附加意见 |

跨方案串台：findings/Plan A **无** 水槽挂板话术污染、海藻糖、代表盆、生物炭、MBGS、缺空白等。

**科学维结论：有条件通过。**  
- 关键改进：G1 由漏报→检出，且依赖真实 LLM（可靠性修复生效）。  
- 残留：G1 被标为 `suggestion` 而非 `confirmed`（模型自主分级偏保守）；不因此堆规则掩盖。  
- **不以 schema 通过宣布科学满分。**

---

## 4. Claim–Evidence

| 行 | 结果 |
|----|------|
| CE01–03 | H1/H2/H3 分行，有实质比较；supports=partial |
| CE04 | **`row_kind=scope_note`**，`design_supports=yes`，判断为边界说明 | **CE04 限制句问题已修复** |
| 无 EXTRAP supports=no 伪主张 | 是 |

**CE 维：通过。**

---

## 5. Plan A

| 项 | 结果 |
|----|------|
| confirmed blocker 数 | **0**（F03 为 suggestion，未进 blocker 集合） |
| blocker_action_map | `[]` → 覆盖率形式 0/0 |
| 对 F03 | **C01** 明确要求随机化/区组化台面位置，解耦处理×空间 | **有效动作存在** |
| optimizer_incomplete | false |

**Plan A 维：对已检出问题有可执行修改；形式 blocker 覆盖率因分级偏软而为 0/0，不能单独作为通过依据。**

---

## 6. Trial 1–4 回归（分层）

见 `real-trials/regression-v0133/offline-regression.json`。

| Trial | 类型 | 要点 |
|-------|------|------|
| 1 | 离线重放 | Plan A 仍要求容器层面独立重复且不可仅换统计模型 |
| 2 | 离线重放 | 无 Trial1 UV/挂板串台 |
| 3 | 离线重放 | 单批次 needs_info；海藻糖≠台面 true_dup；blocker 覆盖保持 |
| 4 | 离线重放 | 无严重跨方案污染 |

本轮 **未** 对 Trial1–4 再跑全量真实 LLM（成本）；规则/单测门禁全绿。

---

## 7. 总评（分开，不合并通过率）

| 维度 | 结论 |
|------|------|
| 解析完整性 | **通过** |
| 审查可靠性 / LLM 贡献 | **通过**（相对盲测由规则空转→2 条 LLM 增量；finish_reason=stop） |
| 科学判断 | **有条件通过**（G1 检出但 suggestion 偏软；G4 按决策不扩正则） |
| Claim–Evidence | **通过**（CE04 scope_note） |
| Plan A | **实质动作通过 / 形式 blocker 覆盖不作为依据** |

**Trial 5 重跑总体：有条件通过（不再因审查触顶而科学空转；CE04 已修；G1 不再漏报）。**  
明确：**未**把 schema 通过等同于科学审查满分；G1 分级偏软记为未决，不堆关键词 blocker 规则掩盖。

---

## 8. 约束合规

- [x] 科学 Prompt 冻结且哈希匹配  
- [x] 不扩单批次正则；不加灭菌追问  
- [x] 空间混杂：验证后本轮不纳入规则（笔记已写）  
- [x] findings.origin 区分 LLM / 规则  
- [x] pytest 绿  

## 9. 未决 / 下一轮建议

1. G1 严重度：是否在解冻后用结构化「摆放方式」字段驱动，而非关键词 blocker？  
2. F03 为 suggestion 时 Plan A 已给动作，是否要把「高严重度 suggestion 的空间混杂」也纳入 blocker_action_map 校验？  
3. 是否对 Trial1/3 做一次便宜的真实 LLM 抽检确认无回归？  
4. 进水灭菌：仍暂缓。  
