# Beta V0.1.3.3 阻断级热修说明

时间（Asia/Shanghai）：2026-10-26

## 科学性：无变更

- 未改 design_extract / scientific_review Prompt 文本
- 未加科学规则；未调参；灭菌追问仍暂缓

## 可靠性（阻断）

1. `protocol_audit/llm_review.py`：扩容重试不可用时，回退首轮可用 findings，避免丢审查成果
2. `protocol_audit/llm_client.py`：`extract_json_object` 优先 \`\`\`json 并跳过非 json preamble fence
3. 单测：`test_review_keeps_first_when_expand_worse`

## Web（阻断）

`web/app.py`：扩展名白名单、限流、生产 secret、无 traceback flash、job TTL、更长 job id；`report.html` 展示 origin/隐私摘要

## 验证

- Trial3 热修前：`trial3-pre-fix/`（llm_review=0，诚实 failed）
- Trial3 热修后：`trial3/`（llm_review=6，完整审查）
- pytest：38 passed
