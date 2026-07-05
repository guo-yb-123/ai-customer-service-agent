import os
import json
from openai import OpenAI
from openai.types.chat import ChatCompletionMessage
import config
from app.utils.json_parser import extract_json_from_llm, safe_loads
from app.utils.logging_config import get_logger
from app.utils.circuit_breaker import retry_on_failure

logger = get_logger(__name__)

DASHSCOPE_SK = os.getenv("DASHSCOPE_API_KEY")

client = OpenAI(
    api_key=DASHSCOPE_SK,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)


def _build_llm_req(prompt: str):
    return {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}]
    }


def _build_agent_req(messages: list, tools: list = None, tool_choice: str = "auto"):
    """
    构建 agent 请求参数
    tool_choice:
      - "required": 强制模型必须调用工具（杜绝礼貌废话）
      - "auto":     模型自主决定是否调用工具（用于生成最终回复）
    """
    req = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "temperature": 0.0,
    }
    if tools:
        req["tools"] = tools
        req["tool_choice"] = tool_choice
    return req


def _execute_tool_calls(msg, skill_instances, user_id, session_id, db, messages):
    """
    执行一轮工具调用，将结果追加到 messages 中。
    返回 (should_continue, msg_to_return)
      - should_continue=True: 工具已执行，继续下一轮 LLM 调用
      - should_continue=False: 遇到异步任务等特殊情况，直接返回该消息
    """
    for tool_call in msg.tool_calls:
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)
        logger.info("触发工具：%s，参数：%s", tool_name, tool_args)

        target_skill = None
        for skill in skill_instances:
            if skill.name == tool_name:
                target_skill = skill
                break
        if not target_skill:
            raise Exception(f"不存在工具 {tool_name}")

        tool_args["user_id"] = user_id
        tool_args["session_id"] = session_id
        tool_args["db"] = db

        try:
            tool_result = target_skill.run(**tool_args)
        except Exception as run_err:
            if "drain_events_until" in str(run_err) or ">=" in str(run_err):
                return False, ChatCompletionMessage(
                    role="assistant",
                    content="正在为您拉取数据，后台服务队列可能正在初始化，请稍等几秒再试~"
                )
            else:
                raise run_err

        # 短路处理：异步任务 或 转人工（不需要 LLM 二次生成回复）
        if tool_result.get("action") in ("async_task_pending", "transfer_human"):
            early_msg = ChatCompletionMessage(
                role="assistant",
                content=tool_result.get("text", "正在为您拉取数据，稍等片刻~")
            )
            early_msg.task_id = tool_result.get("task_id")
            early_msg.ticket_id = tool_result.get("ticket_id")
            early_msg.action = tool_result.get("action")
            return False, early_msg

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_name,
            "content": json.dumps(tool_result, ensure_ascii=False)
        })

    return True, None


def call_qwen_with_tools(messages: list, skill_instances: list, tool_schemas: list, user_id: str, session_id: str, db):
    """
    两阶段工具调用：
    第一阶段：tool_choice="required" → 强制模型必须选工具（杜绝礼貌废话）
    第二阶段：tool_choice="auto"     → 模型基于工具结果生成自然语言回复
    """
    try:
        max_rounds = 3

        # ========== 第一阶段：强制调用工具 ==========
        resp = client.chat.completions.create(
            **_build_agent_req(messages, tool_schemas, tool_choice="required")
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            # "required" 下理论上不会发生，兜底直接返回
            logger.warning("tool_choice='required' 但模型未返回 tool_calls，兜底返回")
            return msg

        should_continue, early_msg = _execute_tool_calls(
            msg, skill_instances, user_id, session_id, db, messages
        )
        if not should_continue:
            return early_msg

        # ========== 后续轮次：auto 模式 ==========
        for round_num in range(1, max_rounds):
            resp = client.chat.completions.create(
                **_build_agent_req(messages, tool_schemas, tool_choice="auto")
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                # 模型认为已完成，返回自然语言回复
                return msg

            should_continue, early_msg = _execute_tool_calls(
                msg, skill_instances, user_id, session_id, db, messages
            )
            if not should_continue:
                return early_msg

        # ========== 达到最大轮次：强制生成最终回复 ==========
        final_resp = client.chat.completions.create(
            **_build_agent_req(messages, tool_schemas, tool_choice="auto")
        )
        return final_resp.choices[0].message

    except Exception as e:
        logger.exception("带工具的LLM调用异常")
        raise ConnectionError(f"Tool LLM调用失败：{str(e)}") from e


@retry_on_failure(max_retries=2, backoff=0.5, exceptions=(Exception,))
def call_qwen_once(prompt: str) -> str:
    try:
        resp = client.chat.completions.create(**_build_llm_req(prompt))
        text = resp.choices[0].message.content.strip()
        if not text:
            raise RuntimeError("LLM返回空文本")
        return text
    except Exception as e:
        logger.exception("单次LLM调用异常")
        raise ConnectionError(f"LLM调用失败: {str(e)}")


def llm_infer(prompt: str):
    try:
        return call_qwen_once(prompt)
    except Exception:
        return ""


def call_qwen_stream(prompt: str):
    try:
        responses = client.chat.completions.create(**_build_llm_req(prompt), stream=True)
        for chunk in responses:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as e:
        logger.exception("LLM流式调用异常")
        raise ConnectionError(f"LLM流式调用失败: {str(e)}") from e


def query_rewrite(question: str) -> list:
    prompt = f"""
    你是企业售后客服检索助手，请把用户问题改写成3条适合售后知识库检索的标准问句。
    要求：
    1. 补全售后业务关键词
    2. 去掉口语化、简略表述
    3. 不改变用户原始诉求
    4. 只返回纯JSON数组，不要任何多余文字、解释
    用户问题：{question}
    输出格式：["问题1","问题2","问题3"]
    """.strip()
    try:
        raw_text = call_qwen_once(prompt)
        json_str = extract_json_from_llm(raw_text)
        return safe_loads(json_str)
    except Exception as e:
        logger.exception(f"Query Rewrite Failed question={question}, err={e}")
        return []
