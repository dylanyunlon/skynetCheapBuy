from typing import List, Dict, Any, Optional, Type
from sqlalchemy.orm import Session, Query, selectinload, joinedload
from sqlalchemy import and_, or_, func
from functools import wraps
import logging

logger = logging.getLogger(__name__)

class QueryOptimizer:
    """查询优化器"""
    
    def __init__(self, db: Session):
        self.db = db
        self._query_cache = {}
    
    def eager_load(self, query: Query, *relationships) -> Query:
        """预加载关联数据，避免 N+1 问题"""
        for relationship in relationships:
            if "." in relationship:
                # 嵌套关系
                query = query.options(selectinload(relationship))
            else:
                # 直接关系
                query = query.options(joinedload(relationship))
        return query
    
    def batch_load(self, model: Type, ids: List[Any], relationships: List[str] = None) -> Dict[Any, Any]:
        """批量加载"""
        query = self.db.query(model).filter(model.id.in_(ids))
        
        if relationships:
            query = self.eager_load(query, *relationships)
        
        results = query.all()
        return {item.id: item for item in results}
    
    def paginate(self, query: Query, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """分页查询"""
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        }
    
    def apply_filters(self, query: Query, filters: Dict[str, Any]) -> Query:
        """应用过滤条件"""
        for field, value in filters.items():
            if value is not None:
                if isinstance(value, list):
                    query = query.filter(getattr(query.column_descriptions[0]['type'], field).in_(value))
                elif isinstance(value, dict):
                    # 范围查询
                    if "gte" in value:
                        query = query.filter(getattr(query.column_descriptions[0]['type'], field) >= value["gte"])
                    if "lte" in value:
                        query = query.filter(getattr(query.column_descriptions[0]['type'], field) <= value["lte"])
                else:
                    query = query.filter(getattr(query.column_descriptions[0]['type'], field) == value)
        return query
    
    def optimized_count(self, query: Query) -> int:
        """优化的计数查询"""
        # 移除不必要的 ORDER BY 和 JOIN
        count_query = query.order_by(None).options()
        return self.db.query(func.count()).select_from(count_query.subquery()).scalar()

def optimized_query(relationships: List[str] = None):
    """优化查询装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # 获取 db session
            db = kwargs.get('db') or self.db
            
            # 创建优化器
            optimizer = QueryOptimizer(db)
            
            # 注入优化器
            kwargs['optimizer'] = optimizer
            
            # 执行查询
            result = await func(self, *args, **kwargs)
            
            return result
        return wrapper
    return decorator