"""
RAG 接口端到端测试脚本
启动 main.py 后运行：python test_api.py
"""
import requests
import time
import json

BASE_URL = "http://localhost:6010"
HEADERS = {"X-API-Key": "rag-internal-key-2025"}
TEST_PDF = "upload_files/document_id_2_物业费知识手册.pdf"

def log(step, msg):
    print(f"[{step}] {msg}")

def test_health():
    """0. 健康检查"""
    try:
        r = requests.get(f"{BASE_URL}/docs", timeout=3, headers=HEADERS)
        log("健康检查", f"服务在线，状态码 {r.status_code}")
        return True
    except:
        log("健康检查", "服务未启动，请先执行 python main.py")
        return False


def test_create_knowledge():
    """1. 创建知识库"""
    resp = requests.post(f"{BASE_URL}/v1/knowledge_database", json={
        "category": "政策法规",
        "title": "测试知识库-物业费"
    }, headers=HEADERS)
    data = resp.json()
    code = data.get("response_code")
    kid = data.get("knowledge_id", -1)
    if code == 200:
        log("创建知识库", f"成功 → knowledge_id={kid}")
    else:
        log("创建知识库", f"失败 → {data.get('response_msg')}")
    return kid


def test_query_knowledge(knowledge_id):
    """2. 查询知识库"""
    resp = requests.get(f"{BASE_URL}/v1/knowledge_database", params={
        "knowledge_id": knowledge_id,
        "token": "test"
    }, headers=HEADERS)
    data = resp.json()
    if data.get("response_code") == 200:
        log("查询知识库", f"成功 → 标题={data.get('title')}, 分类={data.get('category')}")
    else:
        log("查询知识库", f"失败 → {data.get('response_msg')}")


def test_upload_document(knowledge_id):
    """3. 上传文档"""
    import os
    if not os.path.exists(TEST_PDF):
        log("上传文档", f"跳过，文件不存在: {TEST_PDF}")
        return -1

    with open(TEST_PDF, "rb") as f:
        resp = requests.post(f"{BASE_URL}/v1/knowledge_document",
            data={
                "knowledge_id": str(knowledge_id, headers=HEADERS),
                "title": "物业费知识手册",
                "category": "物业"
            },
            files={"file": ("物业费知识手册.pdf", f, "application/pdf")}
        )
    print(f"  DEBUG: status={resp.status_code}, body={resp.text[:300]}")
    data = resp.json()
    doc_id = data.get("document_id", -1)
    if data.get("response_code") == 200:
        log("上传文档", f"成功 → document_id={doc_id}，后台解析中...")
    else:
        log("上传文档", f"失败 → {data.get('response_msg')}")
    return doc_id


def test_query_document(document_id):
    """4. 查询文档"""
    resp = requests.get(f"{BASE_URL}/v1/knowledge_document", params={
        "document_id": document_id,
        "token": "test"
    }, headers=HEADERS)
    data = resp.json()
    if data.get("response_code") == 200:
        log("查询文档", f"成功 → 文件名={data.get('title')}, 类型={data.get('file_type')}")
    else:
        log("查询文档", f"失败 → {data.get('response_msg')}")


def test_embedding():
    """5. 文本向量化"""
    resp = requests.post(f"{BASE_URL}/v1/embedding", json={
        "text": "物业费收费标准是什么",
        "token": "test",
        "model": "bge-small-zh-v1.5"
    }, headers=HEADERS)
    data = resp.json()
    vec = data.get("vector", [[]])
    dim = len(vec[0]) if vec and vec[0] else 0
    if data.get("response_code") == 200:
        log("向量化", f"成功 → 向量维度={dim}")
    else:
        log("向量化", f"失败 → {data.get('response_msg')}")


def test_rerank():
    """6. 重排序"""
    resp = requests.post(f"{BASE_URL}/v1/rerank", json={
        "text_pair": [
            ["物业费如何计算", "物业费按建筑面积乘以单价计算"],
            ["物业费如何计算", "今天天气很好适合出门"]
        ],
        "token": "test",
        "model": "bge-reranker-base"
    }, headers=HEADERS)
    data = resp.json()
    scores = data.get("vector", [])
    if data.get("response_code") == 200:
        log("重排序", f"成功 → 分数=[{scores[0]:.4f}, {scores[1]:.4f}]（前者应远高于后者）")
    else:
        log("重排序", f"失败 → {data.get('response_msg')}")


def test_chat(knowledge_id):
    """7. RAG 对话"""
    resp = requests.post(f"{BASE_URL}/v1/chat", json={
        "knowledge_id": knowledge_id,
        "message": [
            {"role": "user", "content": "物业费收费标准是什么？"}
        ]
    }, headers=HEADERS)
    data = resp.json()
    if data.get("response_code") == 200:
        msgs = data.get("message", [])
        answer = msgs[-1].get("content", "") if msgs else ""
        preview = answer[:100].replace("\n", " ")
        log("RAG对话", f"成功 → 回答预览: {preview}...")
    else:
        log("RAG对话", f"失败 → {data.get('response_msg')}")


def test_delete_document(document_id):
    """8. 删除文档"""
    resp = requests.delete(f"{BASE_URL}/v1/knowledge_document", params={
        "document_id": document_id,
        "token": "test"
    }, headers=HEADERS)
    data = resp.json()
    if data.get("response_code") == 200:
        log("删除文档", "成功")
    else:
        log("删除文档", f"失败 → {data.get('response_msg')}")


def test_delete_knowledge(knowledge_id):
    """9. 删除知识库"""
    resp = requests.delete(f"{BASE_URL}/v1/knowledge_database", params={
        "knowledge_id": knowledge_id,
        "token": "test"
    }, headers=HEADERS)
    data = resp.json()
    if data.get("response_code") == 200:
        log("删除知识库", "成功")
    else:
        log("删除知识库", f"失败 → {data.get('response_msg')}")


if __name__ == "__main__":
    print("=" * 50)
    print("RAG 接口端到端测试")
    print("=" * 50)

    if not test_health():
        exit(1)

    # 创建知识库
    kid = test_create_knowledge()
    if kid < 0:
        print("知识库创建失败，终止测试")
        exit(1)

    test_query_knowledge(kid)

    # 上传文档
    did = test_upload_document(kid)
    if did > 0:
        test_query_document(did)
        print("\n等待 8 秒，让后台解析完成...")
        time.sleep(8)

    # AI 能力测试
    test_embedding()
    test_rerank()

    if did > 0:
        test_chat(kid)

    # 清理
    print("\n--- 清理 ---")
    if did > 0:
        test_delete_document(did)
    test_delete_knowledge(kid)

    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)
