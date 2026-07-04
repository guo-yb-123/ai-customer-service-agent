"""
意图 → 必填槽位映射 + 敏感操作定义

每个意图对应一组必填参数，用于槽位填充校验。
敏感操作需要人工审批后才能执行。
"""
from typing import Dict, List, Set

# ===== 意图 → 必填槽位映射 =====
SLOT_SCHEMA: Dict[str, List[str]] = {
    # 需要额外参数的意图
    "query_order": ["order_no"],
    "query_logistics_by_goods": ["goods_name"],
    "query_single_logistics": ["tracking_no"],
    "initiate_return_by_goods": ["goods_name"],
    "submit_ticket": ["order_no", "problem_desc"],
    "query_single_aftersale": ["aftersale_no"],
    "query_single_goods": ["goods_id"],
    # 以下意图无需额外参数（user_id 由系统自动注入）
    "query_all_order": [],
    "query_all_logistics": [],
    "query_crm": [],
    "query_all_aftersale": [],
    "query_knowledge_base": [],
    "query_all_goods": [],
    "transfer_human": [],
    "fallback_query": [],
}

# ===== 敏感操作：需要人工审批 =====
SENSITIVE_SKILLS: Set[str] = {
    "initiate_return_by_goods",
    "submit_ticket",
}

# ===== 意图→技能名映射（intent 名 → skill.name）=====
INTENT_TO_SKILL: Dict[str, str] = {
    "query_order": "query_order",
    "query_all_order": "query_all_order",
    "query_logistics_by_goods": "query_logistics_by_goods",
    "query_single_logistics": "query_single_logistics",
    "query_all_logistics": "query_all_logistics",
    "initiate_return_by_goods": "initiate_return_by_goods",
    "submit_ticket": "submit_ticket",
    "query_single_aftersale": "query_single_aftersale",
    "query_all_aftersale": "query_all_aftersale",
    "query_crm": "query_crm",
    "query_single_goods": "query_single_goods",
    "query_all_goods": "query_all_goods",
    "query_knowledge_base": "query_knowledge_base",
    "transfer_human": "transfer_human",
    "fallback_query": "fallback_query",
}


def get_required_slots(intent: str) -> List[str]:
    """获取指定意图的必填槽位列表"""
    return SLOT_SCHEMA.get(intent, [])


def is_sensitive(skill_name: str) -> bool:
    """判断技能是否需要人工审批"""
    return skill_name in SENSITIVE_SKILLS


def get_skill_name(intent: str) -> str:
    """将意图名映射到实际的 skill.name"""
    return INTENT_TO_SKILL.get(intent, intent)
