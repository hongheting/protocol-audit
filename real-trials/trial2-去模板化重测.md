# Trial2 去模板化重测（V0.1.2）

- **日期**：2026-10-25 Asia/Shanghai  
- **基线**：`trial2-独立验证评估.md`（V0.1.1：LLM findings 可用，CE/Plan A 串台）  
- **本轮**：去模板化 `claim_evidence.py` / `optimizer_a.py` + 通用结构规则最小集；**离线**用已保存 `trial2.llm-design-extract.json` 重建 structural findings + CE + Plan A（未改 review Prompt，故未强制二次 LLM）  
- **产物**：`trial2.llm-audit-report.v012.json`

## 1. Findings（结构规则为主）

| ID | rule_id | 标题 | 对应原评估 |
|----|---------|------|------------|
| F01 | structural_corr_not_cause | 相关性/表征共变不足以支持主要机制主张 | ≈原 F06 |
| F02 | structural_over_extrapolation | 短周期/简化工况外推过度 | 原漏报补强 |
| F03 | structural_factor_lock | 因素水平完全锁定混杂 | ≈原 F02 缓冲×pH |
| F04 | structural_uncorrected_depletion | 重复取样体积/质量未校正 | ≈原 F03 |
| F05 | structural_cocktail_attribution | 混合暴露却单一组分归因 | ≈原 F04 |
| F06 | structural_regen_mass_balance | 再生缺中间质量衡算 | ≈原 F05 |
| F07 | structural_process_blank | 改性相对基线缺工艺空白 | 原漏报 |
| F08 | （LLM 保留） | 「平行/重复」独立性未写清 | ≈原 F01 |

**结论**：F02–F04 类问题仍被抓住，并补上工艺空白与工程外推。

## 2. Claim–Evidence 串台检查

检索 CE JSON 中是否出现 Trial1 领域词：`UV` / `水槽` / `挂板` / `润湿` / `功能颗粒` / `涂层` / `微宇宙` / `取水口`。

**结果：零命中（NONE）。**

| 行 | 假设 | 比较句来源 | supports |
|----|------|------------|----------|
| CE01 | H1 机制 | 本方案分组 G0/G1/G2/D1–D4 + 机制表述 | no |
| CE02 | H2 pH/共存 | 同分组 + 因素初始pH、共存组分 | partial（锁定+鸡尾酒等） |
| CE03 | H3 再生 | 同分组 + 再生轮次 | partial（质量衡算） |
| CE04 | EXTRAP | 实验室 → 工程/连续运行 | no |

不再出现「2×2 颗粒×UV」「润湿性 vs 附着量」等 H 编号模板。

## 3. Plan A 可执行性

串台词检索：**零命中**。`replicate_unit` 为「锥形瓶/离心管」，**不是**水槽/挂板。

| 变更 | 内容 | 可执行？ |
|------|------|----------|
| C01 | 解耦锁定因素（同调节方式/正交对照） | ✅ 针对缓冲×pH |
| C02 | 混合暴露 → 单因子及必要组合 | ✅ 针对鸡尾酒归因 |
| C03 | 体积/质量衡算或分管取样 | ✅ 针对动力学 |
| C04 | 再生各轮称量校正投加量 | ✅ |
| C05 | 增加工艺空白（浸渍/热处理匹配） | ✅ 通用表述 |
| C06 | 收紧机制与工程主张 | ✅ |
| C07 | 显式实验单位=锥形瓶/离心管 | ✅ |

**未**再出现「降级 UV 主张 / 水槽层面重复」。

## 4. Trial1 回归（离线 sanity）

对 `trial1.llm-design-extract.json` 仅跑结构规则 + CE + Plan A：

- 仍检出容器混杂、伪重复、助溶剂、析因、破坏性 RM、机制、外推等  
- Plan A C01：**在处理分配单位（水槽）层面增加独立重复…不可仅换统计模型**（领域正确保留）  
- CE 比较句来自分组/因素（含本方案 UV/涂层字样属原文内容，非 H2 编号误触发）  
- 产物旁注：`trial1.ce-plana.v012-offline.json`

## 5. 测试与安全

```text
PROTOCOL_AUDIT_LLM=off pytest tests/ -m "not llm" -q
→ 11 passed, 1 deselected
```

新增：`test_generic_factor_lock_volume_cocktail_regen_process`、`test_claim_evidence_and_plan_a_no_trial1_bleed_on_adsorption`、`test_plan_a_trial1_still_mentions_allocation_unit_when_tank_findings`。

grep：`real-trials/gold`、trial2 专名（镧改性/La-BC 等）**未**进入 `protocol_audit/` 生产 Prompt；旧 `H2|协同` /「润湿性指标与附着」模板已清除。

## 6. 结论

| 标准 | 状态 |
|------|------|
| Trial2 CE/Plan A 零 Trial1 串台 | ✅ |
| Plan A 对本吸附方案可执行 | ✅ |
| 仍抓住锁定混杂/体积/鸡尾酒等 | ✅ |
| pytest 绿 | ✅ 11 passed |

**剩余缺口（非本轮必须）**  
- CE 对 treatment_effect 的 finding 关联仍可再收紧（H2 仍附带工艺空白，方向合理但非最精准）  
- 未二次真实 LLM review（结构规则已覆盖原 LLM 真阳；若改 review Prompt 再重跑）  
- Trial1 全量真实 LLM 回归可择机做；本轮离线 CE/Plan A 未崩  

**建议版本标记**：V0.1.2 去模板化。
