# ProtocolAudit Beta V0.1.3.3 决策记录

- **决策时间（Asia/Shanghai）**：2026-10-26（用户授权消息 id: t15u）
- **代码基线**：`protocol_audit.__version__ = "0.1.3.3"`
- **科学 Prompt**：继续冻结于 **V0.1.2**（design/review 哈希须匹配 `real-trials/regression-v012/V0.1.2-freeze.md`）
- **本阶段定位**：受控 Beta 发布验收；**只修发布阻断问题**，不继续扩展科学功能。

## 已确定决策

| # | 决策 | 执行约束 |
|---|------|----------|
| 1 | **G1 空间混杂分级偏软暂不修复** | 记为**已知局限**。未来靠结构化「处理分配 / 空间摆放」字段改善；**当前版本不增加关键词规则**。 |
| 2 | **suggestion 不进入 `blocker_action_map`** | 保留 **confirmed blocker** 的严格覆盖校验；其他 findings 的修改映射留待后续版本。 |
| 3 | **Trial 1 / Trial 3 各一次轻量真实 LLM 回归** | 重点：调用可靠性、解析、关键 finding、CE、Plan A 是否严重退化；**不进行新一轮调参**。 |
| 4 | **进水灭菌类追问继续暂缓** | 不加专用追问/规则。 |
| 5 | **科学 Prompt 继续冻结** | **不再增加规则和功能**（科学侧）。 |
| 6 | **完成 Beta 发布检查** | 文件上传安全、API Key 服务端保护、访问限流、超时处理、失败提示、审查完整性状态、未发表实验方案的数据隐私。 |
| 7 | **完成后冻结 Beta 版本** | 无阻断问题则进入网站部署；**一般性审查质量优化不推迟上线**。 |

## 明确不做（本轮）

- 不改写 `design_extract` / `scientific_review` Prompt 文本
- 不纳入空间混杂关键词 blocker 规则
- 不把 suggestion 级 finding 纳入 `blocker_action_map`
- 不加进水灭菌专用逻辑
- 不为提升 Gold 召回做调参或加规则

## 已知局限（决策确认写入）

1. **G1 空间混杂**：LLM 可检出但分级可能偏软（如 suggestion/high）；不在本版用关键词规则抬级。
2. **suggestion → Plan A**：无强制动作映射；仅 confirmed blocker 强制覆盖。
3. **进水灭菌类追问**：暂缓。

## 产物索引（本轮）

- 轻量回归：`real-trials/beta-spotcheck-t1-t3/`
- 冻结：`real-trials/Beta-V0.1.3.3-freeze.md`
- 验收：`real-trials/Beta-V0.1.3.3-验收报告.md`
