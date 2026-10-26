# Beta 发布检查证据（V0.1.3.3）

检查时间（Asia/Shanghai）：见验收报告冻结时间。  
原则：只修发布阻断；科学功能不加规则/不调参。

## 1. 文件上传安全

| 项 | 证据 | 状态 |
|----|------|------|
| 大小上限 | `web/app.py` `MAX_CONTENT_LENGTH` / `PROTOCOL_AUDIT_MAX_UPLOAD_BYTES` 默认 **8 MiB**；`/health` 回报 `max_upload_bytes` | 通过 |
| 扩展名白名单 | 仅 `.docx` `.pdf` `.md` `.markdown` `.txt`；`evil.exe` 冒烟被拒（302 回首页 + flash） | 通过（本轮阻断修复） |
| 路径穿越 | `Path(f.filename).name` 去目录分量；job 目录仅接受 hex id | 通过 |
| 落盘名 | 统一 `upload.bin`，不沿用用户路径 | 通过 |

## 2. API Key 服务端保护

| 项 | 证据 | 状态 |
|----|------|------|
| 密钥来源 | `protocol_audit/llm_client.py` 自 `/workspace/secrets/*.env` 或进程环境变量读取 | 通过 |
| 不进前端 | `web/app.py` / templates **无** key 字段或传递 | 通过 |
| 日志脱敏 | `_redact()` 对 api_key/authorization/bearer/token；长串替换 | 通过 |
| 生产密钥守卫 | `PROTOCOL_AUDIT_ENV=production` 时强制非默认 `PROTOCOL_AUDIT_SECRET`（冒烟 RuntimeError） | 通过（本轮阻断修复） |

## 3. 访问限流

| 项 | 证据 | 状态 |
|----|------|------|
| 滑动窗口 | 默认 60s / 20 次，覆盖 `/upload` `/audit` `/supplement`；超限 flash + HTTP 429 | 通过（本轮阻断修复） |
| 可配置 | `PROTOCOL_AUDIT_RATE_WINDOW_S` / `PROTOCOL_AUDIT_RATE_MAX` | 通过 |
| 说明 | 进程内内存限流，多 worker 需网关限流加持 → 记入已知限制 | 已知限制 |

## 4. 超时处理

| 项 | 证据 | 状态 |
|----|------|------|
| LLM HTTP | `urlopen(..., timeout=300)`；瞬时网络错误最多 3 次退避重试 | 通过 |
| 截断扩容 | 审查侧最多一次 expand retry（V0.1.3.3）；失败标记 `review_status=partial\|failed`，禁止静默空 findings | 通过 |
| Web 请求 | Flask 同步调用，无独立请求级超时中间件；依赖反向代理超时 | 已知限制（受控 Beta 由网关配置） |

## 5. 失败提示

| 项 | 证据 | 状态 |
|----|------|------|
| 解析/审查失败 | `flash("解析失败：…")` / `flash("审查失败：…")`，**不再**附带 traceback | 通过（本轮阻断修复） |
| 限流/类型错误 | 有明确中文提示 | 通过 |
| hard_fail | LLM 解析失败抛 `LLMParseError`，不启发式伪装成功（pipeline） | 通过 |

## 6. 审查完整性状态

| 项 | 证据 | 状态 |
|----|------|------|
| `review_status` | `llm_review.py` → complete/partial/failed；写入 `boundary_note` | 通过 |
| `findings.origin` | schema `$defs.Finding.origin`：llm_review / rule / partial_fallback | 通过 |
| UI 展示 | `report.html` 展示 `boundary_note`、`coverage_note`、`origin=` 标签 | 通过（本轮补强） |

## 7. 未发表实验方案数据隐私

| 项 | 证据 | 状态 |
|----|------|------|
| 默认无公开文献检索 | `privacy_applied.public_literature_search_used=False` | 通过 |
| 任务保留 | 默认 `PROTOCOL_AUDIT_JOB_TTL_HOURS=24`，过期目录清理 | 通过（本轮阻断修复） |
| Job 熵 | uuid4 hex 32 字符（原 12） | 通过（本轮阻断修复） |
| 无账号鉴权 | 知 URL 即可读该 job；**受控 Beta 须置于反向代理/邀请访问之后** | 已知限制 |
| LLM 外传 | 启用真实 LLM 时方案正文会发往智谱 Coding API（产品能力所需）；密钥与日志脱敏，但不等于「数据不出境」 | 已知限制（须在站点说明） |
| 日志 | `logs/llm/calls-*.jsonl` 含 content_preview（响应摘录），部署时应限制文件系统权限且勿公开挂载 | 已知限制 |

## 阻断判定（发布检查维度）

本轮已修补的曾属阻断项：扩展名白名单缺失、无限流、生产弱 secret、debug 默认开启风险、失败提示带 traceback、短 job id + 无限期保留。

剩余项均为**受控部署约束**（网关鉴权、多实例限流、LLM 供应商数据处理说明），不单独构成「代码未就绪」阻断——前提是部署时设置 `PROTOCOL_AUDIT_ENV=production` + 强 `PROTOCOL_AUDIT_SECRET`，并置于访问控制之后。

## 附录：本轮阻断级可靠性热修（审查 expand）

| 问题 | 热修前现象 | 修复 | 验证 |
|------|------------|------|------|
| expand 覆盖首轮 | Trial3 首轮/扩容均返回 findings 线索，但扩容 JSON preamble（如 \`\`\`3WQ…\`\`\`）解析失败后 **丢弃全部 LLM findings**，仅剩规则 | `llm_review.py`：扩容不可用时回退可用首轮；`llm_client.extract_json_object` 优先定位 \`\`\`json 并跳过非 json fence | 单测 `test_review_keeps_first_when_expand_worse`；Trial3 重跑 llm_review=6、review 完整 |
| 静默伪装 | 热修前 boundary 已声明失败（**未**伪装） | 保持 pretend_complete=False | trial3-pre-fix 与热修后对照 |

此修复属**发布阻断可靠性**，非科学功能扩展；科学 Prompt 未改。
