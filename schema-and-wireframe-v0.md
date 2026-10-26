
> **已拍板（扫描表）**：文本层表 P0；扫描表 OCR 为 P1；失败 → 警告 + 粘贴（`manual_input`）仍过验收；缺关键信息则有限审查，禁「全面审查」。ParsePreview 存储另议。

# ProtocolAudit · 数据模型 + 页面线框（v0.2.1）

日期：2026-10-25 Asia/Shanghai  
依赖：`V0.1-产品范围.md`、`架构-工作流-v0.md`  
状态：**设计 / schema only，无可运行原型**  
Schema：请求/预览 **0.2.0**；报告 **0.2.1**（`quote_location` → `locations[]` 为破坏性变更）

---

> **已拍板（2026-10-25）**  
> - 请求可用 `protocol_text` **或** `source_file`（docx/pdf）；解析后进 ParsePreview。  
> - **用户确认**结构化设计后，才 `confirm_design=true` 启动审查。  
> - findings 必带结构化 `SourceLocator`；Word 不依赖页码。  
> - Word/文本层 PDF **表格**必须可靠解析；图片/流程图进 `unparsed_assets`。

## 1. 结论与定位

- **核心判断**：按此方案做完，数据能否回答科学问题。
- **核心分析品牌**：Claim–Evidence Mapping。
- **中间态** `ParsePreview`：摄取块 + 可编辑设计 + 未解析资产 + 确认状态。
- **输入** `AuditRequest`：原文或文件 + 可选 `design_override` / `confirm_design` + 学科 / 目标层级 / 隐私 / 追问答复。
- **输出** `AuditReport` **0.2.1**：`ingest_manifest` + `design_confirmation` + 识别卡 + claim_evidence_map + clarifying_questions + findings（`locations`）+ optimizer Plan A + 分组表 + 结论条。
- **页面**：上传 → **确认步** → 单屏三栏（左原文+定位高亮；中 Claim–Evidence；右追问/findings/Plan A）；顶栏未解析资产横幅。

---

## 2. 相对 v0 / 0.2.0 的关键增量

| 增量 | 说明 |
|---|---|
| `ParsePreview` | 确认闸门中间对象 |
| `ingest_manifest` | source_file、parse_warnings、blocks/tables 计数、unparsed_assets |
| `design_confirmation` | pending \| confirmed |
| `SourceLocator` / `locations[]` | **取代**字符串 `quote_location`（报告升 **0.2.1**） |
| `confirm_design` / `design_override` | 请求侧 kickoff 标志与用户编辑结构 |
| `research_goal_level` 等 | 同 0.2.0（主张层级、三分法 findings、Optimizer A…） |

**文献铁律**：`evidence_refs[].verified` 必须为真才可作为依据；无核实不得填 DOI；禁止编造。

---

## 3. `SourceLocator`（原文定位）

必填：`source_file`、`original_text`。  
可选：`media_type`、`page_number`（PDF 优先；Word 通常 null）、`paragraph_id`、`table_id`、`section_path`、`char_start`/`char_end`。

Finding：`locations` 数组，**minItems: 1**。  
Claim–Evidence 行 / 提取字段 / 追问：尽量附 `locations`。

---

## 4. 输入摘要：`AuditRequest`（0.2.0 + 附加字段）

`protocol_text`（≥40，若无文件）**或** `source_file`。

可选：`discipline`、`language`、`research_goal_level`、`privacy`、`focus[]`、`clarifying_answers[]`、`meta`、`parse_options`（含 `prefer_tables`）、**`confirm_design`**、**`design_override`**。

Kickoff 完整审查时：`confirm_design` 应为 `true`。

完整机读：`audit-request.v0.2.schema.json`。

---

## 5. 中间态：`ParsePreview`（0.2.0）

必填：`schema_version`、`source_file`、`ingested_blocks`、`extracted_design`、`unparsed_assets`、`parse_warnings`、`user_confirmed`。  
可选：`user_edits_summary`、`confirmed_at`、`tables_parsed_count`。

机读：`parse-preview.v0.2.schema.json`；样例：`examples/sample-parse-preview.v0.2.json`。

---

## 6. 输出摘要：`AuditReport`（0.2.1）

### 6.1 顶层必填

`schema_version`（const **`0.2.1`**）、`discipline_resolved`、`boundary_note`、`research_goal_level`、`research_goal_level_source`、**`ingest_manifest`**、**`design_confirmation`**、`identification`、`claim_evidence_map`、`findings`、`clarifying_questions`、`optimizer`、`group_table`、`summary`。

有 `unparsed_assets` 时，`boundary_note` 须声明审查**未声称**覆盖这些资产。

### 6.2 Finding（主交互单元）

| 字段 | 含义 |
|---|---|
| severity | blocker \| high \| medium \| low |
| category | confirmed \| needs_info \| suggestion |
| **locations** | `SourceLocator[]`（≥1） |
| evidence_class / evidence_refs | 核实才展示依据 |
| estimated_burden / hard_error | 负担与硬错误 |
| why_invalidates / fix | 对主张的影响与改法 |

UI：定位芯片示例 — `¶ p-28` / `表 tbl-1` / `p.3`。

### 6.3 Optimizer（仅 A）

`plan_id` const `"A"`；`revised_group_table` + `change_notes`。

### 6.4 Reverse Review stub

同前；完整模式延后。

---

## 7. 页面线框（V0.1）

### 7.1 确认步（上传后、审查前）

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ProtocolAudit · 确认解析结果          [学科 ▾] [目标层级 ▾]  🔒 公开文献: 关  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ⚠ 未解析资产：流程图 U01（§2.1）— 本次审查不会声称覆盖该图                    │
├────────────────────┬─────────────────────────────────────────────────────────┤
│ 原文预览（可滚动）  │ 可编辑结构化设计                                         │
│ 段落/表格锚点高亮   │ 问题 / 假设 / 组 / 对照 / 重复 / 终点 / 统计 … + 状态色点 │
│ 表 tbl-1 已解析 ✓  │ [恢复自动提取]                                           │
│                     │                                                         │
│                     │ [取消]  [确认并开始审查]  ← confirm_design=true          │
└────────────────────┴─────────────────────────────────────────────────────────┘
```

### 7.2 审查主屏

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ ProtocolAudit          [学科 ▾] [目标层级 ▾] [语言]   🔒 公开文献检索: 关    │
│ ⚠ 未解析：流程图×1（见 ingest_manifest）                                      │
├────────────────────┬───────────────────────────────┬─────────────────────────┤
│ 方案原文            │ Claim–Evidence Mapping         │ ⚠ 待确认（追问）        │
│ ┌────────────────┐ │ ┌主张│证据│判断│缺口┐          │ Q01 三个平行=批次还是孔？│
│ │ 高亮 ¶ / 表 /页 │ │ │ … │ … │ … │ … │          │ [回答后继续审查]         │
│ │                │ │ └──────────────────┘          │                         │
│ │                │ │ 识别卡 + 状态色点               │ Findings                 │
│ └────────────────┘ │ 结论：awaiting_clarification   │ ● F01 高·待核实          │
│ 来源: demo.docx     │                               │   芯片: ¶p-28 · §2.3     │
│ [复审]              │                               │ Plan A 最小必要修改      │
│                     │                               │ [导出 MD] [导出 CSV]    │
└────────────────────┴───────────────────────────────┴─────────────────────────┘
窄屏：确认步 → 原文 → 追问 → Claim–Evidence → Findings → Plan A
```

### 交互状态

| 状态 | UI |
|---|---|
| idle | 等待上传/粘贴 |
| parse_preview | 确认步；未确认不可终审 |
| running | 按钮 loading |
| awaiting_clarification | 右侧追问置顶 |
| done | 填满；可改结构或答追问后复审 |
| error | 顶栏错误，不吞原文 |

### 页面层不做（V0.1）

- 登录、历史版本树、多人协作
- Plan B/C 切换、模拟审稿人三栏
- 独立文献结果页（证据挂在 finding 行上）
- 自动「看懂」位图流程图（仅标记未解析）

---

## 8. 机读文件

| 文件 | 说明 |
|---|---|
| `audit-request.v0.2.schema.json` | 请求 schema（含 confirm_design / design_override） |
| `parse-preview.v0.2.schema.json` | 解析确认中间态 |
| `audit-report.v0.2.schema.json` | 报告 schema **0.2.1** |
| `examples/sample-*.v0.2.json` | 样例（报告 schema_version=0.2.1） |
| `audit-request.v0.schema.json` / `audit-report.v0.schema.json` | 弃用指针 |

---

## 9. 建议下一步（工程，非本文范围）

1. 实现 Ingest（docx 段落/表、PDF 文本层+表）→ ParsePreview UI  
2. 确认闸门后再跑 Design Object → 规则引擎 → Review → Optimizer A  
3. 并行测试集（见 `测试集规划-v0.md`）；定位准确率按 `SourceLocator` 命中评
