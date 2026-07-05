from app.services.graph import builder
from app.services.graph.tools.agent_memory import AgentExternalMemory
from app.services.graph.tools.prompts.system_prompt import EXTRACT_PARAM_PROMPT
from app.services.graph.tools.biz_skills import all_skills
from app.utils.llm import call_qwen_with_tools
from typing import Any
from app.utils.logging_config import get_logger
import os

logger = get_logger(__name__)

tool_builder = builder.ToolBuilder(skill_list=all_skills)
tool_definitions = tool_builder.generate_tool_defs()

import json
from sqlalchemy.orm import Session


def escape_brace(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    return text.replace("{", "{{").replace("}", "}}")


def agent_main_run(
        session_id: str,
        user_id: str,
        user_query: str,
        db: Session,
        max_tool_round: int = 3,
        member_level: str | None = None
) -> Any:
    # ========== 0. 开启 LangFuse 追踪 ==========
    from app.utils.langfuse_client import trace_context
    trace = trace_context.start_trace(session_id, user_id, user_query)

    # ========== 1. 初始化会话记忆 ==========
    memory = AgentExternalMemory.load_session_meta(session_id)
    if not memory or not memory.get("extracted_slots", {}).get("user_id"):
        AgentExternalMemory.init_session(session_id=session_id, user_id=user_id)
        memory = AgentExternalMemory.load_session_meta(session_id)
    chat_history = memory.get("chat_history", [])

    # ========== 2. 获取会员等级 ==========
    if member_level is None:
        crm_skill_list = [s for s in all_skills if s.name == "query_crm"]
        if not crm_skill_list:
            return "系统工具异常，无法获取会员信息，请稍后重试"
        crm_skill = crm_skill_list[0]
        crm_result = crm_skill.run(user_id=user_id)
        member_level = crm_result.get("data", {}).get("member_level", "普通用户")

    # ========== 3. 构建消息 ==========
    prompt_context = {
        "member_level": escape_brace(member_level),
        "order_list": [],
        "after_sale_info": "",
        "chat_history": escape_brace("\n".join([f"{item['role']}:{item['content']}" for item in chat_history])),
        "missing_slot": "",
        "user_question": escape_brace(user_query)
    }
    system_prompt = EXTRACT_PARAM_PROMPT.format(**prompt_context)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend([{"role": item["role"], "content": item["content"]} for item in chat_history])
    messages.append({"role": "user", "content": user_query})

    # ========== 4. 调用 LLM（内部已处理多轮工具调用 + 最终自然语言生成）==========
    final_msg_obj = call_qwen_with_tools(
        messages=messages,
        skill_instances=all_skills,
        tool_schemas=tool_definitions,
        user_id=user_id,
        session_id=session_id,
        db=db
    )

    final_text = final_msg_obj.content or "当前查询次数已达上限，请简化问题重试"

    # ========== 5. Reflection 自检（防幻觉/完整性校验）==========
    from app.services.graph.tools.agent_reflection import reflection_check

    if os.getenv("ENABLE_REFLECTION", "1") == "1":
        check = reflection_check(
            user_question=user_query,
            ai_reply=final_text,
            tool_name="",
            tool_result="",
        )
        if not check["passed"]:
            logger.warning(
                "Reflection 不通过 (score=%s): %s — 原回复: %s",
                check["overall_score"], check["fix_suggestion"], final_text[:100],
            )
            if check["has_hallucination"]:
                final_text = "非常抱歉，我刚才的回复可能不够准确。让我重新为您查询一下——" + final_text[:200]
            elif check["has_missing_info"]:
                final_text = final_text + "\n\n如果以上信息没有完全解答您的疑问，请告诉我您还需要了解什么~"
            # 否则保留原回复但记录问题
        else:
            logger.info("Reflection 通过 (score=%s)", check["overall_score"])

    # ========== 7. 存入外部记忆 ==========
    AgentExternalMemory.append_chat(session_id=session_id, role="user", content=user_query)
    AgentExternalMemory.append_chat(session_id=session_id, role="assistant", content=final_text)

    # ========== 8. 将工具返回的 ticket_id 挂载到消息对象上 ==========
    # （task_id/action 已在 _execute_tool_calls 中挂载到 early_msg 上）

    # ========== 9. 结束 LangFuse 追踪 ==========
    trace_context.end_trace(session_id, final_text)

    return final_msg_obj
