import os
import json
import time
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
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# ===== 模型自动降级切换 =====
# 当主模型 token 耗尽或不可用时，按优先级依次尝试备用模型
FALLBACK_MODELS = [
    "deepseek-v3",       # 首选
    "deepseek-r1",       # 备用1：同系列 DeepSeek
    "qwen-max",          # 备用2：通义千问旗舰
    "qwen-plus",         # 备用3：通义千问增强
    "qwen3-235b-a22b",   # 备用4：通义千问3
]

# 需要触发模型切换的错误关键词
_MODEL_SWITCH_KEYWORDS = [
    "quota has been exhausted",
    "free quota",
    "insufficient_quota",
    "rate limit",
    "rate_limit",
    "too many requests",
    "service unavailable",
    "model is overloaded",
    "model_not_found",
    "access_denied",
    "model is not available",
    "server is busy",
    "internal server error",
    "timed out",
    "connection error",
]

_current_model_index = 0  # 当前使用的模型在 FALLBACK_MODELS 中的索引


def _get_current_model() -> str:
    """获取当前应该使用的模型名称"""
    global _current_model_index
    if _current_model_index < len(FALLBACK_MODELS):
        return FALLBACK_MODELS[_current_model_index]
    # 所有模型都不行，回到配置中的默认模型
    return config.LLM_MODEL


def _should_switch_model(error: Exception) -> bool:
    """判断是否应该切换到备用模型"""
    error_str = str(error).lower()
    for keyword in _MODEL_SWITCH_KEYWORDS:
        if keyword.lower() in error_str:
            return True
    # HTTP 429 (rate limit) 或 5xx 也应该切换
    if hasattr(error, 'status_code'):
        status = getattr(error, 'status_code', 0)
        if status in (429, 500, 502, 503, 504):
            return True
    return False


def _switch_to_next_model() -> str | None:
    """切换到下一个可用模型，返回模型名；若全部耗尽则返回 None"""
    global _current_model_index
    _current_model_index += 1
    if _current_model_index < len(FALLBACK_MODELS):
        new_model = FALLBACK_MODELS[_current_model_index]
        logger.warning("🔄 模型已切换: → %s (第 %d/%d 个备用)",
                       new_model, _current_model_index, len(FALLBACK_MODELS) - 1)
        return new_model
    logger.error("❌ 所有备用模型均已尝试，无可用的模型")
    return None


def _reset_model_index():
    """重置模型索引（每次新对话开始时调用）"""
    global _current_model_index
    _current_model_index = 0


def _with_model_fallback(llm_call_fn):
    """
    装饰器：为 LLM 调用函数添加模型自动降级切换能力。

    当调用失败且错误匹配切换条件时，自动切换到下一个备用模型重试。
    """
    def wrapper(*args, **kwargs):
        global _current_model_index
        last_error = None

        # 最多尝试所有备用模型
        for attempt in range(len(FALLBACK_MODELS) - _current_model_index):
            current_model = _get_current_model()
            try:
                # 将当前模型注入到请求参数中
                if 'model' not in kwargs:
                    kwargs['model'] = current_model
                return llm_call_fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                if not _should_switch_model(e):
                    # 非模型切换类的错误，直接抛出
                    raise

                logger.warning("模型 %s 调用失败: %s", current_model, str(e)[:150])
                new_model = _switch_to_next_model()
                if new_model is None:
                    break
                # 更新 kwargs 中的 model
                kwargs['model'] = new_model
                time.sleep(0.5)  # 短暂等待避免速率限制叠加

        # 所有模型都失败了
        raise ConnectionError(
            f"所有备用模型调用均失败，最后错误: {str(last_error)[:200] if last_error else '未知'}"
        ) from last_error

    return wrapper


def _build_llm_req(prompt: str, model: str = None):
    return {
        "model": model or _get_current_model(),
        "messages": [{"role": "user", "content": prompt}]
    }


def _build_agent_req(messages: list, tools: list = None, tool_choice: str = "auto", model: str = None):
    """
    构建 agent 请求参数
    tool_choice:
      - "required": 强制模型必须调用工具（杜绝礼貌废话）
      - "auto":     模型自主决定是否调用工具（用于生成最终回复）
    """
    req = {
        "model": model or _get_current_model(),
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
    两阶段工具调用（带模型自动降级）：
    第一阶段：tool_choice="required" → 强制模型必须选工具（杜绝礼貌废话）
    第二阶段：tool_choice="auto"     → 模型基于工具结果生成自然语言回复

    当主模型 token 耗尽时自动切换到备用模型。
    """
    _reset_model_index()  # 每次新 Agent 调用从首选模型开始

    last_error = None
    for attempt in range(len(FALLBACK_MODELS)):
        current_model = _get_current_model()
        try:
            max_rounds = 3

            # ========== 第一阶段：强制调用工具 ==========
            resp = client.chat.completions.create(
                **_build_agent_req(messages, tool_schemas, tool_choice="required", model=current_model)
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
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
                    **_build_agent_req(messages, tool_schemas, tool_choice="auto", model=current_model)
                )
                msg = resp.choices[0].message

                if not msg.tool_calls:
                    return msg

                should_continue, early_msg = _execute_tool_calls(
                    msg, skill_instances, user_id, session_id, db, messages
                )
                if not should_continue:
                    return early_msg

            # ========== 达到最大轮次：强制生成最终回复 ==========
            final_resp = client.chat.completions.create(
                **_build_agent_req(messages, tool_schemas, tool_choice="auto", model=current_model)
            )
            return final_resp.choices[0].message

        except Exception as e:
            last_error = e
            if not _should_switch_model(e):
                logger.exception("LLM调用异常（不可切换）: %s", e)
                raise ConnectionError(f"LLM调用失败：{str(e)}") from e

            logger.warning("模型 %s 调用失败，尝试切换: %s", current_model, str(e)[:150])
            new_model = _switch_to_next_model()
            if new_model is None:
                break
            time.sleep(0.5)

    raise ConnectionError(
        f"所有模型均调用失败，最后错误: {str(last_error)[:200] if last_error else '未知'}"
    )


@retry_on_failure(max_retries=2, backoff=0.5, exceptions=(Exception,))
def call_qwen_once(prompt: str) -> str:
    """
    单次 LLM 调用（带模型自动降级）。

    当主模型 token 耗尽时自动切换到备用模型。
    在当前会话中记住可用模型，避免重复尝试已失败的模型。
    """
    last_error = None
    for attempt in range(len(FALLBACK_MODELS)):
        idx = _current_model_index + attempt
        if idx >= len(FALLBACK_MODELS):
            break
        current_model = FALLBACK_MODELS[idx]
        try:
            resp = client.chat.completions.create(**_build_llm_req(prompt, model=current_model))
            text = resp.choices[0].message.content.strip()
            if not text:
                raise RuntimeError("LLM返回空文本")
            return text
        except Exception as e:
            last_error = e
            if not _should_switch_model(e):
                if "LLM返回空文本" in str(e):
                    logger.warning("LLM返回空文本，切换模型重试")
                else:
                    logger.exception("单次LLM调用异常（不可切换）: %s", e)
                    raise ConnectionError(f"LLM调用失败: {str(e)}") from e

            logger.warning("模型 %s 调用失败，尝试切换: %s", current_model, str(e)[:150])
            new_model = _switch_to_next_model()
            if new_model is None:
                break
            time.sleep(0.5)

    raise ConnectionError(
        f"所有模型均调用失败，最后错误: {str(last_error)[:200] if last_error else '未知'}"
    )


def llm_infer(prompt: str):
    try:
        return call_qwen_once(prompt)
    except Exception:
        return ""


def call_qwen_stream(prompt: str):
    """
    LLM 流式调用（带模型自动降级）。
    """
    last_error = None
    for attempt in range(len(FALLBACK_MODELS)):
        current_model = _get_current_model()
        try:
            responses = client.chat.completions.create(
                **_build_llm_req(prompt, model=current_model), stream=True
            )
            for chunk in responses:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            # 成功流式输出后重置模型索引
            _reset_model_index()
            return
        except Exception as e:
            last_error = e
            if not _should_switch_model(e):
                logger.exception("LLM流式调用异常（不可切换）: %s", e)
                raise ConnectionError(f"LLM流式调用失败: {str(e)}") from e

            logger.warning("模型 %s 流式调用失败，尝试切换: %s", current_model, str(e)[:150])
            new_model = _switch_to_next_model()
            if new_model is None:
                break
            time.sleep(0.5)

    raise ConnectionError(
        f"所有模型均调用失败（流式），最后错误: {str(last_error)[:200] if last_error else '未知'}"
    )


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
