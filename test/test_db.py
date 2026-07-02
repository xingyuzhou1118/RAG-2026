import pytest
from db_api import KnowledgeDatabase, Session

@pytest.fixture #装饰器，将一个函数变成夹具每次测试函数需要数据库会话时，pytest 自动调用这个函数，把返回值注入进去。
def session():
    with Session() as session:
        yield session
        session.rollback()

def test_insert_knowledge_database(session):
    new_record = KnowledgeDatabase(title = "测试知识库1",category = "测试")
    session.add(new_record)
    session.commit()

    record = session.query(KnowledgeDatabase).filter_by(title = "测试知识库1").first()
    assert record is not None
    assert record.title == "测试知识库1"
    assert record.category == "测试"
    print("插入知识库Successfully!")

def test_query_knowledge_database(session):
    session.add(KnowledgeDatabase(title = "测试知识库2",category = "测试"))
    session.commit()

    records = session.query(KnowledgeDatabase).filter_by(category = "测试").all()
    assert len(records) > 1
    assert records[0].title == "测试知识库1"
    print("查询知识库Successfully!")

def test_delete_knowledge_database(session):
    record_to_delete = session.query(KnowledgeDatabase).filter_by(title = "测试知识库2").first()
    session.delete(record_to_delete)
    session.commit()

    record = session.query(KnowledgeDatabase).filter_by(title = "测试知识库2").first()
    assert record is None
    print("删除知识库Successfully!")