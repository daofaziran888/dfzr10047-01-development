"""业务路由汇总：补采领办专用路由先于通用资源路由注册，避免固定路径被动态路径抢占。"""
from __future__ import annotations

from app.routers import recollect, resource

ROUTERS = [recollect, resource]
