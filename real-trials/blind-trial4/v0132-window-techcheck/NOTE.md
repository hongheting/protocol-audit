# Trial4 审查窗技术验证（离线，非完整盲测重跑）

- **性质**：技术验证 / 离线重放（**非**真实 LLM 实测、**非**完整盲测）
- **目的**：确认 V0.1.3.2 方法优先窗相对旧 `full_text[:14000]` 能把方法/反应器相关文本送入审查输入
- **结果摘要**：全文 54327 字 → 3 窗送审；`methods_detected=true`，`methods_included=true`；送审片段含「材料与方法」「反应器」「接种」「水力」「MBGS」；`comprehensive=false`（仍有约 22k 字未入窗，boundary 不得声称全面审查）
- **产物**：`review_coverage.json`、`sent_W01.txt` … `sent_W03.txt`
