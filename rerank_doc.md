---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 9aeb587c3ff78188ec6676c8e9ef1fda_fd6f65ed710d11f1b2f55254006c9bbf
    ReservedCode1: JVQB4JzVoWbKa61v41v6S5/SZLqkBx4c30sI/HqEOKZUKO6ZfCuyGZSoip3qUb7+Fhz3meRndYscHXqHDjKCcUTeda5jykSKqYRGEKsinTpYCjwe5Zo3akF88zyYMzxF0d9JTr+dfaPC/c46EpIajRwxgDiSvXZ/0d1j37Tsl2JUosuvBj3NtnwBwj4=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 9aeb587c3ff78188ec6676c8e9ef1fda_fd6f65ed710d11f1b2f55254006c9bbf
    ReservedCode2: JVQB4JzVoWbKa61v41v6S5/SZLqkBx4c30sI/HqEOKZUKO6ZfCuyGZSoip3qUb7+Fhz3meRndYscHXqHDjKCcUTeda5jykSKqYRGEKsinTpYCjwe5Zo3akF88zyYMzxF0d9JTr+dfaPC/c46EpIajRwxgDiSvXZ/0d1j37Tsl2JUosuvBj3NtnwBwj4=
---

# BGE-Reranker 重排序模型打分机制详解

## 1. 在 RAG 流程中的位置

```
用户提问
  │
  ├── 阶段一：粗筛（Recall）→ BM25 + 向量检索 → RRF 融合 → 取前 N 条候选
  │
  └── 阶段二：精排（Rerank）→ BGE-Reranker 对 N 条候选重新打分排序
```

粗筛阶段追求"快"——从百万级 chunk 中捞出几十条。精排阶段追求"准"——对这几十条逐一细看，把真正最相关的排在前面。

---

## 2. Cross-Encoder 架构

### 2.1 与 Bi-Encoder 的本质区别

BGE-Reranker 是一个 **Cross-Encoder** 模型，和粗筛阶段用的 SentenceTransformer（Bi-Encoder）架构完全不同。

| 维度 | Bi-Encoder（编码阶段） | Cross-Encoder（重排阶段） |
|------|------------------------|---------------------------|
| 输入方式 | 分别编码：`encode("查询")` 和 `encode("候选")` | 成对输入：`model(["查询", "候选段落"])` |
| 信息交互 | 两个向量只在最后的余弦距离计算时才"见面" | 查询和候选从模型第一层起全程交叉关注 |
| 精度 | 较低（交互晚、信息少） | 高（全程交叉注意力） |
| 速度 | 快（候选向量可预存，查询时只算一次） | 慢（每对 (query, chunk) 都要完整过模型） |
| 适用规模 | 百万级 | 几十条 |

### 2.2 Cross-Encoder 内部结构

```
输入：["人均收入增长", "2024年居民人均可支配收入41314元..."]

          ┌─────────────────────────────────────┐
          │           Token Embedding            │
          │  [CLS] 查询token... [SEP] 候选token... [SEP] │
          └────────────┬────────────────────────┘
                       │
          ┌────────────▼────────────────────────┐
          │     Transformer Encoder Layer 1      │
          │   ┌─────────────────────────────┐   │
          │   │  Self-Attention（12 头）     │   │
          │   │  "增长" ←→ "41314元"        │   │
          │   │  "可支配" ←→ "收入"         │   │
          │   │  "人均" ←→ "居民"           │   │
          │   └─────────────────────────────┘   │
          │           前馈网络 + LayerNorm       │
          └────────────┬────────────────────────┘
                       │
                       │  × 12 层重复
                       │
          ┌────────────▼────────────────────────┐
          │           Linear Classifier          │
          │  取 [CLS] token 的向量 → 全连接 → 输出一个分数    │
          └─────────────────────────────────────┘

输出：4.87（一个浮点数，表示查询与候选的匹配程度）
```

关键点：
- 查询和候选**拼接成一条序列**，用 `[SEP]` 分隔
- Self-Attention 让"增长"这个词不仅能关注自己的上下文，还能直接关注候选段落中的"41314元"
- 取 `[CLS]` token（序列第一个特殊token）的输出向量，过一个线性分类器输出一个分数

---

## 3. 打分机制

### 3.1 训练目标

BGE-Reranker 在训练时使用的是**正负样本对**的对比学习：

```
正样本（相关）：["人均收入增长", "2024年可支配收入41314元增长5.3%"]  → 期望高分
负样本（不相关）：["人均收入增长", "今天天气不错适合出去玩"]          → 期望低分
```

损失函数的目标：**拉大正负样本的分数差距**。

### 3.2 分数范围与含义

输出的分数**没有固定上下界**（不像余弦相似度在 -1 到 1 之间），可以出现正值、负值、甚至大于 10 的值。

| 分数范围 | 含义 |
|---------|------|
| > 3.0 | 高度相关，候选段落直接回答查询 |
| 0 ~ 3.0 | 部分相关，话题沾边但不是直接答案 |
| < 0 | 不相关或弱相关 |

### 3.3 打分示例

假设查询为"人均收入增长"，候选列表经过 BGE-Reranker 打分：

```
查询：人均收入增长

候选1：2024年居民人均可支配收入41314元，同比名义增长5.3%
  → Cross-Encoder 内部：Self-Attention 让 "增长" ↔ "41314元" 直接交互
  → 分数：4.87  ✅ 高度相关，排第一

候选2：GDP增长反映经济总量变化，不直接反映居民收入
  → Self-Attention： "增长" ↔ "GDP" + "收入" ↔ "居民"
  → 分数：1.23  ⚠️ 部分相关，排中间

候选3：隔壁老王今天买了两斤苹果
  → Self-Attention：没有任何匹配点
  → 分数：-8.92  ❌ 不相关，排最后
```

---

## 4. 项目中 BGE-Reranker 的调用链路

### 4.1 模型加载（`load_rerank_model`）

```python
def load_rerank_model(model_name: str, model_path: str) -> None:
    global EMBEDDING_MODEL_PARAMS
    if model_name in ["bge-reranker-base"]:
        # 加载 Cross-Encoder 模型本体
        EMBEDDING_MODEL_PARAMS["rerank_model"] = AutoModelForSequenceClassification.from_pretrained(model_path)
        # 加载对应的分词器
        EMBEDDING_MODEL_PARAMS["rerank_tokenizer"] = AutoTokenizer.from_pretrained(model_path)
        # 切换到推理模式（关闭 Dropout 等训练特性）
        EMBEDDING_MODEL_PARAMS["rerank_model"].eval()
        # 模型移到 CPU 或 GPU
        EMBEDDING_MODEL_PARAMS["rerank_model"].to(device)
```

### 4.2 推理调用（`get_rerank`）

```python
def get_rerank(self, text_pair) -> np.ndarray:
    if self.rerank_model in ["bge-reranker-base"]:
        with torch.no_grad():  # 关闭梯度计算，节省显存
            # Step 1：分词——将文字对转成 token ID 和 attention mask
            inputs = EMBEDDING_MODEL_PARAMS["rerank_tokenizer"](
                text_pair,                        # [["查询", "候选1"], ["查询", "候选2"], ...]
                padding=True,                    # 同一批次补齐到相同长度
                truncation=True,                 # 超长截断
                return_tensors='pt',             # 返回 PyTorch 张量
                max_length=512,                  # 最大 token 数
            )
            # Step 2：移到目标设备
            inputs = {key: value.to(device) for key, value in inputs.items()}
            # Step 3：模型前向推理
            scores = EMBEDDING_MODEL_PARAMS["rerank_model"](
                **inputs,
                return_dict=True
            ).logits.view(-1,).float()

            # Step 4：转成 NumPy 返回
            scores = scores.data.cpu().numpy()
            return scores
    raise NotImplemented
```

### 4.3 在 RAG 流程中调用（`query_document` 末尾）

```python
if self.use_rerank:
    # 构建 (查询, 候选) 对列表
    text_pair = []
    for chunk_content in sorted_content:
        text_pair.append([query, chunk_content])

    # 批量推理，一次拿到所有匹配分
    rerank_score = self.get_rerank(text_pair)

    # 按分数从高到低排序
    rerank_idx = np.argsort(rerank_score)[::-1]

    # 重排记录和内容
    sorted_records = [sorted_records[x] for x in rerank_idx]
    sorted_content = [sorted_content[x] for x in rerank_idx]
```

---

## 5. Bi-Encoder 与 Cross-Encoder 的协作流水线

```
百万级 chunk 库
    │
    ▼
┌─────────────────────────────────┐
│  Bi-Encoder（粗筛）             │
│  - 查询向量 vs 所有 chunk 向量  │
│  - 毫秒级返回 top-50           │
│  - 可能漏掉少量相关结果        │
└──────────────┬──────────────────┘
               │ 50 条候选
               ▼
┌─────────────────────────────────┐
│  RRF 融合                       │
│  - BM25 + 向量检索 两路合并    │
│  - 截取 top-N（如 10 条）      │
└──────────────┬──────────────────┘
               │ 10 条候选
               ▼
┌─────────────────────────────────┐
│  Cross-Encoder（精排）          │
│  - 逐对打分                     │
│  - 耗时可接受（10 条）          │
│  - 准确率显著提升               │
└──────────────┬──────────────────┘
               │ 重排后的 10 条
               ▼
          拼入 Prompt → LLM 生成
```

---

## 6. 总结

| 维度 | 说明 |
|------|------|
| 模型类型 | Cross-Encoder（序列分类模型） |
| 核心机制 | 将查询与候选拼接后，通过 Transformer 的 Self-Attention 进行深层语义交互 |
| 输入格式 | `[CLS] query [SEP] candidate [SEP]`，token 数 ≤ 512 |
| 输出格式 | 单个浮点分数，无固定范围 |
| 与 Bi-Encoder 关系 | Bi-Encoder 负责粗筛（速度优先），Cross-Encoder 负责精排（精度优先），两者是互补流水线 |
| 项目中的开关 | `config.yaml` 中 `use_rerank: true/false` 控制是否启用 |

