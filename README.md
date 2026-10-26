# ProtocolAudit / 实验方案审查助手

**作者 Author：** 洪鹤庭 Hong Heting（Jassyhong）  
**在线 Demo：** [https://protocol.jassyhong.top](https://protocol.jassyhong.top)  
**许可证 License：** MIT（见 `LICENSE`）  
**版本：** V0.1.3.x（科学 Prompt 冻结于 V0.1.2）

上传 Word / PDF / Markdown 实验方案 → 解析预览 →（可选 LLM）结构化设计 → 结构规则硬闸 + 科学审查 → Claim–Evidence 映射 → 可改建议报告。

> **English:** Protocol review focused on whether the finished experiment can actually answer the scientific claim—not whether the write-up “looks complete.”

---

## 一句话定位

按此方案做完实验，**数据能否回答科学问题**（Claim–Evidence Mapping）；优先揪出影响结论成立的关键缺陷，而不是堆 finding 条数。

## 功能要点

- 上传 `.docx` / `.pdf` / `.md` → ParsePreview（可编辑）→ 用户确认
- 结构规则硬闸：假设 / 对照 / 终点 / 统计 / 批次与外推等
- 可选 LLM 科学审查（智谱 Coding GLM / Gemini）；默认可纯规则离线跑
- Claim–Evidence 按假设分行；Optimizer 方案 A 给出可改建议
- Web Beta（Flask + gunicorn）与 CLI；fixtures + real-trials 回归材料

## 在线 Demo

打开 [protocol.jassyhong.top](https://protocol.jassyhong.top)。受控 Beta 可能启用 Basic 认证（用户名常见为 `demo`，密码由部署方注入，**不在本仓库**）。

## 本地运行

```bash
git clone https://github.com/hongheting/protocol-audit.git
cd protocol-audit

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Web 另需：pip install -r web/requirements.txt

# 纯规则 CLI（推荐默认测试路径）
PROTOCOL_AUDIT_LLM=off python scripts/run_audit_cli.py fixtures/flawed_protocol.docx --llm off

# 测试（跳过真实 LLM）
PROTOCOL_AUDIT_LLM=off python -m pytest tests/ -m "not llm" -q
```

### 可选：启用 LLM

设置环境变量（**不要把真实密钥写入仓库或聊天**）：

```bash
export PROTOCOL_AUDIT_LLM=glm          # 或 gemini / off / auto
export BIGMODEL_CODING_API_KEY=...     # 智谱 Coding
# 或
export GEMINI_API_KEY=...              # Google Gemini
```

然后：

```bash
python scripts/run_audit_cli.py fixtures/flawed_protocol.docx --llm glm -o /tmp/report.json
```

### Docker / Compose

```bash
# 从仓库根目录
docker compose -f web/docker-compose.yml up --build
# 默认 http://127.0.0.1:8080 ；compose 内为本地冒烟密钥，生产请替换
```

生产镜像构建见 `web/Dockerfile`（gunicorn，读 `PORT`）。

## 环境变量（仅变量名）

| 变量 | 说明 |
|------|------|
| `PROTOCOL_AUDIT_LLM` | `off` / `glm` / `gemini` / `auto` |
| `BIGMODEL_CODING_API_KEY` / `ZHIPU_API_KEY` | 智谱 Coding |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini |
| `PROTOCOL_AUDIT_ENV` | `production` / `prod` / `beta` 时启用加固守卫 |
| `PROTOCOL_AUDIT_SECRET` | Flask `secret_key`（生产必填且勿用默认值） |
| `PROTOCOL_AUDIT_DEMO_USER` / `PROTOCOL_AUDIT_BASIC_USER` | Basic 用户名（默认 `demo`） |
| `PROTOCOL_AUDIT_DEMO_PASSWORD` / `PROTOCOL_AUDIT_BASIC_PASSWORD` | Basic 密码（或 `*_FILE`） |
| `PROTOCOL_AUDIT_MAX_UPLOAD_BYTES` | 上传上限 |
| `PROTOCOL_AUDIT_RATE_WINDOW_S` / `PROTOCOL_AUDIT_RATE_MAX` | 限流 |
| `PROTOCOL_AUDIT_JOB_TTL_HOURS` | 任务保留时长 |
| `PROTOCOL_AUDIT_LLM_LOG_DIR` | LLM 日志目录（默认脱敏写入 `logs/`） |
| `PORT` | Web 端口 |

可选：将 dotenv 放到本机私有路径并由进程注入；**切勿**提交 `.env` 或密钥文件。

## 目录（摘要）

| 路径 | 说明 |
|------|------|
| `protocol_audit/` | 解析、规则、LLM、流水线 |
| `web/` | Flask UI + Dockerfile / compose |
| `fixtures/` / `examples/` | 有缺陷 / 健全示例方案 |
| `scripts/run_audit_cli.py` | CLI |
| `tests/` | pytest |
| `real-trials/` | 回归与 Beta 验收文档（不含超大私有 blob） |
| `*.schema.json` | 请求 / 报告 JSON Schema |

## 免责声明

- **非替代伦理审查 / IRB / 生物安全审查**：本工具不做合规放行，也不替代单位或监管审批。
- **非论文录用或基金评审意见**：输出是方法学与证据链方面的辅助提示，最终科学判断仍归研究者与审稿人。
- LLM 开启时，内容会发往所选云端模型供应商；请勿上传含未公开隐私、患者标识或受控数据的方案，除非你已获授权并接受供应商条款。
- Demo / Beta 结果可能不完整，请人工复核后再改方案。

## License

MIT © 2026 Hong Heting（洪鹤庭, Jassyhong）
