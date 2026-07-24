from app.services.graph.tools.biz_skills.skill_crm import CrmSkill
from app.services.graph.tools.biz_skills.skill_goods import AllGoodsSkill, SingleGoodsSkill
from app.services.graph.tools.biz_skills.skill_knowledge import KnowledgeBaseSkill
from app.services.graph.tools.biz_skills.skill_order import OrderSkill, AllOrderSkill
from app.services.graph.tools.biz_skills.skill_logistics import AllLogisticsSkill, SingleLogisticsSkill, LogisticsByGoodsSkill
from app.services.graph.tools.biz_skills.skill_system import TransferHumanSkill, FallbackSkill
from app.services.graph.tools.biz_skills.skill_ticket import TicketSkill, AllAfterSaleSkill, SingleAfterSaleSkill, ReturnByGoodsSkill

all_skills = [
    CrmSkill(),
    OrderSkill(),
    TicketSkill(),
    AllOrderSkill(),
    AllAfterSaleSkill(),
    ReturnByGoodsSkill(),
    SingleAfterSaleSkill(),
    AllLogisticsSkill(),
    SingleLogisticsSkill(),
    LogisticsByGoodsSkill(),
    AllGoodsSkill(),
    SingleGoodsSkill(),
    KnowledgeBaseSkill(),
    TransferHumanSkill(),
    FallbackSkill()

]