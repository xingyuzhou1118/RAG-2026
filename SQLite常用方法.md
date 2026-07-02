老板，下面是一份可直接查阅的手册。

---

## 一、Column 完整常用参数

```python
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, Text
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|:---:|------|
| `primary_key` | bool | False | 是否主键。一张表只能有一个主键（或一个复合主键） |
| `autoincrement` | bool | True（主键且整数时） | 是否自动递增。仅对 `Integer` 主键有效 |
| `default` | 值/函数 | None | 插入时，如果代码没传值，自动填入的值。**注意传函数引用，不要传函数调用** |
| `onupdate` | 函数 | None | 更新时，自动刷新为函数返回值 |
| `nullable` | bool | True | 是否允许 NULL。设为 False 则该字段必须有值 |
| `unique` | bool | False | 是否唯一约束。重复插入会报错 |
| `index` | bool | False | 是否为该字段单独建索引（加速查询） |
| `comment` | str | None | 字段注释（MySQL 支持，SQLite 忽略） |
| `server_default` | str | None | 数据库层面的默认值，如 `server_default="CURRENT_TIMESTAMP"` |

### 参数对比示例

```python
# 最简：只指定类型
title = Column(String)

# 主键 + 自增
knowledge_id = Column(Integer, primary_key=True, autoincrement=True)

# 默认值传函数引用（正确）
create_dt = Column(DateTime, default=datetime.utcnow)        # ✅ 每次调用都取新时间

# 默认值传函数调用（错误）
create_dt = Column(DateTime, default=datetime.utcnow())     # ❌ 所有记录同一个时间

# 创建 + 更新双时间戳
create_dt = Column(DateTime, default=datetime.utcnow)              # 创建时写一次
update_dt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 每次更新刷新

# 不允许为空
email = Column(String, nullable=False)

# 唯一
username = Column(String, unique=True)

# 建索引（适合经常作为查询条件的字段）
knowledge_id = Column(Integer, index=True)

# 数据库层面默认值
create_time = Column(DateTime, server_default="CURRENT_TIMESTAMP")
```

### 常用字段类型速查

| Column 类型 | Python 对应 | SQLite 存储 | 说明 |
|------------|:---:|-----------|------|
| `Integer` | int | INTEGER | 整数 |
| `BigInteger` | int | INTEGER | 大整数 |
| `String` | str | TEXT | 不限长字符串 |
| `String(200)` | str | TEXT | 限长200字符（SQLite 不强制，MySQL 强制） |
| `Text` | str | TEXT | 大段文本（语义上区别于短字符串） |
| `Float` | float | REAL | 浮点数 |
| `Boolean` | bool | INTEGER(0/1) | 布尔值 |
| `DateTime` | datetime | TEXT(ISO格式) | 日期时间 |
| `Date` | date | TEXT | 日期 |
| `Time` | time | TEXT | 时间 |
| `LargeBinary` | bytes | BLOB | 二进制数据 |

---

## 二、增删查改完整操作

以下所有操作必须写在 `with Session() as session:` 上下文里。

### 前置：创建会话

```python
from db_api import Session, KnowledgeDatabase, KnowledgeDocument

with Session() as session:
    # 所有操作写在这里
    # ...
    session.commit()   # 写操作必须 commit
```

---

### 1. 新增（Create）

```python
# 方式一：创建对象 → add → commit
with Session() as session:
    kb = KnowledgeDatabase(
        title="物业费知识库",
        category="政策法规"
    )
    session.add(kb)
    session.commit()
    # commit 后 kb.knowledge_id 自动回填了数据库生成的 ID

# 方式二：add_all 批量新增
with Session() as session:
    kb1 = KnowledgeDatabase(title="知识库A", category="法规")
    kb2 = KnowledgeDatabase(title="知识库B", category="指南")
    session.add_all([kb1, kb2])
    session.commit()

# 方式三：需要立即拿到自增ID但暂不提交
with Session() as session:
    kb = KnowledgeDatabase(title="测试", category="测试")
    session.add(kb)
    session.flush()                    # flush：发 SQL 但不提交
    new_id = kb.knowledge_id           # 此时可以拿到ID
    # ... 做其他事 ...
    session.commit()                   # 最后统一提交
```

---

### 2. 查询（Read）

```python
# ---- 查单条 ----

# 按主键查
record = session.query(KnowledgeDatabase).get(1)

# 按条件查第一条
record = session.query(KnowledgeDatabase).filter(
    KnowledgeDatabase.title == "物业费知识库"
).first()

# 更复杂的条件
from sqlalchemy import and_, or_

record = session.query(KnowledgeDatabase).filter(
    and_(
        KnowledgeDatabase.category == "政策法规",
        KnowledgeDatabase.title.like("%物业%")   # like 模糊匹配
    )
).first()

# ---- 查多条 ----

# 查所有
records = session.query(KnowledgeDatabase).all()

# 按条件查多条
records = session.query(KnowledgeDatabase).filter(
    KnowledgeDatabase.category == "政策法规"
).all()

# 限制数量
records = session.query(KnowledgeDatabase).limit(10).all()

# 偏移分页（第2页，每页10条）
records = session.query(KnowledgeDatabase).offset(10).limit(10).all()

# 排序（按创建时间倒序）
records = session.query(KnowledgeDatabase).order_by(
    KnowledgeDatabase.create_dt.desc()
).all()

# ---- 统计 ----

# 计数
count = session.query(KnowledgeDatabase).filter(
    KnowledgeDatabase.category == "政策法规"
).count()

# ---- 只取部分字段 ----

# 只取 title 和 category
results = session.query(
    KnowledgeDatabase.title,
    KnowledgeDatabase.category
).all()
# 返回列表: [("物业费知识库", "政策法规"), ("个税知识库", "政策法规")]
```

### 常用过滤条件

| 写法 | SQL 等价 | 说明 |
|------|---------|------|
| `.filter(Table.field == value)` | `WHERE field = value` | 等于 |
| `.filter(Table.field != value)` | `WHERE field != value` | 不等于 |
| `.filter(Table.field > value)` | `WHERE field > value` | 大于 |
| `.filter(Table.field.in_([a, b]))` | `WHERE field IN (a, b)` | 在列表中 |
| `.filter(Table.field.like("%关键词%"))` | `WHERE field LIKE '%关键词%'` | 模糊匹配 |
| `.filter(Table.field.is_(None))` | `WHERE field IS NULL` | 为空 |
| `.filter(Table.field.isnot(None))` | `WHERE field IS NOT NULL` | 不为空 |
| `and_(条件1, 条件2)` | `WHERE 条件1 AND 条件2` | 且 |
| `or_(条件1, 条件2)` | `WHERE 条件1 OR 条件2` | 或 |

---

### 3. 修改（Update）

```python
# 方式一：查出来 → 改属性 → commit（推荐）
with Session() as session:
    record = session.query(KnowledgeDatabase).filter(
        KnowledgeDatabase.knowledge_id == 1
    ).first()
    if record:
        record.title = "修改后的标题"
        record.category = "新分类"
        session.commit()   # SQLAlchemy 自动感知属性变化，生成 UPDATE 语句

# 方式二：批量更新（不需要先查出来）
with Session() as session:
    session.query(KnowledgeDatabase).filter(
        KnowledgeDatabase.category == "旧分类"
    ).update({"category": "新分类"})
    session.commit()
```

---

### 4. 删除（Delete）

```python
# 方式一：查出来 → delete → commit
with Session() as session:
    record = session.query(KnowledgeDatabase).filter(
        KnowledgeDatabase.knowledge_id == 1
    ).first()
    if record:
        session.delete(record)
        session.commit()

# 方式二：批量删除
with Session() as session:
    session.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_id == 1
    ).delete()
    session.commit()
```

---

### 5. 异常处理完整写法

```python
from sqlalchemy.exc import SQLAlchemyError

with Session() as session:
    try:
        kb = KnowledgeDatabase(title="测试", category="测试")
        session.add(kb)
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()    # 回滚事务
        print(f"操作失败：{e}")
```

---

### 6. 关联查询（利用你已定义的 relationship）

```python
# KnowledgeDatabase.documents 已经定义好了
with Session() as session:
    kb = session.query(KnowledgeDatabase).filter(
        KnowledgeDatabase.knowledge_id == 1
    ).first()

    # 直接 .documents 拿文档列表（自动执行 SELECT ... WHERE knowledge_id = 1）
    for doc in kb.documents:
        print(doc.title, doc.file_path)

# 反向：从文档查它属于哪个知识库
with Session() as session:
    doc = session.query(KnowledgeDocument).filter(
        KnowledgeDocument.document_id == 101
    ).first()
    print(doc.knowledge.title)   # 直接取到知识库名称
```

---

## 快速参考卡片

```
增：session.add(obj)           → session.commit()
删：session.delete(obj)         → session.commit()
改：obj.属性 = 新值              → session.commit()
查：session.query(类).filter(条件).first() / .all()

核心规则：
  1. 一切操作包裹在 with Session() as session: 里
  2. 写操作（增删改）必须 commit
  3. 读操作不需要 commit
  4. 出错要 rollback
```