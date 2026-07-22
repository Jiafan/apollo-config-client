"""应用装配：从环境变量构建全局唯一的 ConfigManager 单例（dogfooding 示例）。

真实项目里这份"应用装配"代码**不进库**——库只提供工厂函数
``create_config_manager_from_env``。这里仅为让 flask / fastapi 示例能直接 ``import`` 使用。
"""
from __future__ import annotations

import atexit

from apollo_config import create_config_manager_from_env
from apollo_config.contrib import init_oracle_thick_mode

# 在任何 Oracle 连接创建前统一初始化驱动（11g 必须 thick 模式）；
# 集中在此处，普通脚本 import get_config_manager 也会自动生效。
init_oracle_thick_mode()

_manager = create_config_manager_from_env()


def get_config_manager():
    return _manager


atexit.register(_manager.stop)
