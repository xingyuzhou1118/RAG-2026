import yaml

from elasticsearch import Elasticsearch #导入ES客户端
import traceback #导入 追踪错误 模块


#读取配置文件
with open("config.yaml","r") as f:
    config = yaml.safe_load(f)

#从配置文件中提取ES的连接参数
es_host = config["elasticsearch"]["host"]
es_port = config["elasticsearch"]["port"]
es_scheme = config["elasticsearch"]["scheme"]
es_username = config["elasticsearch"]["username"]
es_password = config["elasticsearch"]["password"]

if es_username != "" and es_password != "":
    es = Elasticsearch(
        [
            {
                "host": es_host,
                "port": es_port,
                "scheme": es_scheme
            }
        ],
        basic_auth = (es_username,es_password)
    )
else:
    es = Elasticsearch(
        [
            {
                "host": es_host,
                "port": es_port,
                "scheme": es_scheme
            }
        ]
    )
embedding_dims = config["models"]["embedding_model"][
    config["rag"]["embedding_model"]
]["dims"]

#初始化es
def init_es():
    """
    检查es环境配置
    :return: 环境配置是否成功
    """
    if not es.ping():
        print(traceback.format_exc())
        print("Could not connect to Elasticsearch.")
        return False

    """
    ES数据库里index索引就是SQL里的一张表TABLE，document就是一行数据,mapping可以用来提前定义index中的字段(SQL中的列字段Column)
    也可以不用提前定义，创建一个document数据的时候定义有什么字段
    file_name 字段存储的是文档的名字
    abstract 字段存储的是文档的摘要
    content 字段存储的是文档的内容
    """
    document_meta_mapping = {
        "mappings":{
            "properties":{
                'file_name':{
                    'type': 'text',
                    'analyzer': 'ik_max_word',
                    'search_analyzer': 'ik_smart'
                },
                'abstract':{
                    'type': 'text',
                    'analyzer': 'ik_max_word',
                    'search_analyzer': 'ik_smart'
                },
                'content':{
                    'type': 'text',
                    'analyzer': 'ik_max_word',
                    'search_analyzer': 'ik_smart'
                }

            }
        }
    }
    #如果没有document_meta索引(表)就创建，创建失败就返回错误原因
    try:
        if not es.indices.exists(index = "document_meta"):
            es.indices.create(index = "document_meta",body = document_meta_mapping)
    except:
        print(traceback.format_exc())
        print("Could not create index of document_meta.")
        return False

    """
    chunk_info索引中预先定义了chunk_content,chunk_embedding字段
    chunk_content字段:用来存储文档解析后文本块的内容
    chunk_embedding字段:用来存储文档解析后通过bge编码模型编码后的稠密向量，方便进行倒排索引，以及需要查询数据时进行
    向量检索
    """
    chunk_info_mapping = {
        "mappings":{
            'properties':{
                'chunk_content':{
                    'type': 'text',
                    'analyzer': 'ik_max_word',
                    'search_analyzer': 'ik_smart'
                },
                'chunk_embedding':{
                    'type':'dense_vector',
                    'element_type':'float',
                    'dims':embedding_dims,
                    'index':True,
                    'index_options':{
                        'type':'int8_hnsw'
                    }
                }
            }
        }
    }
    try:
        if not es.indices.exists(index = "chunk_info"):
            es.indices.create(index = "chunk_info",body = chunk_info_mapping)
    except:
        print(traceback.format_exc())
        print("Could not create index of chunk_info.")
        return False

    print("Successfully connected to Elasticsearch!")

init_es()

