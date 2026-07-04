"""
提示词加载器 — 从 YAML 文件加载，修改后重启即生效，无需改代码
"""
import os
from pathlib import Path
from functools import lru_cache

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# 提示词文件路径
PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", Path(__file__).parent.parent.parent / "config" / "prompts"))


def _load_yaml(path: Path) -> dict:
    """加载 YAML 文件，支持 PyYAML 和简单的字典解析"""
    if _HAS_YAML:
        with open(path, "r", encoding="utf-8") as f:
            return _yaml.safe_load(f)
    return _parse_simple_yaml(path)


def _parse_simple_yaml(path: Path) -> dict:
    """简单的 YAML 解析器（不依赖 PyYAML）"""
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    current_key = None
    current_template = []
    in_template = False

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line.startswith(" ") and not line.startswith("\t"):
            if current_key and current_template:
                data[current_key] = {"template": "\n".join(current_template).strip()}
            current_key = stripped.rstrip(":")
            current_template = []
            in_template = False
        elif stripped.startswith("template:"):
            in_template = True
            # 取 template: 后面的内容
            val = stripped[len("template:"):].strip()
            if val.startswith("|"):
                continue  # 多行模板
            current_template.append(val)
        elif in_template:
            current_template.append(line.rstrip())

    if current_key and current_template:
        data[current_key] = {"template": "\n".join(current_template).strip()}

    return data


@lru_cache(maxsize=32)
def load_prompt(prompt_name: str) -> str:
    """
    加载指定名称的提示词模板

    使用方式:
        prompt = load_prompt("extract_param")
        formatted = prompt.format(member_level="金牌", ...)
    """
    file_path = PROMPTS_DIR / "system.yaml"
    if not file_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {file_path}")

    data = _load_yaml(file_path)
    if prompt_name not in data:
        raise KeyError(f"提示词 '{prompt_name}' 未找到，可用: {list(data.keys())}")

    return data[prompt_name]["template"]


def reload_prompts():
    """清空缓存，强制重新加载提示词（热更新）"""
    load_prompt.cache_clear()
