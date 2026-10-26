# ProtocolAudit Beta V0.1.3.3 — 部署交接（Jassy King）

- **时间（Asia/Shanghai）**：2026-10-26
- **版本**：`0.1.3.3`（科学 Prompt 冻结于 V0.1.2；本轮只做部署包装，不改审查规则/Prompt）
- **分工**：Dockerfile / Basic auth 注入 / ACR push / `ca-protocol-audit` / 灰云 DNS → **Jassy 主写**；本文档为执行者侧交接与冒烟清单，**勿覆盖 `web/Dockerfile`**。

## 1. 架构（与既有科研工具同款）

| 项 | 值 |
|----|-----|
| 区域 | Azure `japaneast` |
| Resource Group | `rg-refcheck` |
| Container Apps 环境 | `cae-refcheck` |
| ACR | `refcheck84ed97.azurecr.io` |
| Container App | `ca-protocol-audit` |
| 镜像建议 | `protocol-audit-beta:0.1.3.3`（或当日 tag） |
| 监听 | `0.0.0.0:$PORT`（默认 **8080**） |
| 探活 | `GET /health`（**免 Basic auth**） |
| CPU / 内存 | 0.5 / 1.0Gi |
| 副本 | min 0 / max 1 |
| **自定义域名（已确认）** | **`protocol.jassyhong.top`**（不是 `audit.*`） |
| DNS | Cloudflare **灰云 DNS only**（不要橙云） |
| 先例 | `ref.jassyhong.top` / `journal.jassyhong.top` / `tools.jassyhong.top` |

应用：Flask（`web.app:app`）+ gunicorn。无终端用户账号；受控 Beta 靠 **Basic auth**（对齐文献核对：用户 `demo` + ACA secret 注入密码）。

## 2. 环境变量清单

### 非密钥（可明文 `--set-env-vars`）

| 变量 | 建议值 | 说明 |
|------|--------|------|
| `PROTOCOL_AUDIT_ENV` | `production` | 触发 SECRET + Basic 密码必填守卫 |
| `PROTOCOL_AUDIT_LLM` | `glm` | 启用智谱；本地冒烟可 `off` |
| `PROTOCOL_AUDIT_VERSION` | `0.1.3.3` | 可选，镜像内已有默认 |
| `PORT` | `8080` | 与 ACA target-port 一致 |
| `PROTOCOL_AUDIT_JOB_TTL_HOURS` | `24` | 未发表方案落盘 TTL |
| `PROTOCOL_AUDIT_RATE_WINDOW_S` / `PROTOCOL_AUDIT_RATE_MAX` | `60` / `20` | 可选 |
| `PROTOCOL_AUDIT_MAX_UPLOAD_BYTES` | `8388608` | 可选（8 MiB） |
| `PROTOCOL_AUDIT_BASIC_USER` | `demo` | 可选；默认 `demo` |

### 密钥（ACA secrets → env；**不要写入镜像/仓库/本交接正文**）

| Secret / env 名 | 用途 |
|-----------------|------|
| `PROTOCOL_AUDIT_SECRET` | Flask `secret_key`（production 必填，非 `dev-skeleton-a`） |
| `PROTOCOL_AUDIT_DEMO_PASSWORD` | Basic auth 密码（production 必填；亦认 `PROTOCOL_AUDIT_BASIC_PASSWORD` / `*_FILE`） |
| `BIGMODEL_CODING_API_KEY` | 智谱 Coding API（`PROTOCOL_AUDIT_LLM=glm` 时） |

参考本地清单（仅变量名，不含值）：`/workspace/secrets/protocol-audit-prod.env`  
注入示例（由 Jassy 执行，值来自本地 secret 文件，勿贴进 git）：

```bash
# 示意：先 set secret，再在 containerapp 里 secretref
az containerapp secret set -g rg-refcheck -n ca-protocol-audit \
  --secrets \
    protocol-audit-secret=*** \
    demopw=*** \
    bigmodel-coding-api-key=***
# 再 update --set-env-vars \
#   PROTOCOL_AUDIT_SECRET=secretref:protocol-audit-secret \
#   PROTOCOL_AUDIT_DEMO_PASSWORD=secretref:demopw \
#   BIGMODEL_CODING_API_KEY=secretref:bigmodel-coding-api-key \
#   PROTOCOL_AUDIT_ENV=production PROTOCOL_AUDIT_LLM=glm PORT=8080
```

## 3. 构建与推送（Jassy）

```bash
cd /workspace/product/protocol-audit
sudo docker build --platform linux/amd64 -f web/Dockerfile -t protocol-audit-beta:0.1.3.3 .
# az acr login / tag / push → refcheck84ed97.azurecr.io/protocol-audit-beta:0.1.3.3
# az containerapp create|update -n ca-protocol-audit ... --target-port 8080 --ingress external
```

Dockerfile 以 **Jassy 仓库内版本为准**；执行者侧不覆盖。

## 4. DNS（Cloudflare 灰云）

子域固定：**`protocol.jassyhong.top`**

1. **TXT** `asuid.protocol` → `az containerapp show ... customDomainVerificationId`
2. **CNAME** `protocol` → Container App 默认 FQDN（**Proxy = DNS only / 灰云**）
3. 生效后：

```bash
az containerapp hostname add  -g rg-refcheck -n ca-protocol-audit --hostname protocol.jassyhong.top
az containerapp hostname bind -g rg-refcheck -n ca-protocol-audit --hostname protocol.jassyhong.top \
  --environment cae-refcheck --validation-method CNAME
```

## 5. 冒烟清单

部署后按序勾选（Basic 用户默认 `demo`，密码为 ACA secret，不写在此）：

- [ ] `GET https://<ACA-FQDN>/health` → **200**，JSON `ok: true`，**无需** Basic（探活）
- [ ] `GET https://<ACA-FQDN>/` **无** Authorization → **401** + `WWW-Authenticate`
- [ ] `GET https://<ACA-FQDN>/` 带 Basic `demo:<password>` → **200**，Beta UI
- [ ] 上传/粘贴短文本 → 解析预览页可打开（LLM=off 亦可）
- [ ] （可选）`PROTOCOL_AUDIT_LLM=glm` 时跑一次短审查；确认超时足够、无客户端暴露 API Key
- [ ] 自定义域：`https://protocol.jassyhong.top/health` → 200；首页仍需 Basic
- [ ] 确认 Cloudflare 该 CNAME 为**灰云**（非橙云）

## 6. 隐私与已知限制（上线须知情）

- 启用 LLM（`glm`）时，**方案正文会外发智谱**；受控邀请用户需知情。
- Job 落在容器本地盘；**scale-to-zero / 换修订会丢**（与 refcheck 同类）。
- 应用内无账号；全站 Basic 即受控 Beta 门禁。
- 科学侧已知限制见 `Beta-V0.1.3.3-验收报告.md` / `Beta-V0.1.3.3-freeze.md`（G1 分级偏软、suggestion 不进 blocker_map、灭菌暂缓等）。**不因一般审查质量优化推迟上线。**

## 7. 相关路径

| 用途 | 路径 |
|------|------|
| 本交接 | `real-trials/Beta-部署交接-JassyKing.md` |
| 冻结说明 | `real-trials/Beta-V0.1.3.3-freeze.md` |
| 验收报告 | `real-trials/Beta-V0.1.3.3-验收报告.md` |
| Web 应用 | `web/app.py` |
| Dockerfile（Jassy） | `web/Dockerfile` |
| 本地 prod env 名清单 | `/workspace/secrets/protocol-audit-prod.env`（勿提交） |

**可交 Jassy 执行 az/ACR/DNS；执行者侧文档与冒烟清单已就绪。**
