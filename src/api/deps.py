"""FastAPI 依赖注入：公共依赖项集中定义

路由处理函数通过 Depends() 注入，避免每个 handler 重复获取配置/数据库等资源。

用法示例：
    @router.get("/api/example")
    def example(config: dict = Depends(get_config)):
        return ok(config)
"""
from src.config import load_config


def get_config() -> dict:
    """注入全局配置（YAML 缓存）"""
    return load_config()


def get_supplement_fields() -> list:
    """注入补充字段名称列表"""
    return ["分析问题时间", "AI分析结果(飞书链接)", "AI评论总结", "rootcause", "结果置信度"]
