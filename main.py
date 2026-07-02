from time import process_time
import os
import yaml
import re
from dotenv import load_dotenv
load_dotenv()

def _resolve_env_vars(obj):
    """递归替换配置中的 ${ENV_VAR} 占位符为实际环境变量值"""
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        pattern = re.compile(r'\$\{(\w+)\}')
        return pattern.sub(lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    return obj

with open("config.yaml","r") as f:
    config = yaml.safe_load(f)
config = _resolve_env_vars(config)

import time
import numpy as np
import uuid
import datetime
import traceback

import uvicorn
from typing import Annotated
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, Request
import json
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os

# static 目录绝对路径
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

from router_schema import (
    EmbeddingRequest,EmbeddingResponse,
    RerankRequest,RerankResponse,
    KnowledgeRequest,KnowledgeResponse,
    DocumentRequest,DocumentResponse,
    RAGRequest,RAGResponse
)

from rag_api import RAG
from db_api import (
    KnowledgeDatabase,KnowledgeDocument,
    Session
)
from es_api import es

def retry_with_backoff(max_retries = 10,base_delay = 0.05):
    """
    指数退避重试器
    每次遇到数据库被另一条命令占用而上锁时
    操作数据库失败
    等待时间翻倍：0.05 -> 0.1 -> 0.2 -> 0.4
    :param max_retries: 重试次数
    :param base_delay: 基础等待时间
    :return: 无
    """
    for attempt in range(max_retries):
        try:
            yield attempt
            return
        except Exception:
            if attempt < max_retries - 1:
                wait = base_delay * (2 ** attempt)
                time.sleep(wait)
    # 如果所有重试都失败，则由每个接口的最外层except处理失败
    raise
app = FastAPI()

# CORS — 允许前端跨端口访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 根路径：返回前端页面 ----------
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# ---------- API Key 鉴权中间件 ----------
EXEMPT_PATHS = {"/", "/docs", "/openapi.json", "/redoc"}  # 放行路径前缀

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    path = request.url.path
    if any(path == ep or path.startswith(ep + "/") for ep in EXEMPT_PATHS):
        return await call_next(request)

    expected_key = config.get("auth", {}).get("api_key", "")
    client_key = request.headers.get("X-API-Key", "")
    if expected_key and client_key != expected_key:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized: invalid or missing X-API-Key"})

    return await call_next(request)
# ----------------------------------------

#todo:1.知识库接口，包括创建、查询、删除

#创建知识库接口：POST /v1/knowledge_database
@app.post("/v1/knowledge_database")
def add_knowledge_database(req: KnowledgeRequest) -> KnowledgeResponse:
    start_time = time.time()
    try:
        for attempt in retry_with_backoff():
            with Session() as session:
                record = KnowledgeDatabase(
                    title = req.title,
                    category = req.category,
                    create_dt = datetime.datetime.now(),
                    update_dt = datetime.datetime.now(),
                )
                session.add(record)
                session.flush() # 刷新session，获取自增ID
                knowledge_id = record.knowledge_id
                session.commit()
            return KnowledgeResponse(
                request_id = str(uuid.uuid4()),
                knowledge_id = knowledge_id,
                category = req.category,
                title = req.title,
                response_code = 200,
                response_msg = "知识库创建成功！",
                process_status = "completed",
                process_time = time.time() - start_time
            )
    except Exception as e:
        print(traceback.format_exc())
    return KnowledgeResponse(
        request_id = str(uuid.uuid4()),
        knowledge_id = -1,
        category = "",
        title = "",
        response_code = 500,
        response_msg = "知识库创建失败!",
        process_status = "failed",
        process_time = time.time() - start_time
        )
# 查询所有知识库列表: GET /v1/knowledge_databases
@app.get("/v1/knowledge_databases")
def list_knowledge_databases():
    with Session() as session:
        records = session.query(KnowledgeDatabase).all()
        return [
            {"knowledge_id":r.knowledge_id, "title":r.title, "category":r.category}
            for r in records
        ]

# 查询知识库接口: GET /v1/knowledge_database
@app.get("/v1/knowledge_database")
def get_knowledge_database(knowledge_id: int,token:str) -> KnowledgeResponse:
    start_time = time.time()
    try:
        for attempt in retry_with_backoff():
            with Session() as session:
                record = session.query(KnowledgeDatabase).filter(KnowledgeDatabase.knowledge_id == knowledge_id).first()
                if record is not None:
                    return KnowledgeResponse(
                        request_id = str(uuid.uuid4()),
                        knowledge_id = record.knowledge_id,
                        category = str(record.category),
                        title = str(record.title),
                        response_code = 200,
                        response_msg = "知识库查询成功!",
                        process_status = "completed",
                        process_time = time.time() - start_time
                    )
                #没查到record的话，直接跳出循环
                break
    except Exception as e:
        print(traceback.format_exc())

    return KnowledgeResponse(
        request_id = str(uuid.uuid4()),
        knowledge_id = knowledge_id,
        category = "",
        title = "",
        response_code = 404,
        response_msg = "知识库不存在,查询失败!",
        process_status = "failed",
        process_time = time.time() - start_time
    )

#删除知识库接口: DELETE /v1/knowledge_database
@app.delete("/v1/knowledge_database")
def delete_knowledge_database(knowledge_id: int,token:str)-> KnowledgeResponse:
    start_time = time.time()
    try:
        for attempt in retry_with_backoff():
            with Session() as session:
                kb = session.query(KnowledgeDatabase).filter(KnowledgeDatabase.knowledge_id == knowledge_id).first()
                if kb is None:
                    break

                # 查出该知识库下所有文档
                docs = session.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_id == knowledge_id).all()

                # (1) 删除 ES 中的文档索引
                for doc in docs:
                    es.delete_by_query(
                        index="document_meta",
                        body={"query":{"term":{"document_id":doc.document_id}}}
                    )
                    es.delete_by_query(
                        index="chunk_info",
                        body={"query":{"term":{"document_id":doc.document_id}}}
                    )

                # (2) 删除本地文件
                for doc in docs:
                    file_path = doc.file_path if doc.file_path else ""
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass

                # (3) 删除 SQLite 中的文档记录
                for doc in docs:
                    session.delete(doc)

                # (4) 删除 SQLite 中的知识库记录
                session.delete(kb)
                session.commit()

                return KnowledgeResponse(
                    request_id = str(uuid.uuid4()),
                    knowledge_id = knowledge_id,
                    category = str(kb.category),
                    title = str(kb.title),
                    response_code = 200,
                    response_msg = "知识库删除成功！",
                    process_status = "completed",
                    process_time = time.time() - start_time
                )
    except Exception as e:
        print(traceback.format_exc())
    return KnowledgeResponse(
        request_id = str(uuid.uuid4()),
        knowledge_id = knowledge_id,
        category = "",
        title = "",
        response_code = 404,
        response_msg = "未查询到该知识库，知识库删除失败！",
        process_status = "failed",
        process_time = time.time() - start_time
        )

#todo:2.知识库文档接口，包括创建、查询、删除

# 创建知识库文档接口: POST /v1/knowledge_document
@app.post("/v1/knowledge_document")
async def add_knowledge_document(
        background_tasks: BackgroundTasks,
        knowledge_id: int = Form(),
        title: str = Form(),
        category: str = Form(),
        file: UploadFile = File(...),
)-> DocumentResponse:
    start_time = time.time()
    response_code = 500
    response_msg = "新增文档失败！"
    try:
        for attempt in retry_with_backoff():
            with Session() as session:
                #(1).检查知识库是否存在
                kb = session.query(KnowledgeDatabase).filter(KnowledgeDatabase.knowledge_id == knowledge_id).first()
                if kb is None:
                    response_code = 404
                    response_msg = "知识库不存在，请先创建知识库！"
                    break
                #(2).如果知识库没问题，则接下来创建文档
                record = KnowledgeDocument(
                    title = title,
                    category = category,
                    knowledge_id = knowledge_id,
                    file_path = "", #先占位，后续会更新
                    file_type = file.content_type,
                    create_dt = datetime.datetime.now(),
                    update_dt = datetime.datetime.now(),
                )
                session.add(record)
                session.flush()
                document_id = record.document_id
                session.commit()
                #(3).创建文档成功后,把上传的文档写进本地磁盘中
                os.makedirs("upload_files", exist_ok=True)
                file_path = f"upload_files/document_id_{document_id}_" + file.filename
                file_content = await file.read() #异步读文件内容
                with open(file_path,"wb") as buffer:
                    buffer.write(file_content)
                #更新SQLite中的文件路径
                record = session.query(KnowledgeDocument).filter(KnowledgeDocument.document_id == document_id).first()
                record.file_path = file_path
                session.commit()
            #(4).后台异步解析文档，并把解析结果写入ES数据库中
            background_tasks.add_task(
                RAG().extract_content,
                knowledge_id = knowledge_id,
                document_id =document_id,
                title = title,
                file_path = file_path,
                file_type = file.content_type
            )

            return DocumentResponse(
                request_id = str(uuid.uuid4()),
                document_id = document_id,
                category = category,
                title = title,
                knowledge_id = knowledge_id,
                file_type = file.content_type,
                response_code = 200,
                response_msg = "文档添加成功，后台正在解析文档，请稍等！",
                process_status = "completed",
                process_time = time.time() - start_time
            )
    except Exception as e:
        print(traceback.format_exc())

    return DocumentResponse(
        request_id = str(uuid.uuid4()),
        document_id = -1,
        category = "",
        title = "",
        knowledge_id = -1,
        file_type = "",
        response_code = response_code,
        response_msg = response_msg,
        process_status = "failed",
        process_time = time.time() - start_time
    )


# 查询知识库下所有文档: GET /v1/knowledge_documents
@app.get("/v1/knowledge_documents")
def list_knowledge_documents(knowledge_id: int):
    with Session() as session:
        records = session.query(KnowledgeDocument).filter(
            KnowledgeDocument.knowledge_id == knowledge_id
        ).all()
        return [
            {"document_id":r.document_id, "title":r.title, "file_type":r.file_type}
            for r in records
        ]

# 查询单个知识库文档接口: GET /v1/knowledge_document
@app.get("/v1/knowledge_document")
def get_knowledge_document(document_id: int,token: str)-> DocumentResponse:
    start_time = time.time()
    try:
        for attempt in retry_with_backoff():
            with Session() as session:
                record = session.query(KnowledgeDocument).filter(KnowledgeDocument.document_id == document_id).first()
                if record is not None:
                    return DocumentResponse(
                        request_id = str(uuid.uuid4()),
                        document_id = record.document_id,
                        category = str(record.category),
                        title = str(record.title),
                        knowledge_id = int(record.knowledge_id),
                        file_type = str(record.file_type),
                        response_code = 200,
                        response_msg = "文档查询成功！",
                        process_status = "completed",
                        process_time = time.time() - start_time
                    )
                # 如果record 是 None，则不存在该文档，跳出循环
                break
    except Exception as e:
        print(traceback.format_exc())
    return DocumentResponse(
        request_id = str(uuid.uuid4()),
        document_id = document_id,
        category = "",
        title = "",
        knowledge_id = -1,
        file_type = "",
        response_code = 404,
        response_msg = "未找到该知识库文档，文档查询失败！",
        process_status = "failed",
        process_time = time.time() - start_time
    )

# 删除知识库文档接口: DELETE /v1/knowledge_document
@app.delete("/v1/knowledge_document")
def delete_knowledge_document(document_id: int,token: str)-> DocumentResponse:
    start_time = time.time()
    response_code = 500
    response_msg = "删除文档失败！"
    try:
        for attempt in retry_with_backoff():
            with Session() as session:
                record = session.query(KnowledgeDocument).filter(KnowledgeDocument.document_id == document_id).first()
                if record is None:
                    response_code = 404
                    response_msg = "未找到该知识库文档，删除失败！"
                    break
                #record is not None,文档存在
                #记录文档信息，用于返回DocumentResponse
                knowledge_id = int(record.knowledge_id)
                category = str(record.category)
                title = str(record.title)

                #(1).删除SQLite中的文档记录
                session.delete(record)
                session.commit()
                #(2).删除本地文件
                if record.file_path and os.path.exists(record.file_path):
                    os.remove(record.file_path)
            #(3).删除SQLite文档成功后，删除ES数据库中的文档记录
            es.delete_by_query(
                index = "document_meta",
                body = {
                    "query":{
                        "term":{
                            "document_id":document_id
                        }
                    }
                }
            )
            es.delete_by_query(
                index = "chunk_info",
                body = {
                    "query":{
                        "term":{
                            "document_id":document_id
                        }
                    }
                }
            )
            return DocumentResponse(
                request_id = str(uuid.uuid4()),
                document_id = document_id,
                category = category,
                title = title,
                knowledge_id = knowledge_id,
                file_type = str(record.file_type),
                response_code = 200,
                response_msg = "文档删除成功！",
                process_status = "completed",
                process_time = time.time() - start_time
            )
    except Exception as e:
        print(traceback.format_exc())
    return DocumentResponse(
        request_id = str(uuid.uuid4()),
        document_id = document_id,
        category = "",
        title = "",
        knowledge_id = -1,
        file_type = "",
        response_code = response_code,
        response_msg = response_msg,
        process_status = "failed",
        process_time = time.time() - start_time
    )

#todo:3.RAG相关的接口：embedding,rerank,chat

#创建全局RAG实例(服务启动时，加载模型，所有请求复用)
rag = RAG()

#文本向量化接口: POST /v1/embedding
@app.post("/v1/embedding")
def embedding(req: EmbeddingRequest) -> EmbeddingResponse:
    """

    :param req:
    :return:
    """
    start_time = time.time()

    try:
        if not isinstance(req.text, list):
            text = [req.text]
        else:
            text = req.text
        embedding_vector = rag.get_embedding(text)
        return EmbeddingResponse(
            request_id = str(uuid.uuid4()),
            vector = embedding_vector.astype(np.float64).tolist(),
            response_code = 200,
            response_msg = "文本向量化成功！",
            process_status = "completed",
            process_time = time.time() - start_time,
        )
    except Exception as e:
        print(traceback.format_exc())
        return EmbeddingResponse(
            request_id = str(uuid.uuid4()),
            vector = [[]],
            response_code = 500,
            response_msg = "文本向量化失败！",
            process_status = "failed",
            process_time = time.time() - start_time,
        )

#重排序接口: POST /v1/rerank
@app.post("/v1/rerank")
def rerank(req: RerankRequest) -> RerankResponse:
    """

    :param req:
    :return:
    """
    start_time = time.time()
    try:
        scores = rag.get_rerank(req.text_pair)
        return RerankResponse(
            request_id = str(uuid.uuid4()),
            vector = scores.astype(np.float64).tolist(),
            response_code = 200,
            response_msg = "重排序完成!",
            process_status = "completed",
            process_time = time.time() - start_time,
        )
    except Exception as e:
        print(traceback.format_exc())
        return RerankResponse(
            request_id = str(uuid.uuid4()),
            vector = [],
            response_code = 500,
            response_msg = "重排序失败！",
            process_status = "failed",
            process_time = time.time() - start_time,
        )

#对话接口: POST /v1/chat
@app.post("/v1/chat")
async def chat_stream(req:RAGRequest):
    """流式 SSE 端点"""
    def generate():
        try:
            sent_done = False
            for item in rag.chat_with_rag_stream(req.knowledge_id, req.message):
                if isinstance(item, dict) and "sources" in item:
                    yield f"data: {json.dumps({'done': True, 'sources': item['sources']}, ensure_ascii=False)}\n\n"
                    sent_done = True
                else:
                    yield f"data: {json.dumps({'token': item}, ensure_ascii=False)}\n\n"
            if not sent_done:
                yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'error': traceback.format_exc()})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.post("/v1/chat/sync")
def chat_sync(req:RAGRequest) -> RAGResponse:
    start_time = time.time()
    try:
        updated_messages, sources = rag.chat_with_rag(req.knowledge_id,req.message)
        return RAGResponse(
            request_id = str(uuid.uuid4()),
            message = updated_messages,
            sources = sources,
            response_code = 200,
            response_msg = "对话完成！",
            process_status = "completed",
            process_time = time.time() - start_time,
        )
    except Exception as e:
        print(traceback.format_exc())
        return RAGResponse(
            request_id = str(uuid.uuid4()),
            message = [],
            response_code = 500,
            response_msg = "对话失败!",
            process_status = "failed",
            process_time = time.time() - start_time,
        )

if __name__ == '__main__':
    uvicorn.run(app,host = "0.0.0.0",port = config["rag"]["port"],workers = 1)
