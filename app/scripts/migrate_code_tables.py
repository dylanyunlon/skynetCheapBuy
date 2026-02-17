# app/scripts/migrate_code_tables.py
"""
数据库迁移脚本 - 添加代码管理相关表
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text
from app.config import settings
from app.db.base import Base
from app.models.code import CodeSnippet, GeneratedCode, CronJob
from app.models.user import User
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_tables():
    """创建代码管理相关的表"""
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        # 创建所有表
        Base.metadata.create_all(bind=engine, tables=[
            CodeSnippet.__table__,
            GeneratedCode.__table__,
            CronJob.__table__
        ])
        logger.info("✅ 代码管理表创建成功")
        
        # 检查表是否存在
        with engine.connect() as conn:
            # 检查 code_snippets 表
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'code_snippets'
            """))
            if result.scalar() > 0:
                logger.info("✅ code_snippets 表已存在")
            
            # 检查 generated_codes 表
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'generated_codes'
            """))
            if result.scalar() > 0:
                logger.info("✅ generated_codes 表已存在")
            
            # 检查 cron_jobs 表
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'cron_jobs'
            """))
            if result.scalar() > 0:
                logger.info("✅ cron_jobs 表已存在")
        
        # 添加索引
        with engine.connect() as conn:
            # 为 code_snippets 添加索引
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_code_snippets_user_id 
                ON code_snippets(user_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_code_snippets_conversation_id 
                ON code_snippets(conversation_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_code_snippets_language 
                ON code_snippets(language)
            """))
            conn.commit()
            logger.info("✅ 索引创建成功")
            
    except Exception as e:
        logger.error(f"❌ 创建表失败: {e}")
        raise

def check_user_relation():
    """检查User模型是否有code_snippets关系"""
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # 检查users表是否存在
            result = conn.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'users'
            """))
            if result.scalar() == 0:
                logger.warning("⚠️  users 表不存在，请先运行用户表迁移")
                return False
            
            logger.info("✅ users 表存在")
            return True
            
    except Exception as e:
        logger.error(f"❌ 检查失败: {e}")
        return False

def verify_migration():
    """验证迁移是否成功"""
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # 测试插入数据
            result = conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'code_snippets'
                ORDER BY ordinal_position
            """))
            
            columns = result.fetchall()
            logger.info("\n📋 code_snippets 表结构:")
            for col_name, col_type in columns:
                logger.info(f"  - {col_name}: {col_type}")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ 验证失败: {e}")
        return False

def main():
    """主函数"""
    logger.info("🚀 开始数据库迁移...")
    
    # 1. 检查用户表
    if not check_user_relation():
        logger.error("❌ 请先确保用户表存在")
        return
    
    # 2. 创建表
    create_tables()
    
    # 3. 验证迁移
    if verify_migration():
        logger.info("\n✅ 数据库迁移完成！")
        logger.info("📌 您现在可以使用代码管理功能了")
    else:
        logger.error("\n❌ 迁移验证失败，请检查数据库")

if __name__ == "__main__":
    main()