#todo:定义接口规范 Request and Response
"""
Request 定义了前端应该传来的请求格式
Response 定义后端处理完请求，返回给前端的格式
"""


import datetime
from pydantic import BaseModel,Field
from typing import Union,List,Any,Tuple,Dict,Annotated
from fastapi import FastAPI,File,UploadFile,Form


class EmbeddingRequest(BaseModel):
    """
    前端调用文本向量化接口时传入的请求体：待编码文本、鉴权 token、模型名称
    """
    text: Union[str,List[str]]
    token:str
    model:str

class EmbeddingResponse(BaseModel):
    """
    文本向量化接口返回给前端的响应体：请求 ID、编码后的向量数组及执行状态"
    """
    request_id: str = Field(description = "请求ID")
    vector: List[List[float]] = Field(description = "文本对应的向量表示")
    response_code: int = Field(description = "响应码，表示成功或者错误状态")
    response_msg: str = Field(description = "响应信息，详细描述响应结果")
    process_status: str = Field(description = "处理状态,例如'completed'、'pending'、'failed'")
    process_time: float = Field(description = "处理请求的耗时(秒)")

class RerankRequest(BaseModel):
    """
    前端调用重排序接口时传入的请求体：文本对列表、鉴权 token、模型名称
    """
    text_pair: List[Tuple[str,str]]
    token:str
    model:str

class RerankResponse(BaseModel):
    """
    重排序接口返回给前端的响应体：请求 ID、各文本对的相似度分数及执行状态
    """
    request_id: str = Field(description = "请求ID")
    vector: List[float]
    response_code: int = Field(description = "响应码，用于表示成功或者错误状态")
    response_msg: str = Field(description = "响应信息，详细描述响应结果")
    process_status: str = Field(description = "处理状态，例如 'completed'、'pending' 或 'failed'")
    process_time: float = Field(description = "处理请求的耗时(秒)")

class KnowledgeRequest(BaseModel):
    """
    前端创建知识库时传入的请求体：知识库分类和名称
    """
    category: str
    title: str

class KnowledgeResponse(BaseModel):
    """
    知识库 CRUD 接口返回给前端的响应体：知识库 ID、分类、名称及执行状态
    """
    request_id: str = Field(description = "请求ID")
    knowledge_id: int = Field(description = "知识库ID")
    category: str = Field(description = "知识库分类")
    title: str = Field(description = "知识库名称")
    response_code: int = Field(description = "响应码，用于表示成功或者错误状态")
    response_msg: str = Field(description = "响应信息，详细描述响应结果")
    process_status: str = Field(description = "处理状态，例如 'completed'、'pending' 或 'failed'")
    process_time: float = Field(description = "处理请求的耗时(秒)")

class DocumentRequest(BaseModel):
    """
    前端上传文档时传入的表单请求体：所属知识库 ID、文档名称、分类、文件本体
    为什么 DocumentRequest 里每个字段都要用 Annotated[str, Form()]？
    因为文件上传必须用表单格式传，不能用 JSON body。
    这是一种和 JSON 完全不同的编码方式。
    FastAPI 默认不认识这种格式里的字段，你必须逐字段告诉它"从表单里取，别从 JSON 里取"。
    Form() 就是在告诉 FastAPI："这几个参数从表单字段里取，别去 JSON 里找"。
    str则表示在表单里，HTTP 表单传过来的knowledge_id 原始值是字符串 "1"
    int 表示 我希望最终knowledge_id 字段是 int 格式
    File(...) 里的三个点表示必传。如果前端不传文件，FastAPI 直接返回 422。
    """
    knowledge_id: int = Annotated[str,Form()]
    title: str = Annotated[str,Form()]
    category: str = Annotated[str,Form()]
    file: UploadFile = Annotated[str,File(...)] #File(...) 表示该参数是必须的

class DocumentResponse(BaseModel):
    """
    文档 CRUD 接口返回给前端的响应体：文档 ID、所属知识库、文件类型及执行状态
    """
    request_id: str = Field(description = "请求ID")
    document_id: int = Field(description = "文档ID")
    category: str = Field(description = "文档分类")
    title: str = Field(description = "文档名称")
    knowledge_id: int = Field(description = "知识库ID")
    file_type: str = Field(description = "文件类型")
    response_code: int = Field(description = "响应码，用于表示成功或者错误状态")
    response_msg: str = Field(description = "响应信息，详细描述响应结果")
    process_status: str = Field(description = "处理状态,例如 'completed'、'pending' 或 'failed'")
    process_time: float = Field(description = "处理请求的耗时(秒)")

class RAGRequest(BaseModel):
    """
    前端发起 RAG 对话时传入的请求体：目标知识库 ID、多轮对话消息列表
    """
    knowledge_id: int
    message: List[Dict]

class RAGResponse(BaseModel):
    """
    RAG 对话接口返回给前端的响应体：包含 AI 回答的完整消息列表及执行状态
    """
    request_id: str = Field(description = "请求ID")
    message: List[Dict]
    sources: List[Dict] = Field(default=[], description="引用的原文片段列表")
    response_code: int = Field(description = "响应码，用于表示成功或者错误状态")
    response_msg: str = Field(description = "响应信息，详细描述响应结果")
    process_status: str = Field(description = "处理状态，例如 'completed'、'pending' 或 'failed'")
    process_time: float = Field(description = "处理请求的耗时(秒)")

