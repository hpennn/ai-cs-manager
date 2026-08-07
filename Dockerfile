FROM python:3.10-slim

WORKDIR /app

# 安装依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 创建数据目录
RUN mkdir -p data/knowledge_base data/conversations

EXPOSE 8600

CMD ["python", "backend/main.py"]
