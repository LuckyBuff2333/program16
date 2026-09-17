"""数据库层测试：bugid 只读去重查询"""
import allure

from src import db


def _seed_bugids(*bugids):
    """直接向 bug_records 表插入测试数据（模拟外部维护的已有 bugid）"""
    session = db._get_session()
    for bugid in bugids:
        session.add(db.BugRecord(bugid=bugid, status="success"))
    session.commit()
    session.close()


@allure.feature("数据库层")
@allure.story("bugid 去重")
def test_filter_new_bugids():
    """已存在的 bugid 被过滤，新的 bugid 通过"""
    _seed_bugids("BUG-1")
    new_ids, dup_ids = db.filter_new_bugids(["BUG-1", "BUG-2", "BUG-3"])
    assert new_ids == ["BUG-2", "BUG-3"]
    assert dup_ids == ["BUG-1"]


@allure.feature("数据库层")
@allure.story("bugid 去重")
def test_filter_all_new():
    """全部为新 bugid 时无过滤"""
    new_ids, dup_ids = db.filter_new_bugids(["BUG-10", "BUG-11"])
    assert new_ids == ["BUG-10", "BUG-11"]
    assert dup_ids == []


@allure.feature("数据库层")
@allure.story("bugid 去重")
def test_filter_batch_duplicates():
    """同一批输入中的重复 bugid 也会被过滤"""
    new_ids, dup_ids = db.filter_new_bugids(["BUG-20", "BUG-20", "BUG-21"])
    assert new_ids == ["BUG-20", "BUG-21"]
    assert dup_ids == ["BUG-20"]


@allure.feature("数据库层")
@allure.story("只读约束")
def test_db_not_written_by_tool():
    """工具去重查询不产生任何写入：查询后表中记录数不变"""
    _seed_bugids("BUG-30")
    db.filter_new_bugids(["BUG-30", "BUG-31"])
    session = db._get_session()
    count = session.query(db.BugRecord).count()
    session.close()
    assert count == 1  # BUG-31 未被写入数据库
