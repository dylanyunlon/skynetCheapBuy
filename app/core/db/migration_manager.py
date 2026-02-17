from typing import List, Dict, Any
import json
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)

class Migration:
    """数据库迁移基类"""
    
    def __init__(self, version: str, description: str):
        self.version = version
        self.description = description
    
    async def up(self, db: Session):
        """执行迁移"""
        raise NotImplementedError
    
    async def down(self, db: Session):
        """回滚迁移"""
        raise NotImplementedError

class MigrationManager:
    """迁移管理器"""
    
    def __init__(self, db: Session):
        self.db = db
        self._ensure_migration_table()
    
    def _ensure_migration_table(self):
        """确保迁移表存在"""
        self.db.execute(text("""
            CREATE TABLE IF NOT EXISTS migrations (
                version VARCHAR(50) PRIMARY KEY,
                description TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        self.db.commit()
    
    async def migrate(self, migrations: List[Migration]):
        """执行迁移"""
        for migration in migrations:
            if not await self._is_applied(migration.version):
                logger.info(f"Applying migration {migration.version}: {migration.description}")
                
                try:
                    await migration.up(self.db)
                    await self._mark_applied(migration.version, migration.description)
                    logger.info(f"Migration {migration.version} applied successfully")
                except Exception as e:
                    logger.error(f"Migration {migration.version} failed: {e}")
                    raise

# 迁移：移除硬编码的默认模型
class RemoveHardcodedDefaultModel(Migration):
    def __init__(self):
        super().__init__("20240101_001", "Remove hardcoded default model")
    
    async def up(self, db: Session):
        # 更新用户表的默认模型
        db.execute(text("""
            UPDATE users 
            SET preferred_model = 'gpt-3.5-turbo' 
            WHERE preferred_model = 'o3-gz'
        """))
        db.commit()
    
    async def down(self, db: Session):
        # 回滚
        db.execute(text("""
            UPDATE users 
            SET preferred_model = 'o3-gz' 
            WHERE preferred_model = 'gpt-3.5-turbo'
        """))
        db.commit()