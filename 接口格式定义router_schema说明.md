
## 概念对照（用餐厅类比）

> 你去餐厅吃饭：拿起菜单（接口文档）→ 告诉服务员你要什么（Request 格式）→ 厨房做完端上来（Response 格式）

| 餐厅 | 项目中 | 你写的文件 |
|------|--------|-----------|
| 菜单 | API 接口文档 | Swagger 自动生成 |
| 你点的菜 | Request 模型 | `XXXRequest` 类 |
| 端上来的菜 | Response 模型 | `XXXResponse` 类 |
| 服务员 | 路由函数 | `main.py` 里的函数 |

---

## 具体场景：一条完整链路

假设你要做一个"上传政府 PDF 文件，然后向它提问"的功能。

### 第 1 步：创建知识库

前端发一个 HTTP 请求：

```
POST http://localhost:6010/v1/knowledge_base
Content-Type: application/json

{
    "category": "税务法规",
    "title": "个人所得税知识库"
}
```

这条 JSON 到达后端后，FastAPI 拿着 `KnowledgeRequest` 去校验——`category` 是字符串吗？`title` 是字符串吗？少传了会直接报 422 错误。

处理后，后端返回：

```json
{
    "request_id": "a1b2c3d4-...",
    "knowledge_id": 1,
    "category": "税务法规",
    "title": "个人所得税知识库",
    "response_code": 200,
    "response_msg": "知识库插入成功",
    "process_status": "completed",
    "process_time": 0.023
}
```

这个 JSON 的格式，就是 `KnowledgeResponse` 类定义的。前端拿到后，看 `response_code` 判断成功，用 `knowledge_id: 1` 做后续操作。

### 第 2 步：上传文档到知识库 1

前端发的是 **表单格式**（因为有文件），不是 JSON：

```
POST http://localhost:6010/v1/document
Content-Type: multipart/form-data

knowledge_id: 1
title: "个人所得税法实施细则"
category: "政策文件"
file: [选择一个 .pdf 文件]
```

为什么 `DocumentRequest` 里每个字段都要用 `Annotated[str, Form()]`？**因为文件上传必须用表单格式传**，不能用 JSON body。`Form()` 就是在告诉 FastAPI："这几个参数从表单字段里取，别去 JSON 里找"。

`File(...)` 里的三个点表示**必传**。如果前端不传文件，FastAPI 直接返回 422。

后端返回：

```json
{
    "request_id": "e5f6g7h8-...",
    "document_id": 5,
    "category": "政策文件",
    "title": "个人所得税法实施细则",
    "knowledge_id": 1,
    "file_type": "application/pdf",
    "response_code": 200,
    "response_msg": "文档添加成功",
    "process_status": "completed",
    "process_time": 0.156
}
```

后端在后台异步解析这个 PDF（切 chunk、编码向量、存入 ES），前端可以先拿 `document_id: 5` 做查询。

### 第 3 步：向知识库提问（RAG 对话）

上传完文档、后台解析完成后，前端发：

```
POST http://localhost:6010/chat
Content-Type: application/json

{
    "knowledge_id": 1,
    "message": [
        {"role": "user", "content": "个人所得税的起征点是多少？"}
    ]
}
```

`RAGRequest` 里 `message: List[Dict]` —— 这是标准的 OpenAI 对话格式，一个列表，每个元素有 `role` 和 `content`。

后端走完整 RAG 链路：检索相关 chunk → 拼装 prompt → 调 LLM 生成答案，然后返回：

```json
{
    "request_id": "i9j0k1l2-...",
    "message": [
        {"role": "user", "content": "个人所得税的起征点是多少？"},
        {"role": "system", "content": "根据《个人所得税法》，起征点为每月5000元……"}
    ],
    "response_code": 200,
    "response_msg": "ok",
    "process_status": "completed",
    "process_time": 1.234
}
```

注意返回的 `message` 列表里多了 `system` 角色的回答——这就是 RAG 生成的答案。

### 第 4 步：追问（多轮对话）

用户继续问："那专项附加扣除有哪些？"

前端把**整个历史消息列表**发回去：

```json
{
    "knowledge_id": 1,
    "message": [
        {"role": "user", "content": "个人所得税的起征点是多少？"},
        {"role": "system", "content": "根据《个人所得税法》，起征点为……"},
        {"role": "user", "content": "那专项附加扣除有哪些？"}
    ]
}
```

后端看到 `message` 长度 > 1，就不会再走检索了，直接把整个对话历史丢给 LLM 回答（这是 `chat_with_rag` 里的逻辑）。

---

## Embedding 和 Rerank 接口是什么用的

这两个接口**不是给最终用户用的，是给开发者调试或被前端的高级功能调用**。

| 接口 | 前端传什么 | 后端返回什么 | 使用场景 |
|------|-----------|-------------|---------|
| `/v1/embedding` | `{"text": "个税起征点", "token": "xxx", "model": "bge"}` | 一个 512 维的浮点数数组（向量） | 调试编码效果；或前端自己做语义搜索 |
| `/v1/rerank` | `{"text_pair": [["查询", "文档片段1"], ["查询", "文档片段2"]], ...}` | 每个文本对的相似度分数数组 | 调试重排序效果；验证检索质量 |

---

## 一句话总结

你写的这些 Pydantic 类，就是**前端和后端之间的合同**：

- `Request` 规定了前端**必须怎么传数据**（传什么字段、什么类型）
- `Response` 规定了后端**会怎么回数据**（返回什么字段、什么类型）
- `main.py` 里的路由函数就是**执行这个合同的"服务员"**，拿着 Request 去调用业务逻辑，然后把结果装进 Response 返回

下一步就是去 `main.py` 里写这些路由函数——这才是接口真正"活起来"的地方。