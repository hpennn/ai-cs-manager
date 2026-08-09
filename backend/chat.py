"""对话引擎模块"""

import os
import json
import uuid
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from knowledge import get_chroma_client
from config import get_config_value

# 数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")
SESSIONS_INDEX_PATH = os.path.join(DATA_DIR, "sessions_index.json")

os.makedirs(CONVERSATIONS_DIR, exist_ok=True)

router = APIRouter(tags=["对话"])


# ---- Pydantic Models ----

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatSource(BaseModel):
    text: str
    score: float


class ModeUpdateRequest(BaseModel):
    mode: str  # "auto" | "human"


class AdminMessageRequest(BaseModel):
    content: str


# ---- 通义千问 API 调用 ----

async def call_qwen(messages: list) -> str:
    """调用通义千问API"""
    api_key = get_config_value("qwen_api_key", "")
    if not api_key:
        return "请先在设置中配置通义千问API Key"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "qwen-turbo",
                    "messages": messages
                },
                timeout=30
            )
            data = resp.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                return f"API调用异常: {json.dumps(data, ensure_ascii=False)}"
    except httpx.TimeoutException:
        return "AI服务响应超时，请稍后重试"
    except httpx.ConnectError:
        return "无法连接到AI服务，请检查网络连接"
    except Exception as e:
        return f"调用AI服务出错: {str(e)}"


# ---- 知识检索 ----

def retrieve_knowledge(query: str, top_k: int = 3) -> list:
    """从ChromaDB检索相关知识"""
    try:
        collection = get_chroma_client()
        results = collection.query(
            query_texts=[query],
            n_results=top_k
        )
        sources = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                score = 0.0
                if results.get("distances") and i < len(results["distances"][0]):
                    # cosine distance -> similarity score
                    score = round(1.0 - results["distances"][0][i], 4)
                sources.append({"text": doc, "score": score})
        return sources
    except Exception:
        return []


# ---- 对话记录管理 ----

def load_session_messages(session_id: str) -> list:
    """加载某个会话的消息记录"""
    file_path = os.path.join(CONVERSATIONS_DIR, f"{session_id}.json")
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_session_messages(session_id: str, messages: list):
    """保存会话消息记录"""
    file_path = os.path.join(CONVERSATIONS_DIR, f"{session_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def load_sessions_index() -> list:
    """加载会话索引"""
    if not os.path.exists(SESSIONS_INDEX_PATH):
        return []
    try:
        with open(SESSIONS_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_sessions_index(index: list):
    """保存会话索引"""
    with open(SESSIONS_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def get_session_mode(session_id: str) -> str:
    """获取会话当前模式，默认 auto"""
    index = load_sessions_index()
    for item in index:
        if item["session_id"] == session_id:
            return item.get("mode", "auto")
    return "auto"


def set_session_mode(session_id: str, mode: str):
    """设置会话模式"""
    index = load_sessions_index()
    for item in index:
        if item["session_id"] == session_id:
            item["mode"] = mode
            save_sessions_index(index)
            return True
    return False


def update_session_index(session_id: str):
    """更新会话索引（新增或更新时间戳）"""
    index = load_sessions_index()
    found = False
    for item in index:
        if item["session_id"] == session_id:
            item["updated_at"] = datetime.now().isoformat()
            item["message_count"] = item.get("message_count", 0) + 1
            found = True
            break
    if not found:
        index.append({
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 1,
            "mode": "auto"
        })
    save_sessions_index(index)


# ---- 核心对话处理 ----

async def process_chat(session_id: str, message: str) -> dict:
    """处理一条用户消息，返回AI回复"""
    # 检索相关知识
    sources = retrieve_knowledge(message, top_k=3)

    # 构建上下文
    context_parts = []
    if sources:
        for i, src in enumerate(sources, 1):
            context_parts.append(f"[知识{i}] {src['text']}")

    # 构建消息
    system_prompt = get_config_value(
        "system_prompt",
        "你是一个专业的电商客服助手，根据知识库中的信息回答用户问题。如果知识库中没有相关信息，请礼貌地告知用户并建议联系人工客服。回答要简洁、准确、友好。"
    )

    system_content = system_prompt
    if context_parts:
        system_content += "\n\n以下是从知识库中检索到的相关信息，请参考这些信息回答用户问题：\n" + "\n\n".join(context_parts)

    # 加载历史对话
    history = load_session_messages(session_id)

    # 构建发送给API的消息列表
    api_messages = [{"role": "system", "content": system_content}]

    # 加入最近的对话历史（最多保留最近10轮）
    recent_history = history[-20:] if len(history) > 20 else history
    for msg in recent_history:
        api_messages.append({"role": msg["role"], "content": msg["content"]})

    # 加入当前用户消息
    api_messages.append({"role": "user", "content": message})

    # 调用AI
    reply = await call_qwen(api_messages)

    # 保存对话记录
    history.append({
        "role": "user",
        "content": message,
        "timestamp": datetime.now().isoformat()
    })
    history.append({
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.now().isoformat(),
        "sources": sources
    })
    save_session_messages(session_id, history)
    update_session_index(session_id)

    return {"reply": reply, "sources": sources}


# ---- WebSocket 连接管理器 ----

class ConnectionManager:
    """WebSocket连接管理器（客户侧 + 管理员侧）"""

    def __init__(self):
        # 客户侧: session_id -> WebSocket
        self.active_connections: dict[str, WebSocket] = {}
        # 管理员侧: session_id -> set of WebSockets（同一会话可有多人监听）
        self.admin_connections: dict[str, set] = {}

    # -- 客户侧 --
    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active_connections.pop(session_id, None)

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(message)

    # -- 管理员侧 --
    async def admin_connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        if session_id not in self.admin_connections:
            self.admin_connections[session_id] = set()
        self.admin_connections[session_id].add(websocket)

    def admin_disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.admin_connections:
            self.admin_connections[session_id].discard(websocket)
            if not self.admin_connections[session_id]:
                del self.admin_connections[session_id]

    async def broadcast_to_admins(self, session_id: str, message: dict):
        """向某会话的所有管理员连接广播消息"""
        if session_id in self.admin_connections:
            dead = []
            for ws in self.admin_connections[session_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.admin_connections[session_id].discard(ws)


manager = ConnectionManager()


# ---- WebSocket 客户实时对话 ----

@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket实时对话（客户端）"""
    await manager.connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"reply": "消息不能为空", "sources": []})
                continue

            # 获取会话模式
            mode = get_session_mode(session_id)

            # 通知管理员（无论哪种模式都推送）
            await manager.broadcast_to_admins(session_id, {
                "type": "customer_message",
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "mode": mode
            })

            if mode == "auto":
                # 自动模式：照常调 process_chat（内部负责保存用户消息+AI回复+更新索引）
                result = await process_chat(session_id, message)
                await websocket.send_json(result)

                # 通知管理员 AI 已回复
                await manager.broadcast_to_admins(session_id, {
                    "type": "ai_reply",
                    "reply": result.get("reply", ""),
                    "sources": result.get("sources", []),
                    "timestamp": datetime.now().isoformat()
                })
            else:
                # 人工模式：不调AI，只保存用户消息并标记等待
                history = load_session_messages(session_id)
                history.append({
                    "role": "user",
                    "content": message,
                    "timestamp": datetime.now().isoformat(),
                    "pending_human_reply": True
                })
                save_session_messages(session_id, history)
                update_session_index(session_id)

                await websocket.send_json({
                    "reply": "您的消息已收到，正在为您转接人工客服，请稍候...",
                    "sources": [],
                    "mode": "human"
                })

                # 通知管理员需要人工回复
                await manager.broadcast_to_admins(session_id, {
                    "type": "needs_human_reply",
                    "customer_message": message,
                    "timestamp": datetime.now().isoformat()
                })
    except WebSocketDisconnect:
        manager.disconnect(session_id)


# ---- WebSocket 管理员实时对话 ----

@router.websocket("/ws/admin/{session_id}")
async def websocket_admin(websocket: WebSocket, session_id: str):
    """管理员WebSocket端点，实时监听客户消息并可发送消息"""
    await manager.admin_connect(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "")

            if action == "send_message":
                # 管理员手动发送消息给客户
                content = data.get("content", "").strip()
                if not content:
                    await websocket.send_json({"type": "error", "message": "消息不能为空"})
                    continue

                # 保存到会话记录
                history = load_session_messages(session_id)
                history.append({
                    "role": "assistant",
                    "content": content,
                    "timestamp": datetime.now().isoformat(),
                    "from": "human"
                })
                save_session_messages(session_id, history)
                update_session_index(session_id)

                # 发送给客户端
                await manager.send_message(session_id, {
                    "reply": content,
                    "sources": [],
                    "from": "human"
                })

                # 通知管理员侧确认
                await websocket.send_json({
                    "type": "message_sent",
                    "content": content,
                    "timestamp": datetime.now().isoformat()
                })

            elif action == "get_messages":
                # 管理员获取历史消息
                messages = load_session_messages(session_id)
                await websocket.send_json({
                    "type": "messages",
                    "messages": messages
                })
            else:
                await websocket.send_json({"type": "error", "message": f"未知操作: {action}"})
    except WebSocketDisconnect:
        manager.admin_disconnect(session_id, websocket)


# ---- HTTP API 接口 ----

@router.post("/api/chat")
async def chat(request: ChatRequest):
    """HTTP对话接口"""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    result = await process_chat(request.session_id, request.message)
    return result


# ---- 会话管理接口 ----

@router.get("/api/sessions")
async def list_sessions():
    """获取所有会话列表（含 mode、last_message、customer_name）"""
    index = load_sessions_index()

    # 为每个会话补充增强字段
    for item in index:
        # 确保 mode 字段存在
        if "mode" not in item:
            item["mode"] = "auto"

        # 获取最后一条消息预览
        messages = load_session_messages(item["session_id"])
        if messages:
            last = messages[-1]
            item["last_message"] = last.get("content", "")
            item["last_message_role"] = last.get("role", "")
            item["last_message_time"] = last.get("timestamp", "")
        else:
            item["last_message"] = ""
            item["last_message_role"] = ""
            item["last_message_time"] = ""

        # 客户昵称（取第一条 user 消息的前20字符作为标识，或使用 session_id 前8位）
        if "customer_name" not in item:
            user_messages = [m for m in messages if m.get("role") == "user"]
            if user_messages:
                # 尝试从第一条消息推断昵称
                first_msg = user_messages[0].get("content", "")
                item["customer_name"] = f"客户-{item['session_id'][:8]}"
            else:
                item["customer_name"] = f"客户-{item['session_id'][:8]}"

    # 按更新时间倒序
    index.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return index


@router.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """获取会话详情（含 mode）"""
    index = load_sessions_index()
    session_info = None
    for item in index:
        if item["session_id"] == session_id:
            session_info = item.copy()
            break

    if not session_info:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 确保 mode 字段
    if "mode" not in session_info:
        session_info["mode"] = "auto"

    # 附加消息记录
    session_info["messages"] = load_session_messages(session_id)
    return session_info


@router.put("/api/sessions/{session_id}/mode")
async def update_mode(session_id: str, request: ModeUpdateRequest):
    """切换会话模式"""
    if request.mode not in ("auto", "human"):
        raise HTTPException(status_code=400, detail="mode 必须为 'auto' 或 'human'")

    # 检查会话是否存在
    index = load_sessions_index()
    exists = any(item["session_id"] == session_id for item in index)
    if not exists:
        raise HTTPException(status_code=404, detail="会话不存在")

    set_session_mode(session_id, request.mode)

    # 通知管理员切换事件
    await manager.broadcast_to_admins(session_id, {
        "type": "mode_changed",
        "mode": request.mode,
        "timestamp": datetime.now().isoformat()
    })

    # 通知客户端
    await manager.send_message(session_id, {
        "type": "mode_changed",
        "mode": request.mode,
        "timestamp": datetime.now().isoformat()
    })

    return {"session_id": session_id, "mode": request.mode}


@router.post("/api/sessions/{session_id}/messages")
async def admin_send_message(session_id: str, request: AdminMessageRequest):
    """管理员手动发送消息"""
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 检查会话是否存在
    index = load_sessions_index()
    exists = any(item["session_id"] == session_id for item in index)
    if not exists:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 保存到会话记录
    history = load_session_messages(session_id)
    history.append({
        "role": "assistant",
        "content": request.content,
        "timestamp": datetime.now().isoformat(),
        "from": "human"
    })
    save_session_messages(session_id, history)
    update_session_index(session_id)

    # 通过 WebSocket 发送给客户端
    await manager.send_message(session_id, {
        "reply": request.content,
        "sources": [],
        "from": "human"
    })

    # 通知管理员侧
    await manager.broadcast_to_admins(session_id, {
        "type": "human_reply",
        "content": request.content,
        "timestamp": datetime.now().isoformat()
    })

    return {"status": "sent", "timestamp": datetime.now().isoformat()}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    # 从索引中移除
    index = load_sessions_index()
    new_index = [item for item in index if item["session_id"] != session_id]

    if len(new_index) == len(index):
        raise HTTPException(status_code=404, detail="会话不存在")

    save_sessions_index(new_index)

    # 删除对话记录文件
    file_path = os.path.join(CONVERSATIONS_DIR, f"{session_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)

    return {"status": "deleted", "session_id": session_id}


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages_api(session_id: str):
    """获取某会话的消息记录"""
    messages = load_session_messages(session_id)
    if not messages:
        # 检查session是否存在
        index = load_sessions_index()
        if not any(item["session_id"] == session_id for item in index):
            raise HTTPException(status_code=404, detail="会话不存在")
    return messages
