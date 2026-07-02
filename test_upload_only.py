"""最小上传测试，打印完整响应"""
import requests

resp = requests.post("http://localhost:6010/v1/knowledge_document",
    data={
        "knowledge_id": "5",
        "title": "测试",
        "category": "测试"
    },
    files={"file": ("test.pdf", open(r"E:\PythonTest\RAG\upload_files\document_id_2_物业费知识手册.pdf", "rb"), "application/pdf")}
)
print(f"status_code: {resp.status_code}")
print(f"headers: {dict(resp.headers)}")
print(f"body: {resp.text[:500]}")
