from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship , sessionmaker
from datetime import datetime, timezone

import yaml #type: ignore
with open("config.yaml","r") as file:
    config = yaml.safe_load(file)
db_config = config['database']
db_type = db_config['engine']

if db_type == "sqlite":
    # SQLite 使用文件路径
    db_path = db_config.get('path',"rag.db")
    engine = create_engine(f"sqlite:///{db_path}",echo = True)
    #创建数据库引擎，不连接
else:
    # MySQL 或 其他数据库使用 host，port，username，password, database
    host = db_config.get('host',default = "localhost")
    port = db_config.get('port',default = 3306)
    username = db_config.get('username',default = "root")
    password = db_config.get('password',default = "123456")
    database = db_config.get('database',default = "mydb") #MySQL还需要指定数据库名

    engine = create_engine(f"{db_type}://{username}:{password}@{host}:{port}/{database}",
    echo = True
    )

#创建 Base 类
Base = declarative_base() #基类，Base.metadata是一个"注册表"，记录了这个Base下所有继承类的表结构
# ORM
# 定义知识库表knowledge_database表
class KnowledgeDatabase(Base):
    __tablename__ = 'knowledge_database'
    knowledge_id = Column(Integer,primary_key = True,autoincrement = True) #主键 + ID自动递增
    title = Column(String) #知识库名称
    category = Column(String) #知识库分类 or 知识库类型
    create_dt = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # 创建时间
    update_dt = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))  # 更新时间

    #与知识库文档表KnowledgeDocument关联
    documents = relationship("KnowledgeDocument",back_populates = "knowledge")
    #与知识库文档表中名为knowledge的relationship关联

    def __str__(self):
        return (f"KnowledgeDatabase(knowledge_id = {self.knowledge_id},"
                f"title = '{self.title}',category = '{self.category}',"
                f"create_dt = {self.create_dt},"
                f"update_dt = {self.update_dt})")

#定义知识库文档表KnowledgeDocument表
class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    document_id = Column(Integer,primary_key = True,autoincrement = True) #文档ID 主键 + 自增
    title = Column(String) #文档名称
    category = Column(String) #文档分类 or 文档类型
    knowledge_id = Column(Integer,ForeignKey("knowledge_database.knowledge_id")) #关联知识库ID
    file_path = Column(String) #存储地址
    file_type = Column(String) #文件类型
    create_dt = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    update_dt = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                       onupdate=lambda: datetime.now(timezone.utc))

    #与知识库表KnowledgeDatabase关联
    knowledge = relationship("KnowledgeDatabase",back_populates = "documents")
    #与知识库表中名为documents的relationship关联

#create_all一键建表，Base.metadata 里记录了所有继承 Base 的类
Base.metadata.create_all(engine)
Session = sessionmaker(bind = engine)
#创建会话工厂类，每次需要操作数据库时，从会话工厂类创建一个会话对象，进行增删查改的操作

"""
文件            角色         负责的任务
db_api.py	关系库接线员	 Session（会话工厂）+ KnowledgeDatabase KnowledgeDocument 两个 ORM 类
es_api.py	搜索库接线员	 全局 es 客户端对象 + 自动建好 document_meta / chunk_info 两个索引

db_api 对外提供Session 以及 两个ORM类(预先定义好的数据库表和字段)
from db_api import Session, KnowledgeDatabase, KnowledgeDocument

es_api 对外提供创建好的es客户端对象，里面已经建好了两个索引(表) document_meta 和 chunk_info 
from es_api import es
总结来说数据层的两个文件 db_api 和 es_api 就是负责将数据存储需要的表和字段定义好
db_api 使用SQLite 或者 MySQL 这样的关系型数据库 , 用来存储(结构化数据)关系型数据:知识库的id,名称,类型,创建时间；知识库文档的id,名称,类型，文件存储位置等等元信息
以及通过SQL Alchemy 中的relationship方法 将知识库和知识库文档两张表关联起来，实现知识库1下面有哪些文档，文档A属于哪个知识库这样的关联效果
es_api 使用ES非关系型数据库(向量数据库) 来存储非结构化信息 或者 非关系型数据，以及向量数据：如文档具体内容以及文档具体内容编码后的向量
ES数据库最大的优势是搜索快 + 准(全文检索 + 向量检索)
文档数据写入ES数据库时，ES数据库就会自动分词 + 创建倒排索引，用来支持后面的全文检索
全文检索主要通过 分词 + 倒排索引 + BM25打分 -> 与提问内容最相关的top N （50）
向量检索主要通过 bge编码 + HNSW图算法(迅速找到最相关的文档or chunk) + 余弦相似度计算 -> 得到与提问最相关的top N(50)
最后通过RRF融合算法 去打分，排序 -> top K (10)
还可以进一步使用bge-rerank重排序模型 再进行打分，排序(精排) -> top M (5 / 3)
最终得到的就是与提问最相关的文本块(chunk)
送入提示词模版，喂给大模型，由大模型来总结答案 -> 输出
"""







