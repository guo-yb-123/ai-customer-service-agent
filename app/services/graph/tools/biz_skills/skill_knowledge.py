from app.services.skill.base import BaseSkill
from app.utils.embedding import build_rag_prompt
from app.utils.logging_config import get_logger

logger = get_logger(__name__)



class KnowledgeBaseSkill(BaseSkill):
    name = "query_knowledge_base"
    desc = """
    [知识库问答 -- 强制触发] 用户询问退换货政策、发货时间、保修条款、退款流程、使用说明、公司信息等通用/规则类问题时, 必须调用本工具。
    功能: 基于企业知识库(RAG)检索, 准确回答标准流程和业务规则。
    参数说明:
        user_query: 用户原始提问文本。
    约束: 只回答知识库中有的内容, 不知道的诚实说"暂未找到相关说明", 绝对不能编造。
    """

    def run(self, user_query: str, **kwargs):
        logger.info(f"=====进入知识库检索 run, 问题={user_query} =====")
        prompt, docs = build_rag_prompt(user_query)
        return {
            "text": prompt,
            "reply": prompt,
            "retrieved_docs": docs
        }
