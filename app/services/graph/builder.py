from typing import List,Dict
from app.services.skill.base import BaseSkill
import inspect
import traceback
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


class ToolBuilder:
    # 修正入参：接收已经实例化好的skill对象，不是类
    def __init__(self,skill_list:List[BaseSkill]):
        self.skill_list = skill_list

    def generate_tool_defs(self) -> List[Dict]:
        tools:List[Dict] = []
        for skill in self.skill_list:
            try:
                # 不再 skill_cls() 重复实例化，直接使用传入的实例
                sig = inspect.signature(skill.run)
                params = sig.parameters
                properties = {}
                required = []

                # 自动解析run方法参数，过滤公共注入参数
                for name, param in params.items():
                    if name in ("db", "user_id", "session_id", "kwargs"):
                        continue
                    # 基础类型映射
                    type_map = {
                        str: "string",
                        int: "integer",
                        float: "number",
                        bool: "boolean"
                    }
                    param_type = type_map.get(param.annotation, "string")
                    properties[name] = {
                        "type": param_type,
                        "description": f"{name}参数"
                    }
                    # 无默认值则为必填
                    if param.default is param.empty:
                        required.append(name)

                tool_item = {
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.desc,
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required
                        }
                    }
                }
                tools.append(tool_item)
            except Exception as e:
                # 打印异常堆栈，定位哪个skill解析失败
                logger.info(f"解析工具 {skill.name} 失败，异常：{str(e)}")
                logger.info(traceback.format_exc())
                # 单个工具失败不中断整体循环，跳过当前skill继续下一个
                continue
        return tools
