# ProtocolAudit Beta V0.1.3.3 冻结说明

- **冻结时间（Asia/Shanghai）**：2026-10-26T10:54:29+08:00
- **版本字符串**：`protocol_audit.__version__ = "0.1.3.3"`
- **决策依据**：`real-trials/Beta-V0.1.3.3-决策记录.md`（用户授权 t15u）
- **验收报告**：`real-trials/Beta-V0.1.3.3-验收报告.md`
- **哈希清单**：`real-trials/beta-spotcheck-t1-t3/_beta_hashes.json`

## 冻结声明

1. **科学 Prompt 继续冻结于 V0.1.2**（哈希必须匹配下方表）；不得为一般审查质量优化改 Prompt / 加科学规则。
2. **G1 空间混杂分级偏软**、**suggestion 不进 blocker_action_map**、**进水灭菌追问暂缓** — 见决策记录，记入已知限制。
3. 本 Beta 包含：
   - V0.1.3.3 基线（审查截断扩容、CE scope_note、finding.origin）
   - **阻断级可靠性热修**：expand 失败回退首轮可用 findings；JSON 提取容忍 preamble fence
   - **阻断级 Web 硬化**：扩展名白名单、限流、生产 secret 守卫、失败无 traceback、job TTL、报告展示 origin/隐私摘要

## Prompt 哈希（须与 V0.1.2-freeze 一致）

| Prompt | sha256 |
|--------|--------|
| design_extract (`llm_parse.SYSTEM_PROMPT`) | `241f78e5f12e53bb7da427dfe40722ab4ad928d53f2b28c45c466df7fdd4713b` |
| scientific_review (`llm_review.SYSTEM`) | `26285e01f779200741af462d998367bab72158191fb533499f53a468bfd64705` |

`prompt_match_v012_freeze`: **true**

## 抽检锚点

| Trial | 产物 |
|-------|------|
| Trial1 | `real-trials/beta-spotcheck-t1-t3/trial1/` + `Trial1-轻量回归.md` |
| Trial3 | `real-trials/beta-spotcheck-t1-t3/trial3/` + `Trial3-轻量回归.md`（`trial3-pre-fix/` 为热修前对照） |

## 测试

- `PROTOCOL_AUDIT_LLM=off pytest tests/ -m "not llm"` → **38 passed**（1 deselected）

## 部署前置（受控 Beta）

```bash
export PROTOCOL_AUDIT_ENV=production
export PROTOCOL_AUDIT_SECRET='<strong-random>'
# 可选：PROTOCOL_AUDIT_JOB_TTL_HOURS / RATE_* / MAX_UPLOAD_BYTES
# LLM：source /workspace/secrets/bigmodel-coding.env（仅服务端）
# Basic auth：PROTOCOL_AUDIT_DEMO_PASSWORD（ACA secret）；用户默认 demo
# 自定义域：protocol.jassyhong.top（灰云 DNS）
# 必须置于反向代理 / 邀请访问之后（应用内无终端用户账号；Beta = Basic）
```

**无代码侧发布阻断问题时，可进入网站部署；一般性审查质量优化不推迟上线。**

## 部署包装（2026-10-26，文档就绪）

- 子域已确认：**`protocol.jassyhong.top`**（非 audit）
- Dockerfile / ACR / ACA / Basic 注入：**Jassy 主写**（勿覆盖 `web/Dockerfile`）
- 交接与冒烟：`real-trials/Beta-部署交接-JassyKing.md`

