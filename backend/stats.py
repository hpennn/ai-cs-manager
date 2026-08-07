"""统计模块"""

import os
import json
from datetime import datetime, date

from fastapi import APIRouter

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONVERSATIONS_DIR = os.path.join(DATA_DIR, "conversations")
SESSIONS_INDEX_PATH = os.path.join(DATA_DIR, "sessions_index.json")

router = APIRouter(prefix="/api/stats", tags=["统计"])


def _load_all_messages() -> list:
    """加载所有会话的所有消息"""
    all_messages = []
    if not os.path.exists(CONVERSATIONS_DIR):
        return all_messages
    for filename in os.listdir(CONVERSATIONS_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(CONVERSATIONS_DIR, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    messages = json.load(f)
                    all_messages.extend(messages)
            except (json.JSONDecodeError, IOError):
                continue
    return all_messages


def _load_sessions_index() -> list:
    """加载会话索引"""
    if not os.path.exists(SESSIONS_INDEX_PATH):
        return []
    try:
        with open(SESSIONS_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


@router.get("")
async def get_stats():
    """返回统计数据"""
    sessions = _load_sessions_index()
    all_messages = _load_all_messages()
    today_str = date.today().isoformat()

    # 总会话数
    total_sessions = len(sessions)

    # 总消息数（只算用户消息）
    total_messages = sum(1 for msg in all_messages if msg.get("role") == "user")

    # 今日消息数
    today_messages = sum(
        1 for msg in all_messages
        if msg.get("role") == "user" and msg.get("timestamp", "").startswith(today_str)
    )

    # 平均响应时间（从用户消息到assistant消息的时间差）
    response_times = []
    conversations_by_session = {}
    for msg in all_messages:
        ts = msg.get("timestamp", "")
        if ts:
            session_file = ""
            # 按会话组织消息
            # 这里简单处理：直接按顺序配对
            pass

    # 简单计算：遍历每个会话文件
    if os.path.exists(CONVERSATIONS_DIR):
        for filename in os.listdir(CONVERSATIONS_DIR):
            if filename.endswith(".json"):
                file_path = os.path.join(CONVERSATIONS_DIR, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        messages = json.load(f)
                    # 配对 user -> assistant 消息计算响应时间
                    i = 0
                    while i < len(messages) - 1:
                        if messages[i].get("role") == "user" and messages[i + 1].get("role") == "assistant":
                            try:
                                user_time = datetime.fromisoformat(messages[i].get("timestamp", ""))
                                assistant_time = datetime.fromisoformat(messages[i + 1].get("timestamp", ""))
                                diff = (assistant_time - user_time).total_seconds()
                                if diff >= 0:
                                    response_times.append(diff)
                            except (ValueError, TypeError):
                                pass
                            i += 2
                        else:
                            i += 1
                except (json.JSONDecodeError, IOError):
                    continue

    avg_response_time = 0.0
    if response_times:
        avg_response_time = round(sum(response_times) / len(response_times), 2)

    return {
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "today_messages": today_messages,
        "avg_response_time": avg_response_time
    }
