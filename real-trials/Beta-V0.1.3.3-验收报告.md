# ProtocolAudit Beta V0.1.3.3 验收报告

- **验收时间（Asia/Shanghai）**：2026-10-26T10:54:29+08:00
- **版本**：`0.1.3.3`（科学 Prompt 冻结于 V0.1.2）
- **授权**：用户消息 t15u
- **原则**：只修发布阻断；不扩展科学功能；不调参

---

## 是否存在阻断发布的问题？

# **否**

**依据：**

1. Trial1 / Trial3 轻量真实 LLM 抽检：调用可靠、无静默 facade、关键 finding 无严重退化；Trial3 热修前解析丢成果已修并重跑通过。
2. 七项发布检查：阻断项已修或已有防护；剩余为受控部署约束（网关鉴权、多实例限流、LLM 供应商数据处理说明）。
3. 科学 Prompt 哈希仍匹配 V0.1.2-freeze；`pytest` **38 passed**。
4. 决策确认的科学局限（G1 分级偏软、suggestion 不进 map、灭菌暂缓）**不构成上线阻断**。

**结论：可进入受控网站部署。** 一般性审查质量优化不推迟上线。

---

## 一、已通过

| 项 | 证据 |
|----|------|
| 决策落盘 | `Beta-V0.1.3.3-决策记录.md` |
| Prompt 冻结匹配 | design/review 哈希 = V0.1.2-freeze；`_beta_hashes.json` |
| Trial1 轻量 LLM 回归 | `Trial1-轻量回归.md`：核心 6/6；finish=stop；无 facade；Plan A blocker 6/6；S1/S2 误报 0 |
| Trial3 轻量 LLM 回归（热修后） | `Trial3-轻量回归.md`：关键 ~8–9/10；台面/海藻糖独立；单批次未误升 blocker；Plan A 4/4；无串台 |
| 审查完整性状态 | `review_status` / `boundary_note` / `findings.origin`；UI 展示 boundary + origin |
| 空 findings 不伪装完整 | 热修前 Trial3 已诚实声明失败；热修后完整；单测覆盖 |
| API Key 服务端保护 | `llm_client` 环境/文件密钥 + `_redact`；Web 无 key 字段 |
| 上传安全 | 8MiB 上限 + 扩展名白名单 + 去路径分量（冒烟：exe 拒绝） |
| 访问限流 | 60s/20 次滑动窗口（冒烟出现 429） |
| 失败提示 | flash 无 traceback |
| 生产 secret 守卫 | `PROTOCOL_AUDIT_ENV=production` 强制非默认 secret |
| Job 隐私保留 | 默认 TTL 24h + uuid4 32hex |
| 默认无公开文献检索 | `privacy_applied.public_literature_search_used=False` |
| confirmed blocker 严格覆盖 | 保留；suggestion 不进 map（决策） |
| pytest | **38 passed**, 1 deselected（`-m "not llm"`） |

---

## 二、未验证

| 项 | 说明 |
|----|------|
| 多 worker / 多机限流 | 当前为进程内存限流；网关限流未在本环境实测 |
| 反向代理鉴权 / TLS | 受控部署侧配置，本验收未搭公网 |
| 真实用户长传 PDF/扫描件 OCR | 本轮仅 Word Trial1/3 |
| Trial2/4/5 本轮真实 LLM 复测 | 非本轮范围；Trial5 既往 V0.1.3.3 有条件通过可参考 |
| LLM 供应商侧数据保留策略书面确认 | 需运营/法务跟进，非代码门禁 |
| 进水灭菌追问 | 决策暂缓 → 功能未做 |

---

## 三、已知限制

| 项 | 说明 | 后续 |
|----|------|------|
| G1 空间混杂分级偏软 | 可不升 blocker；不加关键词规则 | 结构化处理分配/空间摆放字段 |
| suggestion ∉ blocker_action_map | 仅 confirmed blocker 强制覆盖 | 后续版本映射 |
| 进水灭菌类追问 | 暂缓 | 另立项 |
| Trial1 Plan A 非 blocker 文案偶发串台 | F15↔再生称量话术 | 不调参；质量债 |
| Trial3 G3 伪重复偏软、G5 次要漏报 | 与既往类似 | 不调参 |
| Web 无终端用户账号 | 知 URL 可读 job | **部署须访问控制** |
| 启用 LLM 时正文外发智谱 | 产品能力所需 | 站点隐私说明 |
| Flask 无独立请求超时中间件 | 依赖网关超时；LLM urlopen 300s | 网关配置 |
| debug | 仅 `PROTOCOL_AUDIT_DEBUG=1` 且非 production | 部署勿开 |

---

## 发布检查七项一览（绿/黄）

| # | 检查 | 灯 | 备注 |
|---|------|----|------|
| 1 | 文件上传安全 | 绿 | 白名单+大小+路径 |
| 2 | API Key 服务端保护 | 绿 | |
| 3 | 访问限流 | 绿（单进程）/ 黄（多实例） | 网关加持 |
| 4 | 超时处理 | 绿（LLM）/ 黄（Web 网关） | |
| 5 | 失败提示 | 绿 | |
| 6 | 审查完整性状态 | 绿 | |
| 7 | 未发表方案隐私 | 绿（TTL+无公开检索）/ 黄（须反代鉴权+供应商说明） | |

---

## 产物索引

- 决策：`real-trials/Beta-V0.1.3.3-决策记录.md`
- 冻结：`real-trials/Beta-V0.1.3.3-freeze.md`
- 抽检：`real-trials/beta-spotcheck-t1-t3/`
- 发布证据：`real-trials/beta-spotcheck-t1-t3/Beta-发布检查证据.md`
