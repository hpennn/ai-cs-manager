"""知识库管理模块"""

import os
import uuid
import re
from datetime import datetime
from typing import List

import chromadb
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

# 初始化数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge_base")
CHROMA_DIR = os.path.join(KNOWLEDGE_DIR, "chroma_db")

os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)

# 初始化 ChromaDB 持久化客户端
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = chroma_client.get_or_create_collection(
    name="knowledge",
    metadata={"hnsw:space": "cosine"}
)

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


# ---- Pydantic Models ----

class FAQCreate(BaseModel):
    question: str
    answer: str


class FAQItem(BaseModel):
    id: str
    question: str
    answer: str
    created_at: str


# ---- 文档元数据 ----
# 存储在 data/knowledge_base/docs_meta.json 中
import json

DOCS_META_PATH = os.path.join(KNOWLEDGE_DIR, "docs_meta.json")


def load_docs_meta() -> list:
    if not os.path.exists(DOCS_META_PATH):
        return []
    try:
        with open(DOCS_META_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_docs_meta(meta: list):
    os.makedirs(os.path.dirname(DOCS_META_PATH), exist_ok=True)
    with open(DOCS_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ---- 文本处理 ----

def extract_text_from_txt(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def extract_text_from_pdf(file_path: str) -> str:
    from PyPDF2 import PdfReader
    reader = PdfReader(file_path)
    texts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            texts.append(text)
    return "\n".join(texts)


def extract_text_from_docx(file_path: str) -> str:
    from docx import Document
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    """将文本切分为指定大小的块"""
    # 先清理多余空白
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap
    return chunks


# ---- API Endpoints ----

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传文档并解析、分块、向量化"""
    # 检查文件类型
    filename = file.filename or "unknown"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".txt", ".pdf", ".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .txt, .pdf, .docx 格式文件")
    
    # 保存上传文件
    doc_id = str(uuid.uuid4())
    save_path = os.path.join(KNOWLEDGE_DIR, f"{doc_id}{ext}")
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)
    
    # 提取文本
    try:
        if ext == ".txt":
            text = extract_text_from_txt(save_path)
        elif ext == ".pdf":
            text = extract_text_from_pdf(save_path)
        elif ext == ".docx":
            text = extract_text_from_docx(save_path)
        else:
            raise HTTPException(status_code=400, detail="不支持的文件格式")
    except Exception as e:
        # 清理已保存的文件
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")
    
    if not text.strip():
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=400, detail="文件中未提取到有效文本内容")
    
    # 分块
    chunks = chunk_text(text)
    if not chunks:
        if os.path.exists(save_path):
            os.remove(save_path)
        raise HTTPException(status_code=400, detail="文本分块结果为空，文件内容可能过短")
    
    # 向量化存入 ChromaDB
    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"doc_id": doc_id, "doc_name": filename, "chunk_index": i} for i in range(len(chunks))]
    collection.add(
        documents=chunks,
        ids=ids,
        metadatas=metadatas
    )
    
    # 保存文档元数据
    meta = load_docs_meta()
    meta.append({
        "id": doc_id,
        "name": filename,
        "type": ext.lstrip("."),
        "chunks_count": len(chunks),
        "created_at": datetime.now().isoformat(),
        "file_path": save_path
    })
    save_docs_meta(meta)
    
    return {
        "id": doc_id,
        "name": filename,
        "type": ext.lstrip("."),
        "chunks_count": len(chunks),
        "message": "文档上传并处理成功"
    }


@router.get("/list")
async def list_documents():
    """返回所有知识条目列表"""
    meta = load_docs_meta()
    result = []
    for item in meta:
        result.append({
            "id": item["id"],
            "name": item["name"],
            "type": item["type"],
            "chunks_count": item["chunks_count"],
            "created_at": item["created_at"]
        })
    return result


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档及其向量"""
    meta = load_docs_meta()
    doc_meta = None
    for item in meta:
        if item["id"] == doc_id:
            doc_meta = item
            break
    
    if not doc_meta:
        raise HTTPException(status_code=404, detail="文档不存在")
    
    # 从 ChromaDB 删除向量
    try:
        # 获取该文档的所有 chunk ids
        results = collection.get(where={"doc_id": doc_id})
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        pass  # 向量可能已被清理，忽略
    
    # 删除物理文件
    file_path = doc_meta.get("file_path", "")
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    
    # 更新元数据
    meta = [item for item in meta if item["id"] != doc_id]
    save_docs_meta(meta)
    
    return {"message": "文档删除成功", "id": doc_id}


# ---- FAQ 管理 ----

FAQ_PATH = os.path.join(KNOWLEDGE_DIR, "faq.json")


def load_faq() -> list:
    if not os.path.exists(FAQ_PATH):
        return []
    try:
        with open(FAQ_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_faq(faq_list: list):
    os.makedirs(os.path.dirname(FAQ_PATH), exist_ok=True)
    with open(FAQ_PATH, "w", encoding="utf-8") as f:
        json.dump(faq_list, f, ensure_ascii=False, indent=2)


@router.post("/faq")
async def create_faq(item: FAQCreate):
    """添加FAQ"""
    if not item.question.strip() or not item.answer.strip():
        raise HTTPException(status_code=400, detail="问题和答案不能为空")
    
    faq_list = load_faq()
    faq_id = str(uuid.uuid4())
    faq_item = {
        "id": faq_id,
        "question": item.question.strip(),
        "answer": item.answer.strip(),
        "created_at": datetime.now().isoformat()
    }
    faq_list.append(faq_item)
    save_faq(faq_list)
    
    # 同时存入 ChromaDB 用于语义检索
    faq_text = f"问：{item.question.strip()}\n答：{item.answer.strip()}"
    collection.add(
        documents=[faq_text],
        ids=[f"faq_{faq_id}"],
        metadatas=[{"doc_id": faq_id, "doc_name": "FAQ", "type": "faq"}]
    )
    
    return {"id": faq_id, "message": "FAQ添加成功"}


@router.get("/faq")
async def list_faq():
    """获取所有FAQ列表"""
    faq_list = load_faq()
    return [
        {
            "id": item["id"],
            "question": item["question"],
            "answer": item["answer"],
            "created_at": item.get("created_at", "")
        }
        for item in faq_list
    ]


@router.delete("/faq/{faq_id}")
async def delete_faq(faq_id: str):
    """删除FAQ"""
    faq_list = load_faq()
    found = False
    new_list = []
    for item in faq_list:
        if item["id"] == faq_id:
            found = True
        else:
            new_list.append(item)
    
    if not found:
        raise HTTPException(status_code=404, detail="FAQ不存在")
    
    save_faq(new_list)
    
    # 从 ChromaDB 删除
    try:
        collection.delete(ids=[f"faq_{faq_id}"])
    except Exception:
        pass
    
    return {"message": "FAQ删除成功", "id": faq_id}


def get_chroma_client():
    """供其他模块调用的 ChromaDB 集合获取方法"""
    return collection
