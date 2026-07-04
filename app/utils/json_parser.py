import re
import json

def extract_json_from_llm(text: str) -> str:
    """
    从 LLM 输出中智能提取 JSON 字符串。
    解决 LLM 常见的 Markdown 包裹、思考链、多余字符等问题。
    """
    if not text:
        raise ValueError("LLM 返回为空")

    # 1. 去除 Qwen/DeepSeek 常见的 <think>...</think> 思考链
    # 这一步非常关键，否则 JSON 解析必炸
    text = re.sub(r'<think>[\s\S]*?</think>', '', text)

    # 2. 尝试匹配 ```json ... ``` 或 ``` ... ```
    # re.DOTALL 让 . 能匹配换行符
    markdown_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if markdown_match:
        return markdown_match.group(1).strip()

    # 3. 如果没有代码块，尝试直接寻找第一个 { 和最后一个 }
    # 适用于纯文本输出
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end+1].strip()

    # 4. 实在找不到，返回原文本（让后续的 json.loads 抛出异常以便排查）
    return text.strip()

def safe_loads(json_str: str) -> dict:
    """
    安全的 JSON 解析，附带更清晰的错误信息
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}. 原始内容: {json_str[:200]}...")