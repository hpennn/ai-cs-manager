"""配置管理模块"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "config.json")

DEFAULT_CONFIG = {
    "zhipu_api_key": "4854154d31a042e2a8d8eee754097757.WDct0BiBIxyzswdH",
    "zhipu_base_url": "https://open.bigmodel.cn/api/paas/v4",
    "zhipu_model": "glm-4-flash",
    "system_prompt": "你是一个专业的电商客服助手，根据知识库中的信息回答用户问题。如果知识库中没有相关信息，请礼貌地告知用户并建议联系人工客服。回答要简洁、准确、友好。",
    "welcome_message": "您好！我是AI客服助手，请问有什么可以帮您？",
    "company_name": "我的公司",
    "admin_username": "admin",
    "admin_password": "admin123"
}


def ensure_config_file():
    """确保配置文件存在"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)


def load_config() -> dict:
    """加载配置"""
    ensure_config_file()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        # 补齐缺失的默认字段
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
        return config
    except (json.JSONDecodeError, IOError):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """保存配置"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_config_value(key: str, default=None):
    """获取单个配置项"""
    config = load_config()
    return config.get(key, default)


def set_config_value(key: str, value):
    """设置单个配置项"""
    config = load_config()
    config[key] = value
    save_config(config)


def get_masked_config() -> dict:
    """获取脱敏后的配置（api_key只显示前后各2位）"""
    config = load_config()
    api_key = config.get("zhipu_api_key", "")
    if api_key and len(api_key) > 4:
        config["zhipu_api_key"] = api_key[:2] + "*" * (len(api_key) - 4) + api_key[-2:]
    elif api_key:
        config["zhipu_api_key"] = "****"
    # 不返回管理员密码
    config.pop("admin_password", None)
    return config
