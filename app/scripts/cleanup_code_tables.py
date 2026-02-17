# app/scripts/cleanup_code_tables.py
"""
清理并重建代码管理相关表
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text
from app.config import settings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_tables():
    """删除旧表"""
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # 开始事务
            trans = conn.begin()
            
            try:
                # 删除表（按照依赖顺序）
                logger.info("删除旧表...")
                
                # 先删除有外键依赖的表
                conn.execute(text("DROP TABLE IF EXISTS cron_jobs CASCADE"))
                logger.info("✅ 删除 cron_jobs 表")
                
                conn.execute(text("DROP TABLE IF EXISTS generated_codes CASCADE"))
                logger.info("✅ 删除 generated_codes 表")
                
                conn.execute(text("DROP TABLE IF EXISTS code_snippets CASCADE"))
                logger.info("✅ 删除 code_snippets 表")
                
                # 提交事务
                trans.commit()
                logger.info("✅ 所有旧表已删除")
                
            except Exception as e:
                trans.rollback()
                raise e
                
    except Exception as e:
        logger.error(f"❌ 清理失败: {e}")
        raise

if __name__ == "__main__":
    cleanup_tables()