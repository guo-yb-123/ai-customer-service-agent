"""
节点：执行技能

根据识别出的意图，调用对应的 BaseSkill.run() 执行业务操作。

敏感操作（退货、创建工单）在未获审批时只准备参数，不实际执行。
审批通过后再次进入本节点时才真正执行。
"""
import json
import inspect
from app.services.graph.state import GraphState
from app.services.graph.slot_schemas import get_skill_name, is_sensitive
from app.services.graph.tools.biz_skills import all_skills
from app.db.database import SessionLocal
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def execute_skill_node(state: GraphState) -> dict:
    """
    根据 intent 准备并执行技能。

    敏感操作保护：
    - 如果是敏感操作且未获审批 → 只设置 tool_name/tool_args，不执行
    - 审批通过后再次进入 → 真正执行
    """
    intent = state.intent or "fallback_query"
    skill_name = state.tool_name or get_skill_name(intent)
    collected = state.collected_slots or {}
    user_id = state.user_id or ""
    session_id = state.session_id or ""

    # 如果是重试（已有工具结果），重新执行以获取最新数据，替换旧结果
    existing_results = list(state.tool_results or [])

    # ===== 敏感操作保护：未审批时不执行 =====
    if is_sensitive(skill_name) and state.approval_status != "approved":
        return _prepare_skill(state, intent, skill_name, collected, user_id, session_id)

    # ===== 实际执行技能 =====
    # 重试时替换而非追加：tool_results 只保留最新一次执行结果
    return _run_skill(state, intent, skill_name, collected, user_id, session_id, existing_results)


def _prepare_skill(
    state: GraphState, intent: str, skill_name: str,
    collected: dict, user_id: str, session_id: str,
) -> dict:
    """准备技能参数但不执行（用于敏感操作的审批前阶段）"""
    # 查找 skill 实例以获取参数签名
    target_skill = None
    for skill in all_skills:
        if skill.name == skill_name:
            target_skill = skill
            break

    call_args = dict(collected)
    call_args["user_id"] = user_id
    call_args["session_id"] = session_id

    if target_skill:
        sig_params = inspect.signature(target_skill.run).parameters
        filtered_args = {k: v for k, v in call_args.items()
                         if k in sig_params or "kwargs" in sig_params}
    else:
        filtered_args = call_args

    logger.info("准备技能（待审批）: %s, 参数: %s",
                 skill_name, {k: v for k, v in filtered_args.items() if k != "db"})

    return {
        "tool_name": skill_name,
        "tool_args": filtered_args,
        "stage": "EXECUTE",
        "error_msg": "",
    }


def _run_skill(
    state: GraphState, intent: str, skill_name: str,
    collected: dict, user_id: str, session_id: str, tool_results: list,
) -> dict:
    """实际执行技能并收集结果"""
    # 查找匹配的 skill 实例
    target_skill = None
    for skill in all_skills:
        if skill.name == skill_name:
            target_skill = skill
            break

    if not target_skill:
        logger.warning("未找到技能: %s，使用 fallback_query", skill_name)
        for skill in all_skills:
            if skill.name == "fallback_query":
                target_skill = skill
                break

    # 构建调用参数：槽位值 + 系统注入参数
    call_args = dict(collected)
    call_args["user_id"] = user_id
    call_args["session_id"] = session_id

    # 创建 DB session 并注入（skill 需要 db 参数时）
    sig_params = inspect.signature(target_skill.run).parameters
    db = None
    if "db" in sig_params:
        db = SessionLocal()
        call_args["db"] = db

    # 过滤掉 skill.run 不接受的参数
    filtered_args = {k: v for k, v in call_args.items()
                     if k in sig_params or "kwargs" in sig_params}

    try:
        logger.info("执行技能: %s, 参数: %s",
                     skill_name, {k: v for k, v in filtered_args.items() if k != "db"})
        result = target_skill.run(**filtered_args)
    except Exception as e:
        logger.exception("技能执行异常: %s, error: %s", skill_name, e)
        if db:
            db.close()
        return {
            "tool_name": skill_name,
            "tool_args": filtered_args,
            "tool_results": tool_results,
            "error_msg": f"技能执行失败: {str(e)}",
            "stage": "EXECUTE",
        }

    # 关闭 DB session
    if db:
        db.close()

    # 处理结果
    if isinstance(result, dict):
        tool_results.append({
            "skill": skill_name,
            "result": result,
            "success": result.get("success", True),
        })

        # 检查是否为异步任务或转人工
        action = result.get("action", "")
        if action in ("async_task_pending", "transfer_human"):
            return {
                "tool_name": skill_name,
                "tool_args": filtered_args,
                "tool_results": tool_results,
                "reply_text": result.get("text", result.get("reply", "")),
                "action": action,
                "task_id": result.get("task_id"),
                "ticket_id": result.get("ticket_id"),
                "stage": "FINISH",
                "error_msg": "",
            }
    else:
        tool_results.append({
            "skill": skill_name,
            "result": {"text": str(result)},
            "success": True,
        })

    return {
        "tool_name": skill_name,
        "tool_args": filtered_args,
        "tool_results": tool_results,
        "stage": "EXECUTE",
        "error_msg": "",
    }
