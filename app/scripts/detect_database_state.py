# app/scripts/detect_database_state.py
"""检测当前数据库状态，为安全迁移做准备"""

import asyncio
from sqlalchemy import text, inspect
from app.db.session import SessionLocal
from app.db.base import Base

async def detect_current_database_state():
    """检测当前数据库中的表和字段"""
    
    print("🔍 正在检测数据库状态...")
    db = SessionLocal()
    
    try:
        # 获取数据库检查器
        inspector = inspect(db.bind)
        existing_tables = inspector.get_table_names()
        
        print(f"\n📊 现有表列表:")
        for table in sorted(existing_tables):
            print(f"  ✓ {table}")
        
        # 检查关键表
        required_tables = ['users', 'conversations', 'messages']
        missing_tables = [t for t in required_tables if t not in existing_tables]
        
        if missing_tables:
            print(f"\n❌ 缺少必需的表: {missing_tables}")
            return False
        
        # 检查是否已有项目相关表
        project_tables = ['projects', 'project_files']
        existing_project_tables = [t for t in project_tables if t in existing_tables]
        
        print(f"\n🎯 项目相关表状态:")
        for table in project_tables:
            exists = table in existing_tables
            status = "✓ 存在" if exists else "❌ 不存在"
            print(f"  {table}: {status}")
        
        # 检查用户表结构
        print(f"\n👤 用户表字段:")
        user_columns = inspector.get_columns('users')
        for col in user_columns:
            print(f"  ✓ {col['name']} ({col['type']})")
        
        # 检查对话表结构
        print(f"\n💬 对话表字段:")
        conv_columns = inspector.get_columns('conversations')
        for col in conv_columns:
            print(f"  ✓ {col['name']} ({col['type']})")
        
        # 检查是否有 chat_sessions 表
        has_chat_sessions = 'chat_sessions' in existing_tables
        print(f"\n🔄 聊天会话表状态:")
        print(f"  chat_sessions: {'✓ 存在' if has_chat_sessions else '❌ 不存在'}")
        print(f"  conversations: ✓ 存在")
        
        # 生成迁移建议
        print(f"\n💡 迁移建议:")
        
        if existing_project_tables:
            print("  ⚠️  已存在项目表，需要检查兼容性")
        else:
            print("  ✅ 可以安全创建项目表")
        
        if has_chat_sessions:
            print("  ⚠️  同时存在 chat_sessions 和 conversations，需要确认关系")
        else:
            print("  ✅ 使用 conversations 作为主要对话表")
        
        return True
        
    except Exception as e:
        print(f"❌ 检测失败: {e}")
        return False
    finally:
        db.close()

async def check_existing_data_volume():
    """检查现有数据量"""
    
    print("\n📈 现有数据统计:")
    db = SessionLocal()
    
    try:
        # 用户数量
        user_count = db.execute(text("SELECT COUNT(*) FROM users")).scalar()
        print(f"  用户数量: {user_count}")
        
        # 对话数量
        conv_count = db.execute(text("SELECT COUNT(*) FROM conversations")).scalar()
        print(f"  对话数量: {conv_count}")
        
        # 消息数量
        msg_count = db.execute(text("SELECT COUNT(*) FROM messages")).scalar()
        print(f"  消息数量: {msg_count}")
        
        if user_count > 0:
            print(f"\n⚠️  检测到现有用户数据，将使用安全迁移模式")
        else:
            print(f"\n✅ 空数据库，可以使用快速迁移模式")
            
    except Exception as e:
        print(f"❌ 数据统计失败: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(detect_current_database_state())
    asyncio.run(check_existing_data_volume())