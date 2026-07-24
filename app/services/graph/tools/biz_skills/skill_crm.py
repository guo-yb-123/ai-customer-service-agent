from app.services.skill.base import BaseSkill, query_crm_user_info
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class CrmSkill(BaseSkill):
    name = "query_crm"
    desc = """
    [会员信息查询] 查询当前用户的会员等级、历史订单数、积分、注册时间等完整CRM资料。
    触发场景: "我的会员等级"、"我的积分"、"我的个人信息"、"查看我的会员"。
    功能: 根据user_id查询CRM会员数据, 用于展示用户档案和差异化客服语气。
    参数: user_id 系统自动注入。
    """

    def run(self, user_id: str, **kwargs):
        logger.info("查询CRM会员信息: user_id=%s", user_id)
        res_json = query_crm_user_info(user_id=user_id)
        logger.info("CRM接口返回: success=%s", res_json.get("success"))
        return {
            "text": res_json.get("text", "查询失败, 无返回信息"),
            "reply": res_json.get("text", "查询失败, 无返回信息"),
            "user_detail": res_json.get("data", {})
        }
