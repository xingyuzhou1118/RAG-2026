```markdown
# RAG 知识库问答系统

基于 RAG（Retrieval-Augmented Generation）的本地知识库问答系统，支持 PDF / Word 文档上传、混合检索（BM25 + 向量语义）、BGE-Reranker 重排序，以及引用溯源展示。

## 技术栈

| 模块 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| 数据库 | SQLite（元数据）+ Elasticsearch（文档索引） |
| 检索算法 | BM25 关键词匹配 + BGE 向量语义检索 + RRF 融合 |
| 重排序 | BGE-Reranker-Base |
| 嵌入模型 | BGE-Small-Zh-V1.5 |
| 文档解析 | pdfplumber（PDF）+ python-docx / win32com（Word） |
| 前端 | 原生 HTML / CSS / JavaScript |

## 功能特性

- 知识库管理：创建 / 删除知识库
- 文档上传：支持 PDF（.pdf）和 Word（.doc / .docx）
- 文档解析：自动提取文本、分块、向量化存入 ES
- RAG 问答：混合检索 + Reranker 重排序 + 流式输出
- 引用溯源：回答中角标标注来源，点击展示原文片段

## 项目结构

```
RAG-2026/
├── main.py               # FastAPI 主入口，路由定义
├── rag_api.py            # RAG 核心逻辑（检索、重排、文档解析）
├── db_api.py             # SQLite 数据库操作
├── es_api.py             # Elasticsearch 索引管理
├── router_schema.py      # Pydantic 请求/响应模型
├── config.yaml           # ES 连接、模型参数配置
├── static/
│   └── index.html        # 前端界面
├── test/                 # 测试脚本
│   ├── test_api.py
│   ├── test_db.py
│   ├── test_es.py
│   └── test_upload_only.py
└── upload_files/         # 上传文档存放目录（运行过程中生成）
```

## 快速开始

### 环境要求

- Python 3.10+
- Elasticsearch 8.x（本地运行）
- Windows 环境（Word 解析需 Microsoft Word）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

1. 复制环境变量模板并填写：

```bash
cp .env.example .env
```

2. 编辑 `config.yaml`，配置 Elasticsearch 连接地址等参数。

### 启动

1. 启动 Elasticsearch 服务
2. 启动 FastAPI：

```bash
uvicorn main:app --reload --port 8000
```

3. 打开浏览器访问 `http://127.0.0.1:8000`

### 使用流程

1. 创建知识库
2. 上传 PDF / Word 文档（后台自动解析索引）
3. 选择知识库，开始问答

## API 接口概览

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/v1/knowledge_database` | 创建知识库 |
| `GET` | `/v1/knowledge_databases` | 查询知识库列表 |
| `DELETE` | `/v1/knowledge_database` | 删除知识库 |
| `POST` | `/v1/knowledge_document` | 上传文档 |
| `GET` | `/v1/knowledge_documents` | 查询文档列表 |
| `DELETE` | `/v1/knowledge_document` | 删除文档 |
| `POST` | `/v1/chat` | RAG 对话（流式） |

## License

MIT
```
