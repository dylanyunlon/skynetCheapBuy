# app/db/init_db.py
import logging
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from app.db.session import engine, SessionLocal
from app.models import user, chat, file
from app.core.security import SecurityUtils
from app.models.user import User, UserRole
from datetime import datetime

logger = logging.getLogger(__name__)

def init_db():
    """初始化数据库"""
    # 创建所有表
    user.Base.metadata.create_all(bind=engine)
    chat.Base.metadata.create_all(bind=engine)
    file.Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")

def create_test_users(db: Session) -> None:
    """创建测试用户"""
    test_users = [
        {
            "username": "admin",
            "email": "admin@example.com",
            "full_name": "系统管理员",
            "password": "admin123",
            "role": UserRole.ADMIN,
            "is_active": True,
            "is_superuser": True,
            "preferred_model": "o3-gz",
            "language": "zh",
            "preferences": {
                "PASS_HISTORY": 3,
                "LONG_TEXT": True,
                "FOLLOW_UP": True,
                "TITLE": True,
                "REPLY": True,
                "TYPING": True
            },
            "plugins": {
                "search": False,
                "url_reader": False,
                "generate_image": False
            }
        },
        {
            "username": "testuser",
            "email": "test@example.com", 
            "full_name": "测试用户",
            "password": "test123",
            "role": UserRole.USER,
            "is_active": True,
            "is_superuser": False,
            "preferred_model": "o3-gz",
            "language": "en",
            "preferences": {
                "PASS_HISTORY": 3,
                "LONG_TEXT": True,
                "FOLLOW_UP": True,
                "TITLE": True,
                "REPLY": True,
                "TYPING": True
            },
            "plugins": {
                "search": False,
                "url_reader": False,
                "generate_image": False
            }
        },
        {
            "username": "newuser",
            "email": "newuser@example.com",
            "full_name": "新用户",
            "password": "newPass123",
            "role": UserRole.USER,
            "is_active": True,
            "is_superuser": False,
            "preferred_model": "o3-gz",
            "language": "zh",
            "preferences": {
                "PASS_HISTORY": 3,
                "LONG_TEXT": True,
                "FOLLOW_UP": True,
                "TITLE": True,
                "REPLY": True,
                "TYPING": True
            },
            "plugins": {
                "search": False,
                "url_reader": False,
                "generate_image": False
            },
            "api_keys": {},
            "api_urls": {}
        }
    ]
    
    for user_data in test_users:
        user = db.query(User).filter(User.username == user_data["username"]).first()
        if not user:
            password = user_data.pop("password")
            user = User(
                **user_data,
                hashed_password=SecurityUtils.get_password_hash(password),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(user)
            logger.info(f"Created test user: {user_data['username']}")
        else:
            # 更新现有用户的属性
            for key, value in user_data.items():
                if key != "password" and hasattr(user, key):
                    setattr(user, key, value)
            user.updated_at = datetime.utcnow()
            logger.info(f"Updated existing user: {user_data['username']}")
    
    db.commit()

def create_sample_conversations(db: Session) -> None:
    """创建示例会话"""
    from app.models.chat import ChatSession, ChatMessage
    import uuid
    
    # 获取测试用户
    test_user = db.query(User).filter(User.username == "testuser").first()
    if not test_user:
        return
    
    # 创建示例会话
    sample_session = ChatSession(
        user_id=test_user.id,
        title="示例对话 - AI助手初体验",
        description="这是一个示例对话，展示AI助手的基本功能",
        config={
            "model": "o3-gz",
            "temperature": 0.7,
            "max_tokens": 2000
        },
        tags=["示例", "教程"],
        message_count=2,
        is_pinned=True
    )
    db.add(sample_session)
    db.commit()
    
    # 添加示例消息
    messages = [
        {
            "role": "user",
            "content": "你好！请介绍一下你自己。"
        },
        {
            "role": "assistant", 
            "content": "你好！我是AI助手，很高兴为您服务。我可以帮助您：\n\n1. **回答问题** - 涵盖各种知识领域\n2. **编写代码** - 支持多种编程语言\n3. **创意写作** - 故事、文章、诗歌等\n4. **数据分析** - 处理和分析各类数据\n5. **学习辅导** - 解释概念，提供练习\n\n请随时告诉我您需要什么帮助！",
            "model": "o3-gz",
            "tokens": {"prompt_tokens": 20, "completion_tokens": 100, "total_tokens": 120}
        }
    ]
    
    for msg_data in messages:
        message = ChatMessage(
            session_id=sample_session.id,
            role=msg_data["role"],
            content=msg_data["content"],
            model=msg_data.get("model"),
            message_data={"tokens": msg_data.get("tokens", {})} if "tokens" in msg_data else {}
        )
        db.add(message)
    
    db.commit()
    logger.info("Created sample conversations")

def init_data():
    """初始化数据"""
    db = SessionLocal()
    try:
        # 创建测试用户
        create_test_users(db)
        
        # 创建示例会话
        create_sample_conversations(db)
        
        logger.info("Initial data created successfully")
    except Exception as e:
        logger.error(f"Error creating initial data: {e}")
        db.rollback()
        raise
    finally:
        db.close()
    init_code_management_tables()

def check_tables_exist():
    """检查数据库表是否存在"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    # 修正表名列表，使用实际的表名
    required_tables = [
        'users',           # 用户表
        'chat_sessions',   # 聊天会话表
        'chat_messages',   # 聊天消息表
        'chat_templates',  # 聊天模板表
        'chat_shares',     # 聊天分享表
        'files',           # 文件表
        'file_shares',     # 文件分享表
        'file_conversions',# 文件转换表
        'file_chunks',     # 文件分块表
        'file_access_logs' # 文件访问日志表
    ]
    
    missing_tables = [table for table in required_tables if table not in tables]
    
    if missing_tables:
        logger.warning(f"Missing tables: {missing_tables}")
        return False
    
    logger.info("All required tables exist")
    return True

def reset_database():
    """重置数据库（仅用于开发环境）"""
    logger.warning("Dropping all tables...")
    user.Base.metadata.drop_all(bind=engine)
    chat.Base.metadata.drop_all(bind=engine)
    file.Base.metadata.drop_all(bind=engine)
    
    logger.info("Recreating all tables...")
    init_db()
    init_data()

def repair_database():
    """修复数据库结构"""
    db = SessionLocal()
    try:
        # 检查并修复用户表的默认值
        users = db.query(User).all()
        for user in users:
            updated = False
            
            # 确保preferences不为None
            if user.preferences is None:
                user.preferences = {
                    "PASS_HISTORY": 3,
                    "LONG_TEXT": True,
                    "FOLLOW_UP": True,
                    "TITLE": True,
                    "REPLY": True,
                    "TYPING": True
                }
                updated = True
            
            # 确保plugins不为None
            if user.plugins is None:
                user.plugins = {
                    "search": False,
                    "url_reader": False,
                    "generate_image": False
                }
                updated = True
            
            # 确保api_keys和api_urls不为None
            if user.api_keys is None:
                user.api_keys = {}
                updated = True
                
            if user.api_urls is None:
                user.api_urls = {}
                updated = True
            
            # 确保有preferred_model
            if not user.preferred_model:
                user.preferred_model = "o3-gz"
                updated = True
            
            # 确保有language
            if not user.language:
                user.language = "zh"
                updated = True
            
            if updated:
                user.updated_at = datetime.utcnow()
                logger.info(f"Repaired user data for: {user.username}")
        
        db.commit()
        logger.info("Database repair completed")
        
    except Exception as e:
        logger.error(f"Error repairing database: {e}")
        db.rollback()
        raise
    finally:
        db.close()

    
def init_code_management_tables():
    """初始化代码管理相关的表"""
    from app.models.code import GeneratedCode, CronJob
    
    # 创建表
    GeneratedCode.__table__.create(bind=engine, checkfirst=True)
    CronJob.__table__.create(bind=engine, checkfirst=True)
    
    # 创建索引
    with engine.connect() as conn:
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_generated_codes_user_id ON generated_codes(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_generated_codes_conversation_id ON generated_codes(conversation_id)",
            # ... 其他索引
        ]
        
        for index_sql in indexes:
            conn.execute(text(index_sql))
        conn.commit()