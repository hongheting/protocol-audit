# Beta async upload/audit fix (0.1.3.3-async1)

**日期：** 2026-10-26（Asia/Shanghai）  
**动机：** 线上 `POST /upload` 同步跑 LLM，约 4 分钟后 ACA/网关返回 **504**（`stream timeout`）。UX 提示（ui1）不足以避免超时。

## 改动摘要
- `POST /upload`：校验落盘后立刻写 `parse_status.json`（running），后台线程跑 `build_parse_preview`，HTTP **立即** redirect → `/jobs/<id>/wait?phase=parse`
- `POST /audit/<id>`：写 `audit_request.json` + `audit_status.json`，后台 `run_audit`，立即 redirect → wait?phase=audit
- `GET /jobs/<id>/wait`：等待页；每 2s fetch status
- `GET /jobs/<id>/status?phase=`：JSON（running/done/error）；done 含 redirect
- 状态文件原子写（`.tmp` + `os.replace`）；同 job 用锁避免重复 worker
- `PROTOCOL_AUDIT_ASYNC=0` 可回退同步（默认异步开）
- 版本：`0.1.3.3-async1`（`/health` + base 标题）
- **未改** 科学 Prompt / 规则引擎

## 验证
1. `/health` → version `0.1.3.3-async1`，`async: true`
2. Basic 登录后上传小文件 → **秒级**进等待页（非卡在 `/upload`）
3. 等待页轮询至 preview；确认审查同理进 wait→report
4. 若失败：等待页显示 error + 回首页/预览

## 发版
镜像建议 tag：`protocol-audit-beta:0.1.3.3-async1`；Jassy 滚动 `ca-protocol-audit`。
