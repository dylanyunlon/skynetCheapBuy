# alembic/versions/add_vibe_coding_fields.py
"""Add vibe coding fields to existing tables

Revision ID: add_vibe_coding_001
Revises: [20250708]
Create Date: 2025-01-09 16:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text, inspect

# revision identifiers
revision = 'add_vibe_coding_001'
down_revision = None  # 请替换为您当前的最新 revision ID
branch_labels = None
depends_on = None

def check_column_exists(table_name: str, column_name: str) -> bool:
    """安全检查字段是否存在"""
    try:
        conn = op.get_bind()
        inspector = inspect(conn)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except:
        return False

def add_column_safely(table_name: str, column_name: str, column_type, **kwargs):
    """安全添加字段 - 只在不存在时添加"""
    if not check_column_exists(table_name, column_name):
        print(f"  ✅ 为 {table_name} 添加字段: {column_name}")
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(sa.Column(column_name, column_type, **kwargs))
        return True
    else:
        print(f"  ⚠️  {table_name}.{column_name} 已存在，跳过")
        return False

def upgrade():
    """安全的增量升级 - 只添加缺失的字段"""
    
    print("🚀 开始 Vibe Coding 增量迁移...")
    
    # 1. 为 projects 表添加 Vibe Coding 字段
    print("\n📁 扩展 projects 表...")
    
    # Vibe Coding 核心字段
    add_column_safely('projects', 'creation_prompt', sa.Text(), nullable=True, 
                     comment='用户原始输入prompt')
    add_column_safely('projects', 'enhanced_prompt', sa.Text(), nullable=True,
                     comment='AI优化后的prompt')
    add_column_safely('projects', 'ai_response', sa.Text(), nullable=True,
                     comment='AI完整响应内容')
    add_column_safely('projects', 'meta_prompt_data', sa.JSON(), nullable=True,
                     comment='双重AI调用的完整数据')
    add_column_safely('projects', 'preview_url', sa.String(500), nullable=True,
                     comment='项目预览URL')
    
    # 可选：添加其他有用的字段
    add_column_safely('projects', 'deployment_config', sa.JSON(), nullable=True,
                     comment='部署配置信息')
    add_column_safely('projects', 'build_logs', sa.Text(), nullable=True,
                     comment='构建日志')
    add_column_safely('projects', 'execution_status', sa.String(50), nullable=True,
                     comment='执行状态')
    
    # 创建索引（如果字段是新添加的）
    try:
        if not check_column_exists('projects', 'preview_url'):  # 说明是新添加的
            op.create_index('ix_projects_preview_url', 'projects', ['preview_url'])
        if not check_column_exists('projects', 'execution_status'):
            op.create_index('ix_projects_execution_status', 'projects', ['execution_status'])
    except Exception as e:
        print(f"  ⚠️  索引创建可能失败: {e}")
    
    print("  ✅ projects 表扩展完成")

    # 2. 为 conversations 表添加项目关联字段
    print("\n💬 扩展 conversations 表...")
    
    add_column_safely('conversations', 'current_project_id', postgresql.UUID(as_uuid=True), 
                     nullable=True, comment='当前关联的项目ID')
    add_column_safely('conversations', 'conversation_type', sa.String(50), 
                     nullable=True, default='general', comment='对话类型：general, vibe_coding, project_focused')
    add_column_safely('conversations', 'project_context', sa.JSON(), 
                     nullable=True, comment='项目相关的对话上下文')
    
    # 为新字段设置默认值
    try:
        print("  🔧 为现有对话设置默认值...")
        op.execute(text("""
            UPDATE conversations 
            SET conversation_type = 'general', project_context = '{}'
            WHERE conversation_type IS NULL
        """))
    except Exception as e:
        print(f"  ⚠️  设置默认值可能失败: {e}")
    
    # 创建索引和外键
    try:
        op.create_index('ix_conversations_project_id', 'conversations', ['current_project_id'])
        op.create_index('ix_conversations_type', 'conversations', ['conversation_type'])
        
        # 添加外键约束
        op.create_foreign_key(
            'fk_conversations_project_id',
            'conversations', 'projects',
            ['current_project_id'], ['id'],
            ondelete='SET NULL'
        )
    except Exception as e:
        print(f"  ⚠️  索引/外键创建可能失败: {e}")
    
    print("  ✅ conversations 表扩展完成")

    # 3. 为 messages 表添加意图识别字段
    print("\n💭 扩展 messages 表...")
    
    add_column_safely('messages', 'intent_detected', sa.String(100), 
                     nullable=True, comment='检测到的用户意图')
    add_column_safely('messages', 'project_action', sa.String(100), 
                     nullable=True, comment='项目相关操作类型')
    add_column_safely('messages', 'ai_processing_data', sa.JSON(), 
                     nullable=True, comment='AI处理过程数据')
    
    # 创建索引
    try:
        op.create_index('ix_messages_intent', 'messages', ['intent_detected'])
        op.create_index('ix_messages_project_action', 'messages', ['project_action'])
    except Exception as e:
        print(f"  ⚠️  索引创建可能失败: {e}")
    
    print("  ✅ messages 表扩展完成")

    # 4. 验证迁移结果
    print("\n🔍 验证迁移结果...")
    try:
        conn = op.get_bind()
        
        # 检查关键字段
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'projects' AND column_name IN (
                'creation_prompt', 'enhanced_prompt', 'ai_response', 'meta_prompt_data', 'preview_url'
            )
        """))
        added_fields = [row[0] for row in result]
        print(f"  ✅ projects 表新增字段: {added_fields}")
        
        # 统计现有数据
        projects_count = conn.execute(text("SELECT COUNT(*) FROM projects")).scalar()
        conversations_count = conn.execute(text("SELECT COUNT(*) FROM conversations")).scalar()
        
        print(f"  📊 现有数据完整性检查:")
        print(f"    - 项目数量: {projects_count}")
        print(f"    - 对话数量: {conversations_count}")
        
        print(f"  🎉 所有现有数据保持完整！")
        
    except Exception as e:
        print(f"  ⚠️  验证过程出现问题: {e}")
    
    print("\n🎉 Vibe Coding 增量迁移完成！")
    print("💡 现在可以开始使用 vibe coding 功能了")

def downgrade():
    """安全回滚 - 删除添加的字段"""
    
    print("🔄 开始回滚 Vibe Coding 字段...")
    
    # 删除索引
    indexes_to_drop = [
        ('ix_projects_preview_url', 'projects'),
        ('ix_projects_execution_status', 'projects'),
        ('ix_conversations_project_id', 'conversations'),
        ('ix_conversations_type', 'conversations'),
        ('ix_messages_intent', 'messages'),
        ('ix_messages_project_action', 'messages'),
    ]
    
    for index_name, table_name in indexes_to_drop:
        try:
            op.drop_index(index_name, table_name)
            print(f"  ✅ 删除索引: {index_name}")
        except Exception as e:
            print(f"  ⚠️  索引 {index_name} 删除失败: {e}")
    
    # 删除外键
    try:
        op.drop_constraint('fk_conversations_project_id', 'conversations', type_='foreignkey')
        print(f"  ✅ 删除外键约束")
    except Exception as e:
        print(f"  ⚠️  外键删除失败: {e}")
    
    # 删除字段
    tables_and_fields = [
        ('projects', ['creation_prompt', 'enhanced_prompt', 'ai_response', 'meta_prompt_data', 
                     'preview_url', 'deployment_config', 'build_logs', 'execution_status']),
        ('conversations', ['current_project_id', 'conversation_type', 'project_context']),
        ('messages', ['intent_detected', 'project_action', 'ai_processing_data'])
    ]
    
    for table_name, fields in tables_and_fields:
        print(f"\n🔄 回滚 {table_name} 表...")
        
        for field_name in fields:
            try:
                if check_column_exists(table_name, field_name):
                    with op.batch_alter_table(table_name, schema=None) as batch_op:
                        batch_op.drop_column(field_name)
                    print(f"  ✅ 删除字段: {field_name}")
            except Exception as e:
                print(f"  ⚠️  字段 {field_name} 删除失败: {e}")
    
    print("\n🎉 回滚完成！")