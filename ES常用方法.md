老板，下面是一份可直接查阅的手册。

---

## 一、ES 常用字段类型及 Mapping 参数

```python
from elasticsearch import Elasticsearch

# 客户端实例化（项目中 es 对象 = Elasticsearch(...)，已在 es_api.py 中完成）
# 之后所有操作均以 es.xxx() 方式调用
```

### Mapping 参数表

Mapping 相当于 SQL 的建表语句（DDL），用来定义索引中每个字段的类型和属性。

| 参数 | 类型 | 适用字段 | 说明 |
|------|------|:---:|------|
| `type` | str | 全部 | 字段数据类型，如 `text` / `keyword` / `dense_vector` / `long` / `float` / `boolean` / `date` 等 |
| `analyzer` | str | `text` | 索引时使用的分词器，项目中用 `ik_max_word`（细粒度分词） |
| `search_analyzer` | str | `text` | 搜索时使用的分词器，项目中用 `ik_smart`（粗粒度分词），降低召回噪音 |
| `dims` | int | `dense_vector` | 向量维度，必须与所选用 embedding 模型输出维度一致（如 bge 模型 512 维） |
| `element_type` | str | `dense_vector` | 向量元素类型，通常为 `float` |
| `index` | bool | `dense_vector` | 是否为向量字段建索引。设为 `True` 才能做 kNN 检索 |
| `index_options` | dict | `dense_vector` | 向量索引配置，项目中用 `{"type": "int8_hnsw"}` 开启内存优化 + HNSW 图索引 |

### 参数对比示例

```python
# 最简：text 字段，不指定分词器（使用 ES 默认 standard 分词）
"simple_field": {"type": "text"}

# 中文文本字段（推荐：索引细分词 + 搜索粗分词）
"file_name": {
    "type": "text",
    "analyzer": "ik_max_word",
    "search_analyzer": "ik_smart"
}

# 密集向量字段（用于语义/向量检索）
"chunk_embedding": {
    "type": "dense_vector",
    "element_type": "float",
    "dims": 512,              # 必须与模型输出维度一致
    "index": True,
    "index_options": {
        "type": "int8_hnsw"   # int8 量化压缩，减少内存占用
    }
}

# keyword 字段（不分词，适合精确匹配：ID、路径、分类名）
"document_id": {"type": "keyword"}

# long 整数字段
"page_number": {"type": "long"}

# boolean 字段
"is_active": {"type": "boolean"}

# date 字段
"create_time": {"type": "date"}
```

### 常用字段类型速查

| ES 类型 | 适用场景 | 是否分词 | 说明 |
|---------|---------|:---:|------|
| `text` | 正文、摘要、文件名（需全文搜索） | ✅ | 会被分词器切分后建立倒排索引 |
| `keyword` | 路径、ID、标签、状态码（精确匹配） | ❌ | 整体作为一个词项，不做分词 |
| `long` | 整数（页码、计数、ID） | ❌ | 64位有符号整数 |
| `integer` | 整数（小范围） | ❌ | 32位有符号整数 |
| `float` | 小数 | ❌ | 32位浮点数 |
| `double` | 高精度小数 | ❌ | 64位浮点数 |
| `boolean` | 是否标记 | ❌ | true / false |
| `date` | 日期时间 | ❌ | ISO 8601 格式或 Unix 时间戳 |
| `dense_vector` | embedding 向量 | — | 存储稠密向量，用于 kNN 语义检索 |
| `nested` | 对象数组（需独立查询） | — | 数组中的每个对象保留独立索引 |
| `object` | JSON 子对象 | — | 默认行为，内部字段会被扁平化 |

### 完整 Mapping 创建示例

```python
# 定义 Mapping
document_meta_mapping = {
    "mappings": {
        "properties": {
            "file_name": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart"
            },
            "abstract": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart"
            },
            "content": {
                "type": "text",
                "analyzer": "ik_max_word",
                "search_analyzer": "ik_smart"
            }
        }
    }
}

# 检查索引是否存在，不存在则创建
if not es.indices.exists(index="document_meta"):
    es.indices.create(index="document_meta", body=document_meta_mapping)
```

> **类比 SQL**：`es.indices.create()` ≈ `CREATE TABLE`；Mapping 中的 `properties` ≈ 列定义列表。

---

## 二、ES 增删查改完整操作

以下所有操作直接通过 `es` 对象调用，不需要事务或 session。

### 前置：检查连接状态

```python
from es_api import es

# 确认 ES 可连通
if not es.ping():
    raise ConnectionError("无法连接到 Elasticsearch")
```

---

### 1. 新增：插入文档（Create）

```python
# 插入一条文档 — es.index()
test_doc = {
    "file_path": "test_file.txt",
    "file_name": "test_file",
    "abstract": "This is a test abstract.",
    "content": "This is the full content of the test file."
}

response = es.index(index="document_meta", document=test_doc)
# response['result'] == 'created'  表示新增成功
# response['_id']                  返回 ES 自动生成的文档 ID

doc_id = response["_id"]
```

| 参数 | 说明 |
|------|------|
| `index` | 索引名（目标表） |
| `document` | 文档内容（dict），字段无需全部预先在 mapping 中定义，ES 会自动推断 |
| `id` | 可选，指定文档 ID。不指定则 ES 自动生成 |

> **类比 SQL**：`es.index(index="X", document=d)` ≈ `INSERT INTO X VALUES (d)`

**验证插入成功**：

```python
# es.exists() 检查指定 ID 的文档是否存在
assert es.exists(index="document_meta", id=doc_id)
```

---

### 2. 查询：全文检索 + 向量检索（Read）

#### 2.1 按 ID 获取单条 — es.get()

```python
doc = es.get(index="document_meta", id=doc_id)
# doc['_source'] 即文档原始内容
print(doc['_source']['file_name'])
```

| 参数 | 说明 |
|------|------|
| `index` | 索引名 |
| `id` | 文档 ID |

> **类比 SQL**：`es.get(index="X", id=ID)` ≈ `SELECT * FROM X WHERE id = ID`

#### 2.2 全文检索（match 查询）— es.search()

```python
# 按字段内容匹配（会被分词器分词后检索）
search_response = es.search(
    index="document_meta",
    query={
        "match": {
            "file_name": "query_test_file"
        }
    }
)

# 结果结构
total_hits = search_response['hits']['total']['value']   # 命中总数
hits = search_response['hits']['hits']                    # 文档列表

for hit in hits:
    doc = hit['_source']      # 文档内容
    score = hit['_score']     # 相关性得分（BM25）
    doc_id = hit['_id']       # 文档 ID
```

| 参数 | 说明 |
|------|------|
| `index` | 索引名 |
| `query` | 查询体。`{"match": {"字段名": "搜索词"}}` 为最常见的全文匹配 |
| `size` | 可选，返回条数上限，默认 10 |
| `from` | 可选，分页偏移量，默认 0 |
| `_source` | 可选，指定返回哪些字段，如 `["file_name"]` |

> **match vs match_phrase**：`match` 分词后 OR 匹配；`match_phrase` 要求词序连续、位置相邻，类似 "包含完整短语"。

> **类比 SQL**：`es.search(query={"match": ...})` ≈ `SELECT * FROM X WHERE field LIKE '%关键词%'`（但走倒排索引，性能远优于 LIKE）

#### 2.3 kNN 向量检索 — es.search(knn=...)

kNN（k-Nearest Neighbor）检索基于向量相似度（余弦/欧氏距离），用于语义搜索而非关键词匹配。

```python
# 构建 kNN 查询体
knn_query = {
    "field": "chunk_embedding",          # 向量字段名
    "query_vector": query_embedding,     # 查询向量（与 dims 长度一致）
    "k": 5,                              # 返回 Top-K 条最相似结果
    "num_candidates": 10                 # HNSW 召回候选集大小
}

vector_search_response = es.search(
    index="chunk_info",
    knn=knn_query
)

# 结果格式与 match 查询一致
for hit in vector_search_response['hits']['hits']:
    print(hit['_source']['chunk_content'], hit['_score'])
```

**kNN 参数详解**：

| 参数 | 必需 | 默认值 | 说明 |
|------|:---:|:---:|------|
| `field` | ✅ | — | 向量字段名，必须是 `dense_vector` 类型且 `index: True` |
| `query_vector` | ✅ | — | 查询向量（list[float]），长度必须与 mapping 中 `dims` 严格一致 |
| `k` | ✅ | — | 返回的最相似结果数量，即 Top-K |
| `num_candidates` | ✅ | — | 从 HNSW 图中召回的候选节点数。**必须 >= k**；越大召回率越高但更慢。经验值：`k * 1.5 ~ k * 3`（项目中 k=5 时 dist_candidates=10） |
| `filter` | ❌ | None | 可选，对候选集按字段条件过滤（如 `{"term": {"category": "法规"}}`），实现"向量+条件"混合过滤 |
| `similarity` | ❌ | `cosine` | 相似度度量，可选 `cosine` / `l2_norm` / `dot_product` |

> **类比 SQL**：无直接等价。kNN ≈ "找出 embedding 向量最接近的 K 行"，传统 SQL 无法原生表达，属于语义级相似度检索。

> **注意**：`knn` 查询中 `_score` 的语义与 BM25 不同——它表示向量相似度（余弦相似度越接近 1 越相似），不能与 match 查询的 BM25 分数直接比较。

---

### 3. 修改：更新文档（Update）

```python
# es.update() 按 ID 局部更新字段
es.update(
    index="document_meta",
    id=doc_id,
    doc={
        "abstract": "This is the updated abstract.",
        "content": "This is the updated content."
    }
)
# doc 参数中只需写要更新的字段，未提及的字段保持不变
```

| 参数 | 说明 |
|------|------|
| `index` | 索引名 |
| `id` | 要更新的文档 ID |
| `doc` | 要更新的字段 dict（**局部更新**，只更新指定字段） |

> **类比 SQL**：`es.update(index="X", id=ID, doc={...})` ≈ `UPDATE X SET ... WHERE id = ID`

**注意**：ES 内部实现是"标记旧文档删除 + 插入新文档"，不是原地修改。

---

### 4. 删除（Delete）

```python
# 按 ID 删除单条
es.delete(index="document_meta", id=doc_id)
```

| 参数 | 说明 |
|------|------|
| `index` | 索引名 |
| `id` | 要删除的文档 ID |

> **类比 SQL**：`es.delete(index="X", id=ID)` ≈ `DELETE FROM X WHERE id = ID`

---

### 5. 索引管理

```python
# 检查索引是否存在
es.indices.exists(index="document_meta")     # → True / False

# 创建索引（带 Mapping）
es.indices.create(index="document_meta", body=mapping_body)

# 删除整个索引（危险操作）
es.indices.delete(index="document_meta")
```

| 操作 | 类比 SQL |
|------|---------|
| `es.indices.create(index="X")` | `CREATE TABLE X` |
| `es.indices.exists(index="X")` | 查系统表 `information_schema.tables` |
| `es.indices.delete(index="X")` | `DROP TABLE X` |

---

### 6. 异常处理完整写法

```python
try:
    response = es.index(index="document_meta", document=test_doc)
    if response['result'] != 'created':
        raise RuntimeError(f"写入异常: {response['result']}")
except Exception as e:
    print(f"操作失败：{e}")
    raise
```

> ES 没有事务回滚概念（每个文档操作是独立的原子操作）。如果需要批量的原子性，使用 `bulk` API + `_bulk` endpoint。

---

## 快速参考卡片

```
连接检查：es.ping()                                → True / False
索引存在：es.indices.exists(index="X")
创建索引：es.indices.create(index="X", body=mapping)
删除索引：es.indices.delete(index="X")

增：es.index(index="X", document={...})            → 返回 _id
查：es.get(index="X", id=ID)                       → 返回 _source
   es.search(index="X", query={"match":...})       → 全文检索
   es.search(index="X", knn={...})                 → 向量语义检索
   es.exists(index="X", id=ID)                     → True/False
改：es.update(index="X", id=ID, doc={...})         → 局部更新
删：es.delete(index="X", id=ID)                    → 按 ID 删除

核心规则：
  1. 所有操作直接通过 es.xxx() 调用，无需 session
  2. Mapping 可在创建索引时定义，也可不定义由 ES 自动推断
  3. 中文检索务必配置 ik_max_word（索引）+ ik_smart（搜索）
  4. kNN 中 num_candidates 必须 >= k，建议取 k × 2
  5. 单条文档操作是原子的，批量操作用 bulk API
```
