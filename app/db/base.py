# app/db/base.py
from typing import Any
from sqlalchemy.ext.declarative import as_declarative, declared_attr
from sqlalchemy import Column, DateTime, func, MetaData
from datetime import datetime

# 创建命名约定，用于自动生成约束名称
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)

@as_declarative(metadata=metadata)
class Base:
    """
    数据库模型基类
    
    提供所有模型的公共属性和方法
    """
    id: Any
    __name__: str
    
    # 自动生成表名
    @declared_attr
    def __tablename__(cls) -> str:
        """
        自动生成表名（将类名转换为下划线格式）
        例如：UserProfile -> user_profile
        """
        import re
        name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', cls.__name__)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()
    
    def dict(self):
        """将模型转换为字典"""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
    
    def __repr__(self):
        """友好的字符串表示"""
        params = ', '.join(f'{k}={v}' for k, v in self.dict().items() if k != 'id')
        return f"{self.__class__.__name__}(id={self.id}, {params})"

# 提供一个函数来获取所有模型
def get_all_models():
    """获取所有已注册的模型类"""
    return Base.__subclasses__()

# 提供一个函数来创建所有表
def create_all_tables(engine):
    """创建所有表"""
    Base.metadata.create_all(bind=engine)

# 提供一个函数来删除所有表（危险操作，仅用于测试）
def drop_all_tables(engine):
    """删除所有表（危险操作）"""
    Base.metadata.drop_all(bind=engine)