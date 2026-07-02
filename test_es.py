import pytest
import numpy as np
from es_api import es

#测试是否连接ES成功
def test_connect_es():
    assert es.ping() is not None

#测试ES初始化是否成功，初始化创建的索引是否存在
def test_init_es():
    assert es.indices.exists(index = "document_meta"), "索引 'document_meta' does not exist"
    assert es.indices.exists(index = "chunk_info"), "索引 'chunk_info' does not exist"

#测试插入文档元数据document_meta
def test_insert_document_meta():
    test_document = {
        "file_path": "test_file.txt",
        "file_name": "test_file",
        "abstract": "This is a test abstract.",
        "content": "This is the full content of the test file."
    }
    response = es.index(index = "document_meta",document = test_document)
    assert response['result'] == 'created'

    doc_id = response['_id']
    result = es.exists(index = "document_meta",id = doc_id)
    assert result

    es.delete(index = "document_meta",id = doc_id)
#测试查询文档元数据document_meta
def test_query_document_meta():
    test_document = {
        "file_path": "query_test_file.txt",
        "file_name": "query_test_file",
        "abstract": "This is an abstract for query testing.",
        "content": "Full content for the query test file."
    }
    response = es.index(index = "document_meta",document = test_document)
    assert response['result'] == 'created'
    doc_id = response['_id']
    es.indices.refresh(index="document_meta")

    search_response = es.search(index = "document_meta",query = {"match":{"file_name":"query_test_file"}})
    assert search_response['hits']['total']['value'] >= 1, "Query should return at least one document, but no exist!"

    retrieved_document = search_response['hits']['hits'][0]['_source']
    assert retrieved_document['file_name'] == test_document['file_name']
    assert retrieved_document['abstract'] == test_document['abstract']
    assert retrieved_document['content'] == test_document['content']

    es.delete(index = "document_meta",id = doc_id)

#测试插入文本块信息chunk_info
def test_insert_chunk_info():
    test_chunk = {
        "chunk_id": 0,
        "knowledge_id": "knowledge_1",
        "document_id": "document_1",
        "page_number": 1,
        "chunk_content": "This is the content of chunk 0.",
        "chunk_images": ["/path/to/image1.jpg"],
        "chunk_tables": ["/path/to/table1.csv"],
        "chunk_embedding":[0.1] * 512
    }
    response = es.index(index = "chunk_info",document = test_chunk)
    assert response['result'] == 'created'

    doc_id = response['_id']
    result = es.exists(index = "chunk_info",id = doc_id)
    assert result, "Chunk info document does not exist!"

    es.delete(index = "chunk_info",id = doc_id)

#测试检索文本块信息chunk_info(全文检索和向量检索)
def test_query_chunk_info():
    test_chunk = {
        "chunk_id": 0,
        "knowledge_id": "knowledge_1",
        "document_id": "document_1",
        "page_number": 1,
        "chunk_content": "This is the content of chunk_0",
        "chunk_images": ["/path/to/image1.jpg"],
        "chunk_tables": ["/path/to/table1.csv"],
        "chunk_embedding": np.random.rand(512).tolist()
    }

    response = es.index(index = "chunk_info",document = test_chunk)
    assert response['result'] == 'created'
    doc_id = response['_id']
    es.indices.refresh(index="chunk_info")

    #查询文本块信息(全文检索)
    query_content = "chunk_0"
    content_query_response = es.search(index = "chunk_info",query = {"match":{
        "chunk_content":query_content
    }})
    assert content_query_response['hits']['total']['value'] >= 1, "No match document found for chunk_content"

    #向量检索
    knn_query = {
        "field": "chunk_embedding",
        "query_vector": test_chunk["chunk_embedding"],
        "k": 5,
        "num_candidates": 10,
    }
    vector_search_response = es.search(index = "chunk_info",knn = knn_query)
    assert vector_search_response['hits']['total']['value'] > 0,"No similar chunks found in vector search."
    es.delete(index = "chunk_info",id = doc_id)