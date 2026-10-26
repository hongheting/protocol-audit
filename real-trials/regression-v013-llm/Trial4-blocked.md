# Trial 4 盲测状态：blocked

- **时间（Asia/Shanghai）**：2026-10-25T22:09:33+08:00
- **状态**：`blocked_trial3_gate_failed`
- **原因**：Trial 3 V0.1.3 真实 LLM 回归**未通过**「单批次行为符合设计」门槛（`F04` 被 `adjust_extrapolation_severity` 误升为 confirmed/blocker）。按用户拍板：**不得**在未通过时强行开启 Trial 4。

## 已预选但未执行的候选（供通过后使用）

若修复并重跑 Trial3 通过后，可用以下**未见、与 T1–T3 体系不同**的真实 Word（本轮**未**复制、**未**跑 LLM、**未**据其改规则）：

1. `/workspace/thesis/midterm/洪鹤庭-中期-3.2-CA@MSiO2-制备负载与释放.docx` — 肉桂醛@介孔硅制备/表征/释放（材料体系，异于 UV 微宇宙 / 镧生物炭 / 菌剂盆栽）
2. `/workspace/zt/luo.docx` 中藻-菌颗粒污泥 SBR 实验方法章节 — 污水 MBGS（体系完全不同；全文含大量综述，需确认以整份或节选作为输入）

**不要编造方案。** 若用户另有指定附件，以用户附件为准。

## 下一步建议（待拍板）

1. 收窄 `adjust_extrapolation_severity`：排除 `rule_id=structural_single_batch_material`，或要求标题同时含「外推/工程依据」等，避免「推广」误触发。
2. 收窄软去重：controls vs spatial confounding 不因同含「混杂」归组。
3. 修复后：再跑 **Trial3 真实 LLM** → 通过后再 **Trial4 盲测**；科学 Prompt 保持 V0.1.2 哈希不变。
