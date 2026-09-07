"""数据库层：仅用于 bugid 去重的只读查询

工具运行结果不写入数据库，只生成结论表格（CSV）；
数据库中的 bug_records 表由外部维护，作为已有 bugid 的比对来源。
"""
import os
from datetime import datetime

# SQLAlchemy 延迟导入：避免 multiprocessing.spawn 热重载时 NamedTuple 创建失败
from src.config import PROJECT_ROOT, load_config, setup_logger

logger = setup_logger("db")
_cfg = load_config()

# 延迟初始化占位
Base = None
BugRecord = None
_engine = None
_Session = None
text = None


def _ensure_models():
    """延迟导入 SQLAlchemy 并初始化模型（首次调用时执行）"""
    global Base, BugRecord, _cfg, text
    if Base is not None:
        return
    from sqlalchemy import Boolean, Column, DateTime, Float, String, text as _text
    from sqlalchemy.orm import declarative_base
    text = _text
    Base = declarative_base()

    class _BugRecord(Base):
        """Bug 记录表（只读）：仅用于步骤1 的 bugid 去重比对，表数据由外部维护"""
        __tablename__ = _cfg["database"].get("table_name", "bug_records")
        bugid = Column(String(64), primary_key=True)
        trigger_time = Column(String(32), nullable=True)
        status = Column(String(16), default="pending")
        root_cause_match = Column(Boolean, nullable=True)
        step_match = Column(Boolean, nullable=True)
        similarity_score = Column(Float, nullable=True)
        doc_path = Column(String(512), nullable=True)
        error_msg = Column(String(1024), nullable=True)
        stored = Column(Boolean, default=False)
        created_at = Column(DateTime, default=datetime.now)
        updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    BugRecord = _BugRecord


def init_db(db_url: str = None):
    """初始化数据库连接并自动建表，可传入自定义 URL（测试用）"""
    global _engine, _Session
    _ensure_models()
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    url = db_url or load_config()["database"]["url"]
    # SQLite 相对路径统一基于项目根目录解析
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        rel = url[len("sqlite:///"):]
        if not os.path.isabs(rel):
            abs_path = os.path.join(PROJECT_ROOT, rel)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            url = "sqlite:///" + abs_path.replace("\\", "/")
    _engine = create_engine(url, echo=False)
    Base.metadata.create_all(_engine)
    # 创建 kb_analysis 表（抽查候选池，由入库操作填充）
    cfg = load_config()["audit"]
    kb_table = cfg["kb_table"]
    with _engine.connect() as conn:
        conn.execute(text(
            f"CREATE TABLE IF NOT EXISTS {kb_table} ("
            f"{cfg['bugid_column']} VARCHAR(64) PRIMARY KEY, "
            f"{cfg['trigger_time_column']} VARCHAR(32), "
            f"{cfg['root_cause_column']} TEXT, "
            f"{cfg['process_column']} TEXT)"
        ))
        conn.commit()
    _Session = sessionmaker(bind=_engine)
    logger.info("数据库初始化完成: %s", url)
    return _engine


def _get_session():
    """获取 Session，未初始化时自动初始化"""
    if _Session is None:
        init_db()
    return _Session()


def filter_new_bugids(bugids: list) -> tuple:
    """步骤1：bugid 去重（同时过滤本批输入中的重复项）。返回 (新增列表, 已存在列表)"""
    session = _get_session()
    try:
        existed = (
            session.query(BugRecord.bugid)
            .filter(BugRecord.bugid.in_(bugids))
            .all()
        )
        existed_set = {row[0] for row in existed}
        new_ids, dup_ids = [], []
        seen = set()  # 记录本批已处理的 bugid，批内重复也归入过滤
        for bugid in bugids:
            if bugid in existed_set or bugid in seen:
                dup_ids.append(bugid)
            else:
                new_ids.append(bugid)
                seen.add(bugid)
        logger.info("bugid 去重完成: 新增 %d 个, 过滤已存在 %d 个", len(new_ids), len(dup_ids))
        return new_ids, dup_ids
    finally:
        session.close()


def fetch_audit_candidates() -> list:
    """随机抽查候选池：读取已入库表中全部 bugid 与触发时间（只读）

    :return: [{"bugid": ..., "trigger_time": ...}, ...]
    """
    cfg = load_config()["audit"]
    session = _get_session()
    try:
        sql = text(f"SELECT {cfg['bugid_column']} AS bugid, "
                   f"{cfg['trigger_time_column']} AS trigger_time FROM {cfg['kb_table']}")
        rows = [{"bugid": str(r.bugid), "trigger_time": r.trigger_time} for r in session.execute(sql)]
        logger.info("抽查候选池读取完成: 共 %d 个已入库 bugid", len(rows))
        return rows
    except Exception as e:
        logger.error("抽查候选池读取失败: %s", e)
        raise
    finally:
        session.close()


def fetch_stored_analysis(bugid: str) -> dict:
    """读取指定 bugid 已入库的根因分析与分析流程字段（只读）

    :return: {"root_cause": ..., "analysis_process": ...}，无记录时字段为 None
    """
    cfg = load_config()["audit"]
    session = _get_session()
    try:
        sql = text(f"SELECT {cfg['root_cause_column']} AS root_cause, "
                   f"{cfg['process_column']} AS analysis_process "
                   f"FROM {cfg['kb_table']} WHERE {cfg['bugid_column']} = :bugid")
        row = session.execute(sql, {"bugid": bugid}).first()
        if row is None:
            logger.warning("库中无 bugid=%s 的已入库分析记录", bugid)
            return {"root_cause": None, "analysis_process": None}
        return {"root_cause": row.root_cause, "analysis_process": row.analysis_process}
    except Exception as e:
        logger.error("读取已入库分析字段失败: bugid=%s, 错误: %s", bugid, e)
        raise
    finally:
        session.close()


def save_stored_analysis(bugid: str, trigger_time: str, root_cause: str, analysis_process: str) -> None:
    """入库时将分析结果写入 kb_analysis 表（供抽查候选池使用）"""
    cfg = load_config()["audit"]
    session = _get_session()
    try:
        # 先删除已存在的同 bugid 记录
        session.execute(text(f"DELETE FROM {cfg['kb_table']} WHERE {cfg['bugid_column']} = :bugid"),
                        {"bugid": bugid})
        # 插入新记录
        session.execute(
            text(f"INSERT INTO {cfg['kb_table']} "
                 f"({cfg['bugid_column']}, {cfg['trigger_time_column']}, "
                 f"{cfg['root_cause_column']}, {cfg['process_column']}) "
                 f"VALUES (:bugid, :trigger_time, :root_cause, :process)"),
            {"bugid": bugid, "trigger_time": trigger_time, "root_cause": root_cause,
             "process": analysis_process}
        )
        session.commit()
        logger.info("已入库分析已写入 kb_analysis: bugid=%s", bugid)
    except Exception as e:
        session.rollback()
        logger.error("写入 kb_analysis 失败: bugid=%s, 错误: %s", bugid, e)
        raise
    finally:
        session.close()
