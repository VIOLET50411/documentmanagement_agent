"""Fix compare answer and sync from Docker."""
import pathlib

p = pathlib.Path('/app/app/agent/agents/compliance_agent.py')
content = p.read_text(encoding='utf-8')

# Fix _build_compare_answer — remove the broken line
content = content.replace(
    '            f"对比结论：已对《{left_title}》与《{right_title}》进行整理。",\n'
    '            f"**结论**：{conclusion}\\n",\n'
    '            "主题 | 文档A | 文档B | 差异说明",',

    '            f"## 对比分析：《{left_title}》vs《{right_title}》\\n",\n'
    '            "| 主题 | 文档A | 文档B | 差异说明 |",\n'
    '            "| --- | --- | --- | --- |",'
)

content = content.replace(
    '            f"核心要求 | {left_text} | {right_text} | {diff}",',
    '            f"| 核心要求 | {left_text} | {right_text} | {diff} |",'
)

p.write_text(content, encoding='utf-8')
print("OK - compare answer fixed")
