"""AI客服管理系统 - FastAPI 主服务"""

import os
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(__file__))

from config import ensure_config_file
from knowledge import router as knowledge_router
from chat import router as chat_router
from config import load_config, save_config
from stats import router as stats_router

# ---- 初始化目录 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "knowledge_base", "chroma_db"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "conversations"), exist_ok=True)

# 初始化默认配置
ensure_config_file()

# ---- FastAPI 应用 ----
app = FastAPI(
    title="AI客服管理系统",
    description="本地部署的AI客服管理系统后端服务",
    version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 挂载路由 ----
app.include_router(knowledge_router)
app.include_router(chat_router)
app.include_router(stats_router)


# ---- 配置 API ----

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import get_masked_config

config_router = APIRouter(prefix="/api/config", tags=["配置"])


class ConfigUpdate(BaseModel):
    qwen_api_key: str = None
    system_prompt: str = None
    welcome_message: str = None
    company_name: str = None


@config_router.get("")
async def get_config():
    """获取配置（api_key脱敏显示）"""
    return get_masked_config()


@config_router.post("")
async def update_config(update: ConfigUpdate):
    """更新配置"""
    config = load_config()
    if update.qwen_api_key is not None:
        # 如果传的是脱敏值（包含*），则不更新
        if "*" not in update.qwen_api_key:
            config["qwen_api_key"] = update.qwen_api_key
    if update.system_prompt is not None:
        config["system_prompt"] = update.system_prompt
    if update.welcome_message is not None:
        config["welcome_message"] = update.welcome_message
    if update.company_name is not None:
        config["company_name"] = update.company_name
    save_config(config)
    return {"message": "配置更新成功"}


app.include_router(config_router)


# ---- 静态文件（前端） ----

@app.get("/")
async def serve_frontend():
    """提供前端管控面板"""
    admin_path = os.path.join(FRONTEND_DIR, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path)
    return {"message": "AI客服管理系统后端运行中", "version": "1.0.0"}


@app.get("/widget/chat-widget.js")
async def serve_widget():
    """提供客服Widget JS"""
    widget_path = os.path.join(FRONTEND_DIR, "widget", "chat-widget.js")
    if os.path.exists(widget_path):
        from fastapi.responses import Response
        with open(widget_path, "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    return Response(content="// Widget not found", status_code=404, media_type="application/javascript")


# 尝试挂载前端静态文件
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ---- 启动入口 ----

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8600,
        reload=True,
        log_level="info"
    )
