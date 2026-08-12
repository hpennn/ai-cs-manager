"""AI客服管理系统 - FastAPI 主服务"""

import os
import sys
import secrets
from datetime import datetime, timedelta
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(__file__))

from config import ensure_config_file, load_config, save_config, get_masked_config
from knowledge import router as knowledge_router
from chat import router as chat_router
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
    version="1.1.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Token 存储（内存） ----
# token -> {"expires_at": datetime}
active_tokens: dict = {}
TOKEN_TTL_HOURS = 24  # token 有效期 24 小时


def clean_expired_tokens():
    """清理过期 token"""
    now = datetime.now()
    expired = [t for t, info in active_tokens.items() if info["expires_at"] < now]
    for t in expired:
        del active_tokens[t]


def verify_token(authorization: Optional[str] = Header(None)):
    """验证 Bearer Token"""
    clean_expired_tokens()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    token = authorization[7:]
    if token not in active_tokens:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    if active_tokens[token]["expires_at"] < datetime.now():
        del active_tokens[token]
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return True


# ---- 认证 API ----
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    message: str = "登录成功"


@app.post("/api/auth/login", response_model=LoginResponse, tags=["认证"])
async def login(req: LoginRequest):
    """管理员登录"""
    config = load_config()
    admin_username = config.get("admin_username", "admin")
    admin_password = config.get("admin_password", "admin123")

    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="账号和密码不能为空")

    if req.username != admin_username or req.password != admin_password:
        raise HTTPException(status_code=401, detail="账号或密码错误")

    # 生成 token
    token = secrets.token_hex(32)
    expires_at = datetime.now() + timedelta(hours=TOKEN_TTL_HOURS)
    active_tokens[token] = {"expires_at": expires_at}

    return LoginResponse(
        token=token,
        username=admin_username,
        message="登录成功"
    )


@app.post("/api/auth/logout", tags=["认证"])
async def logout(authorization: Optional[str] = Header(None)):
    """退出登录"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in active_tokens:
            del active_tokens[token]
    return {"message": "已退出登录"}


@app.get("/api/auth/verify", tags=["认证"])
async def verify(valid: bool = Depends(verify_token)):
    """验证登录状态"""
    return {"valid": True}


# ---- 挂载路由（需要认证的路由通过 Depends 控制）----
# 注意：为了保持向后兼容，知识库、会话、统计等 API 暂不强制认证
# 仅将配置等敏感操作纳入认证。如果需要全面认证，可在各 router 中添加。
app.include_router(knowledge_router)
app.include_router(chat_router)
app.include_router(stats_router)


# ---- 配置 API（需要认证） ----

from fastapi import APIRouter

config_router = APIRouter(prefix="/api/config", tags=["配置"])


class ConfigUpdate(BaseModel):
    qwen_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    company_name: Optional[str] = None
    admin_username: Optional[str] = None
    admin_password: Optional[str] = None


@config_router.get("")
async def get_config(valid: bool = Depends(verify_token)):
    """获取配置（api_key脱敏显示）"""
    return get_masked_config()


@config_router.post("")
async def update_config(update: ConfigUpdate, valid: bool = Depends(verify_token)):
    """更新配置"""
    config = load_config()
    if update.zhipu_api_key is not None:
        if "*" not in update.zhipu_api_key:
            config["zhipu_api_key"] = update.zhipu_api_key
    if update.qwen_api_key is not None:
        if "*" not in update.qwen_api_key:
            config["zhipu_api_key"] = update.qwen_api_key
    if update.system_prompt is not None:
        config["system_prompt"] = update.system_prompt
    if update.welcome_message is not None:
        config["welcome_message"] = update.welcome_message
    if update.company_name is not None:
        config["company_name"] = update.company_name
    if update.admin_username is not None and update.admin_username.strip():
        config["admin_username"] = update.admin_username.strip()
    if update.admin_password is not None and update.admin_password.strip():
        if len(update.admin_password.strip()) < 6:
            raise HTTPException(status_code=400, detail="密码长度不能少于6位")
        config["admin_password"] = update.admin_password.strip()
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
    return {"message": "AI客服管理系统后端运行中", "version": "1.1.0"}


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
        app,
        host="0.0.0.0",
        port=8600,
        reload=False,
        log_level="info"
    )
