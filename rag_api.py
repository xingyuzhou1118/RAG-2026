import yaml
import os
import re
from typing import Union,List,Any,Dict
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
import numpy as np
import datetime
import pdfplumber #导入pdfplumber模块，用于处理PDF文件
from docx import Document # 导入Document模块，处理 Word .docx 文件
from openai import OpenAI

import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
"""
transformers → 重排序模型（判断问题和段落有多搭）
AutoTokenizer  把文字切成 token ID 列表。"人均可支配收入" → [101, 782, 2190, ...]
AutoModelForSequenceClassification  加载一个"输入文字对、输出一个匹配分数"的分类模型
"""
from sentence_transformers import SentenceTransformer
"""
SentenceTransformer 是 sentence-transformers 库的核心类，专管文本 → 向量编码。一句话调用：
model = SentenceTransformer("模型路径")
vector = model.encode("人均可支配收入增长 5.3%")
这个库是专门为 BERT 族模型设计的便捷包装层。底层也是 HuggingFace 的 transformer 架构，
但它把"加载模型 → 切词 → 推理 → 均值池化 → 归一出向量"全包成一行 encode()
"""

"""
为什么重排序不用 SentenceTransformer？
因为 BGE-reranker 的模型结构是 Cross-Encoder（把问题和候选段落拼一起，直接算匹配分），
不是 SentenceTransformer 默认的 Bi-Encoder（分别编码再算相似度）。
前者精度高但慢，只用在最后精排阶段；后者适合海量检索。
"""
from es_api import es

device = config["device"]
#全局字典，充当模型仓库
Embedding_Model_params: Dict[Any,Any] = {}

Basic_QA_Template = """现在的时间是{#Time#}。你是一个专家，你擅长回答用户的提问，帮我结合给定的资料，回答下面的
问题。如果问题无法从资料中获得，或无法从资料中进行回答，请回答'无法回答'。
如果提问不符合逻辑，请回答'无法回答'。
如果问题可以从资料中获得，则请逐步回答，最后进行总结。
资料:
{#Related_Document#}

问题:{#Question#}

"""

Basic_QA_Template_v2 = """现在的时间是{#Time#}。你是一个专家，请结合以下参考资料回答问题。
回答时使用 [1] [2] 等编号标注所引用的信息来源。如果问题无法从资料中获得，请回答"无法回答"。

参考资料：
{#References#}

问题：{#Question#}
"""

"""
模板里特意加了三行约束（"无法回答"）——防止 LLM 在检索不到相关内容时胡编乱造。
这是 RAG 系统对抗幻觉的第一道防线。
"""
def load_embedding_model(model_name: str,model_path: str)-> None:
    """
    加载编码模型
    :param model_name:编码模型的名称(bge-small-zh-v1.5)
    :param model_path:编码模型的路径(/models/BAAI/bge-small-zh-v1.5)
    :return:
    """
    global Embedding_Model_params
    # sbert(sentence bert)模型
    if model_name in ["bge-small-zh-v1.5","bge-base-zh-v1.5"]:
        Embedding_Model_params["embedding_model"] = SentenceTransformer(model_path)
    #SentenceTransformer 是 sentence-transformers 库提供的便捷接口，一行代码加载模型。
    #这个模型的能力：输入一句话，输出一个 512 维的浮点数向量。语义相近的句子，向量在空间里挨得近。

def load_rerank_model(model_name:str,model_path:str) -> None:
    """
    加载重排序模型
    :param model_name:模型名称(bge-reranker-base)
    :param model_path:模型路径(/models/BAAI/bge-reranker-base)
    :return:
    """
    global Embedding_Model_params
    if model_name in ["bge-reranker-base"]:
        # cross-encoder重排序模型
        Embedding_Model_params["rerank_model"] = AutoModelForSequenceClassification.from_pretrained(model_path)
        # tokenizer分词器，用来把文字切分成 token ID 列表
        Embedding_Model_params["rerank_tokenizer"] = AutoTokenizer.from_pretrained(model_path)
        # 把模型调成推理模式（关掉 dropout 等训练特性）
        Embedding_Model_params["rerank_model"].eval()
        # 把模型移到CPU or GPU
        Embedding_Model_params["rerank_model"].to(device)

if config["rag"]["use_embedding"]:
    model_name = config["rag"]["embedding_model"]
    model_path = config["models"]["embedding_model"][model_name]["local_url"]
    print(f'Loading embedding model {model_name} from model path {model_path}')
    load_embedding_model(model_name,model_path)

if config["rag"]["use_rerank"]:
    model_name = config["rag"]["rerank_model"]
    model_path = config["models"]["rerank_model"][model_name]["local_url"]

    print(f"Loading rerank model {model_name} from model path {model_path}")
    load_rerank_model(model_name, model_path)

def split_text_with_overlap(text,chunk_size,overlap_size) -> List[str]:
    """
    将长文本切分成多个短文本
    :param text:长文本
    :param chunk_size:每个短文本的长度
    :param overlap_size:短文本之间的重叠长度
    :return:多个短文本组成的列表
    """
    chunks = [] #最终要返回的切片列表，存放切分后的文本片段
    start = 0   #当前切片的起始位置，从0开始
    while start < len(text):     #只要起始位置小于文本长度，就继续切分
        end = start + chunk_size #计算当前切片的结束位置 = 当前起始位置 + 切片大小chunk_size
        chunk = text[start:end]  #用Python的切片语法，从起始位置到结束位置提取文本片段
        chunks.append(chunk)     #将当前片段添加到结果列表中
        start = end - overlap_size #更新起始位置，将起始位置后移，并减去重叠长度overlap_size

    return chunks

class RAG:

    def __init__(self):
        """

        """
        self.embedding_model = config["rag"]["embedding_model"]
        self.rerank_model = config["rag"]["rerank_model"]
        self.use_rerank = config["rag"]["use_rerank"]
        self.embedding_dims = config["models"]["embedding_model"][config["rag"]["embedding_model"]]["dims"]
        self.chunk_size = config["rag"]["chunk_size"]
        self.overlap_size = config["rag"]["overlap_size"]
        self.chunk_candidate = config["rag"]["chunk_candidate"]
        self.client = OpenAI(
            api_key = config["rag"]["llm_api_key"],
            base_url = config["rag"]["llm_base"]
        )
        self.llm_model = config["rag"]["llm_model"]

    def get_embedding(self,text:Union[str,List[str]]) -> np.ndarray:
        """
        对文本进行编码
        :param text:待编码文本
        :return:编码结果
        """
        if self.embedding_model in ["bge-small-zh-v1.5","bge-base-zh-v1.5"]:
            return Embedding_Model_params["embedding_model"].encode(text,normalize_embeddings = True)

        raise NotImplemented #抛出异常，表示这个函数还没有实现

    def get_rerank(self,text_pair) -> np.ndarray:
        """
        对文本进行重排序
        :param text_pair:待排序的文本对
        :return:排序结果
        """
        if self.rerank_model in ["bge-reranker-base"]:
            with torch.no_grad():
                inputs = Embedding_Model_params["rerank_tokenizer"](
                    text_pair,padding = True,truncation = True,
                    return_tensors = "pt",max_length = 512,
                )
                inputs = {key:value.to(device) for key,value in inputs.items()}
                scores = Embedding_Model_params["rerank_model"](**inputs,return_dict = True).logits.view(-1,).float()
                scores = scores.data.cpu().numpy()
                return scores
        raise NotImplementedError
    def _extract_pdf_content(self,knowledge_id,document_id,title,file_path) -> bool:
        """
        从PDF文件中提取内容,负责处理后台解析文档内容
        这是 background_tasks 后台跑的那个函数。逐页打开 PDF → 提取文字 → 切 chunk → 编码 → 写 ES
        :param knowledge_id:知识库ID
        :param document_id:文档ID
        :param title:文档标题
        :param file_path:PDF文件路径
        :return:是否成功
        """
        try:
            pdf = pdfplumber.open(file_path)
        except Exception as e:
            print("打开文件失败！")
            return False
        print(f"{file_path}，pages:{len(pdf.pages)}页") #打印文件地址和页数等信息

        abstract = ""

        for page_number in range(len(pdf.pages)):     #每一页提取
            current_page_text = pdf.pages[page_number].extract_text() #提取当前页的文本

            # 设定前四页为摘要的组成
            if page_number < 4:
                abstract = abstract + '\n' + current_page_text

            # 将当前页的内容编码为向量存入ES
            embedding_vector = self.get_embedding(current_page_text)
            page_data = {
                "document_id": document_id,
                "knowledge_id": knowledge_id,
                "page_number": page_number,
                "chunk_id": 0,
                "chunk_content": current_page_text,
                "chunk_images": [],
                "chunk_tables": [],
                "chunk_embedding": [float(x) for x in list(embedding_vector)]
            }
            response = es.index(index = "chunk_info",document = page_data)

            #滑窗切分成小块chunk，逐块编码存入 ES（chunk_id=1,2,3...）
            page_chunks = split_text_with_overlap(current_page_text,self.chunk_size,self.overlap_size)
            embedding_vector = self.get_embedding(page_chunks)
            for chunk_idx in range(1,len(page_chunks) + 1):
                page_data = {
                    "document_id": document_id,
                    "knowledge_id": knowledge_id,
                    "page_number": page_number,
                    "chunk_id": chunk_idx,
                    "chunk_content": page_chunks[chunk_idx - 1],
                    "chunk_images": [],
                    "chunk_tables": [],
                    "chunk_embedding": [float(x) for x in list(embedding_vector[chunk_idx - 1])]
                }
                response = es.index(index = "chunk_info",document = page_data)
        # 接下来写入文档的元数据信息
        document_data = {
            "document_id": document_id,
            "knowledge_id": knowledge_id,
            "file_name": title,
            "file_path": file_path,
            "abstract": abstract
        }
        response = es.index(index = "document_meta",document = document_data)
        return True

    def _extract_word_content(self,knowledge_id,document_id,title,file_type,file_path)-> bool:
        """
        PDF 是分页文档，Word 是流式文档 无分页 只分段落；
        从Word文件中提取内容,负责处理后台解析文档内容
        这是 background_tasks 后台跑的那个函数。打开 Word → 提取文字 → 切 chunk → 编码 → 写 ES
        :param knowledge_id:知识库ID
        :param document_id:文档ID
        :param title:文档标题
        :param file_type:文件类型
        :param file_path:文件路径
        :return:是否成功
        """
        try:
            # .doc 旧格式不支持 python-docx，先转成 .docx
            if file_path.lower().endswith(".doc") and not file_path.lower().endswith(".docx"):
                import win32com.client
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                docx_path = file_path + "x"
                try:
                    doc = word.Documents.Open(os.path.abspath(file_path))
                    doc.SaveAs2(os.path.abspath(docx_path), FileFormat=16)  # 16=wdFormatDocumentDefault
                    doc.Close()
                finally:
                    word.Quit()
                file_path = docx_path

            doc = Document(file_path)
        except Exception as e:
            print("打开文件失败！")
            return False

        # 收集所有非空段落的文字
        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip() # strip() 去除首尾空格和空白回车
            if text:
                paragraphs.append(text)

        if not paragraphs:
            print("文档无内容！")
            return False
        abstract = '\n'.join(paragraphs[:4]) # 拼接前四个段落作为摘要
        full_text = '\n'.join(paragraphs) # 用换行符拼接所有段落

        # 1.整篇文档存入ES(chunk_id = 0,完整原文)
        embedding_vector = self.get_embedding(full_text)
        es.index(index = "chunk_info",document = {
            "document_id": document_id,
            "knowledge_id": knowledge_id,
            "page_number": 0, # Word 文档无页码概念，只有段落
            "chunk_id": 0,
            "chunk_content": full_text,
            "chunk_images": [],
            "chunk_tables": [],
            "chunk_embedding": [float(x) for x in list(embedding_vector)]
        })
        # 2.滑窗切分成小块chunk,逐块编码存入ES
        chunks = split_text_with_overlap(full_text,self.chunk_size,self.overlap_size)
        embedding_vector = self.get_embedding(chunks)
        for chunk_idx in range(1,len(chunks) + 1):
            para_data = {
                "document_id": document_id,
                "knowledge_id": knowledge_id,
                "page_number": 0, # Word 文档无页码概念，只有段落
                "chunk_id": chunk_idx,
                "chunk_content": chunks[chunk_idx - 1],
                "chunk_images": [],
                "chunk_tables": [],
                "chunk_embedding": [float(x) for x in list(embedding_vector[chunk_idx - 1])]
            }
            response = es.index(index = "chunk_info",document = para_data)

        # 3.文档元数据信息写入ES的document_meta索引中
        es.index(index = "document_meta",document = {
            "document_id": document_id,
            "knowledge_id": knowledge_id,
            "file_name": title,
            "file_path": file_path,
            "abstract": abstract
        })

        return True



    def extract_content(self,knowledge_id,document_id,title,file_type,file_path):
        if "pdf" in file_type:
            self._extract_pdf_content(knowledge_id,document_id,title,file_path)
        elif "word" in file_type:
            self._extract_word_content(knowledge_id,document_id,title,file_type,file_path)

        print("提取完成",document_id,file_type,file_path)

    #todo:核心方法：混合检索：BM25全文检索 + 向量语义检索 + RRF融合 + BGE-rerank重排序
    def hybrid_query_document(self,query: str,knowledge_id: int) -> List[str]:
        # 1.BM25 全文检索 -> 指定一个知识库检索，bm25打分
        word_search_response = es.search(index = "chunk_info", # 索引名称
            body = { #ES查询DSL
            "query": {
                "bool":{  # bool查询：可以组合多个条件
                    "must":[ # must条件必须满足
                        {
                            "match":{ # match查询，对chunk_content字段进行关键词匹配
                                "chunk_content": query
                            }
                        }
                    ],
                    "filter":[ # filter条件是筛选或者过滤条件，满足filter条件才能返回
                        {
                            "term":{
                                "knowledge_id": knowledge_id
                            }
                        }
                    ]
                }
            },
            "size": 50  # 返回50条最相关的结果
        },
        fields = ["chunk_id","document_id","knowledge_id","page_number","chunk_content"], # 只返回指定的字段
        source = False # 不返回原始_source字段，进一步瘦身
        )
        # 2.向量语义检索
        embedding_vector = self.get_embedding(query) #编码查询向量
        knn_query = {
            "field": "chunk_embedding", # 在哪个字段进行向量检索
            "query_vector":[float(x) for x in list(embedding_vector)], # 查询向量
            "k": 50, # 返回最相关的k个结果
            "num_candidates": 100,  #hnsw 初步检索计算得到num_candidate个待选chunk, 然后对这num_candidate个chunk进行向量距离计算，得到最相似的k个chunk
            "filter": {  # filter条件是筛选或者过滤条件，满足filter条件才能返回
                "term": {
                    "knowledge_id": knowledge_id
                }
            }
        }
        vector_search_response = es.search(
            index = "chunk_info",knn = knn_query, # 选择knn查询，而不是body内的DSL查询
            fields = ["chunk_id","document_id","knowledge_id","page_number","chunk_content"], # 只返回指定的字段
            source = False # 不返回原始_source字段，进一步瘦身
            )

        #3. RRF 融合
        """
        RRF_score(doc) = Σ (1 / (排名_i + k))
        排名_i 是在当前这一路检索中的排名
        多路召回：召回 BM25全文检索 和 向量语义检索得到两路检索结果
        BM25全文检索：[a,b,c,d]
        向量语义检索: [b,e,a,c]
        a 1/60  b 1/61  c 1/62  d 1/63
        b 1/60  e 1/61  a 1/62  c 1/63
        a = 1/60 + 1/62 = 0.0328
        b = 1/61 + 1/60 = 0.0331
        c = 1/62 + 1/63 = 0.0321
        d = 1/63 = 0.0159
        e = 1/61 = 0.0164
    
        """
        k = 60
        fusion_score = {}  #只存分数，用来排序 {chunk的ES内部_id: RRF累加分数}
        chunk_id2record = {} # 只存完整记录，排序后按分数高低取出来 {chunk的ES内部_id: 完整记录}
        """
        查询后ES返回的JSON格式
        word_search_response = {
    "took": 23,                                          # 查询耗时（毫秒）
    "timed_out": False,
    "_shards": {"total": 1, "successful": 1, ...},
    "hits": {                                            # 第一层 hits：整个检索结果的外壳
        "total": {"value": 87, "relation": "eq"},        # 匹配到的总条数
        "max_score": 4.78,                               # 最高 BM25 分数
        "hits": [                                        # 第二层 hits：真正的结果列表
            {
                "_index": "chunk_info",                  # 来源索引
                "_id": "aBcDeFg123",                     # 这个 chunk 的内部 ID
                "_score": 4.78,                          # BM25 分数
                "fields": {                              # 你通过 fields=[] 参数要的字段
                    "chunk_id": [1],
                    "document_id": [42],
                    "knowledge_id": [3],
                    "page_number": [0],
                    "chunk_content": ["2024年居民人均可支配收入41314元..."]
                }
            },
            {                                            # 结果列表的第二条
                "_index": "chunk_info",
                "_id": "hIjKlMn456",
                "_score": 3.92,
                "fields": { ... }
            },
            ...   # 总计size = 50 条
        ]
    }
}

        """
        # 添加BM25全文检索的RRF分数
        for idx,record in enumerate(word_search_response['hits']['hits']):
            _id = record['_id']  #  这个chunk的ES内部_id
            # BM25全文检索这一路的RRF累加分数
            if _id not in fusion_score:
                fusion_score[_id] = 1 / (idx + k)
            else:
                fusion_score[_id] += 1 / (idx + k)

            # 记录完整字段
            if _id not in chunk_id2record:
                chunk_id2record[_id] = record["fields"]

        # 添加向量语义检索的RRF分数
        for idx,record in enumerate(vector_search_response['hits']['hits']):
            _id = record['_id'] # 这个chunk的ES内部_id
            # 向量语义检索这一路的RRF累加分数
            if _id not in fusion_score:
                fusion_score[_id] = 1 / (idx + k)

            else:
                fusion_score[_id] += 1 / (idx + k)

            # 添加完整字段
            if _id not in chunk_id2record:
                chunk_id2record[_id] = record["fields"]
        # 对fusion_score字典进行排序，按照RRF累加分数的高低进行排序降序
        sorted_dict = sorted(fusion_score.items(),key = lambda item: item[1],reverse = True)
        # 根据排序后的chunk的ID，取出chunk_id2record的完整字段，最后截取chunk_candidate条
        sorted_records = [chunk_id2record[x[0]] for x in sorted_dict] [:self.chunk_candidate]
        # 只返回record["fields"]所有字段中的chunk_content字段
        sorted_content = [x["chunk_content"] for x in sorted_records]

        # 没有检索到任何内容，直接返回
        if not sorted_records:
            return []

        # rerank 重排序
        if self.use_rerank:
            text_pairs = []
            for chunk_content in sorted_content:
                if chunk_content and chunk_content[0]:
                    text_pairs.append([query, chunk_content[0]])
            if not text_pairs:
                return sorted_records
            rerank_score = self.get_rerank(text_pairs) # 对候选chunk进行rerank重排序打分
            """
                    text_pair = [
            ["人均收入增长", "2024年居民人均可支配收入41314元，同比名义增长5.3%"],     # 候选1
            ["人均收入增长", "GDP增长反映经济总量变化，不直接反映居民收入"],             # 候选2
            ["人均收入增长", "隔壁老王今天买了两斤苹果花了15块钱"],                      # 候选3
            ["人均收入增长", "城镇居民人均可支配收入增速高于农村"],                      # 候选4
            ["人均收入增长", "全国居民恩格尔系数为29.8%，比上年下降0.1个百分点"],         # 候选5
            ]
            得到的rerank_score 是这样的numpy数组： array([4.87, 2.13, -8.92, 5.01, 1.76], dtype=float32)
            rerank_score = [4.87, 2.13, -8.92, 5.01, 1.76]
            """
            rerank_idx = np.argsort(rerank_score)[::-1]
            # 对rerank_score进行排序，返回排序后的索引，[::-1]由升序变降序
            #rerank_idx = [4, 0, 1, 3, 2] 对应着 降序 从大到小排序后的 sorted_records，sorted_content以及rerank_score的索引

            # 根据索引降序排序rerank_idx，返回降序排序后的sorted_records
            sorted_records = [sorted_records[x] for x in rerank_idx]
        # 根据索引降序排序rerank_idx，返回降序排序后的sorted_content
            sorted_content = [sorted_content[x] for x in rerank_idx]

        return sorted_records

    def _build_references(self, related_records):
        """根据检索结果构造带编号的参考资料和 sources 元数据"""
        # 收集唯一 document_id，批量查标题
        doc_ids = set()
        for r in related_records:
            did = r.get("document_id", [None])[0]
            if did is not None:
                doc_ids.add(did)

        doc_titles = {}
        if doc_ids:
            try:
                resp = es.search(index="document_meta", body={
                    "query": {"terms": {"document_id": list(doc_ids)}},
                    "size": len(doc_ids),
                }, fields=["document_id", "title"], source=False)
                for h in resp["hits"]["hits"]:
                    _did = h["fields"]["document_id"][0]
                    _title = h["fields"]["title"][0]
                    doc_titles[_did] = _title
            except Exception:
                pass

        references_parts = []
        sources = []
        for i, record in enumerate(related_records, 1):
            content = record["chunk_content"][0]
            did = record.get("document_id", [None])[0]
            doc_title = doc_titles.get(did, f"文档#{did}" if did else "未知文档")

            prefix = f"《{doc_title}》" if doc_title else ""
            references_parts.append(f"[{i}] {prefix}\n{content}")

            sources.append({
                "id": i,
                "document_id": did,
                "document_title": doc_title,
                "content_preview": content[:200] + ("..." if len(content) > 200 else ""),
            })

        return "\n\n".join(references_parts), sources

    def chat_with_rag(
            self,
            knowledge_id: int, #对哪一个知识库进行提问和检索
            messages: List[Dict], #对话消息
    ):
        """

        :param knowledge_id:
        :param messages:
        :return: (messages, sources)
        """
        sources = []
        if len(messages) == 1:
            query = messages[0]["content"]
            related_records  = self.hybrid_query_document(query = query,knowledge_id = knowledge_id)
            references, sources = self._build_references(related_records)

            rag_query = Basic_QA_Template_v2.replace("{#Time#}",str(datetime.datetime.now())) \
                .replace("{#Question#}",query) \
                .replace("{#References#}",references)

            rag_response = self.chat(
                [{"role":"user","content":rag_query}],
                0.7,0.9
            ).content
            messages.append({"role":"system","content":rag_response})

        else:
            normal_response = self.chat(
                messages,
                0.7,
                0.9
            ).content
            messages.append({"role":"system","content":normal_response})

        return messages, sources

    def chat(self,messages:List[Dict],top_p:float,temperature:float) -> Any:
        completion = self.client.chat.completions.create(
            model = self.llm_model,
            messages = messages,
            top_p = top_p,
            temperature = temperature,
        )
        return completion.choices[0].message

    def chat_stream(self, messages:List[Dict], top_p:float=0.7, temperature:float=0.9):
        """流式调用 LLM，逐 token 生成"""
        completion = self.client.chat.completions.create(
            model = self.llm_model,
            messages = messages,
            top_p = top_p,
            temperature = temperature,
            stream = True,
        )
        for chunk in completion:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def chat_with_rag_stream(self, knowledge_id:int, messages:List[Dict]):
        """RAG 对话流式版本"""
        if len(messages) == 1:
            query = messages[0]["content"]
            related_records = self.hybrid_query_document(query=query, knowledge_id=knowledge_id)
            references, sources = self._build_references(related_records)
            rag_query = Basic_QA_Template_v2.replace("{#Time#}", str(datetime.datetime.now())) \
                .replace("{#Question#}", query) \
                .replace("{#References#}", references)
            yield from self.chat_stream([{"role":"user", "content":rag_query}])
            yield {"sources": sources}
        else:
            yield from self.chat_stream(messages)










