# alembic/versions/001_conditional_project_tables.py
"""Conditional project tables creation based on existing state

Revision ID: 001
Create Date: 2025-01-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text, inspect

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None

def check_table_exists(table_name: str) -> bool:
    """检查表是否存在"""
    try:
        conn = op.get_bind()
        inspector = inspect(conn)
        return table_name in inspector.get_table_names()
    except:
        return False

def check_column_exists(table_name: str, column_name: str) -> bool:
    """检查字段是否存在"""
    try:
        conn = op.get_bind()
        inspector = inspect(conn)
        columns = [col['name'] for col in inspector.get_columns(table_name)]
        return column_name in columns
    except:
        return False

def upgrade():
    """条件化升级 - 只创建不存在的表和字段"""
    
    print("🚀 开始条件化数据库升级...")
    
    # 1. 检查并创建 projects 表
    if not check_table_exists('projects'):
        print("  📁 创建 projects 表...")
        op.create_table('projects',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
            sa.Column('name', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('project_type', sa.String(50), nullable=False, default='web'),
            sa.Column('tech_stack', sa.JSON(), nullable=True, default=lambda: []),
            sa.Column('status', sa.String(50), nullable=False, default='creating'),
            
            # 工作空间信息
            sa.Column('workspace_path', sa.String(500), nullable=True),
            sa.Column('preview_url', sa.String(500), nullable=True),
            sa.Column('deployment_url', sa.String(500), nullable=True),
            
            # 统计信息
            sa.Column('file_count', sa.Integer(), nullable=False, default=0),
            sa.Column('size', sa.Integer(), nullable=False, default=0),
            
            # Vibe Coding 相关字段
            sa.Column('creation_prompt', sa.Text(), nullable=True),
            sa.Column('enhanced_prompt', sa.Text(), nullable=True),
            sa.Column('ai_response', sa.Text(), nullable=True),
            sa.Column('meta_prompt_data', sa.JSON(), nullable=True),  # 存储完整的双重AI调用数据
            
            # 时间戳
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('deployed_at', sa.DateTime(), nullable=True),
            
            # 外键约束 - 引用现有的 users 表
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
        )
        
        # 创建索引
        op.create_index('ix_projects_user_id', 'projects', ['user_id'])
        op.create_index('ix_projects_status', 'projects', ['status'])
        op.create_index('ix_projects_type', 'projects', ['project_type'])
        
        print("  ✅ projects 表创建完成")
    else:
        print("  ⚠️  projects 表已存在，跳过创建")

    # 2. 检查并创建 project_files 表
    if not check_table_exists('project_files'):
        print("  📄 创建 project_files 表...")
        op.create_table('project_files',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
            sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('file_path', sa.String(500), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('file_type', sa.String(50), nullable=True),
            sa.Column('language', sa.String(50), nullable=True),
            sa.Column('size', sa.Integer(), nullable=False, default=0),
            sa.Column('is_entry_point', sa.Boolean(), nullable=False, default=False),
            sa.Column('is_generated', sa.Boolean(), nullable=False, default=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE')
        )
        
        # 创建索引
        op.create_index('ix_project_files_project_id', 'project_files', ['project_id'])
        op.create_index('ix_project_files_type', 'project_files', ['file_type'])
        
        print("  ✅ project_files 表创建完成")
    else:
        print("  ⚠️  project_files 表已存在，跳过创建")

    # 3. 检查并扩展 conversations 表（为了支持项目关联）
    if check_table_exists('conversations'):
        # 检查是否需要添加项目关联字段
        if not check_column_exists('conversations', 'current_project_id'):
            print("  💬 为 conversations 表添加项目关联字段...")
            
            with op.batch_alter_table('conversations', schema=None) as batch_op:
                batch_op.add_column(sa.Column('current_project_id', postgresql.UUID(as_uuid=True), nullable=True))
                batch_op.add_column(sa.Column('conversation_type', sa.String(50), nullable=True, default='general'))
                batch_op.add_column(sa.Column('project_context', sa.JSON(), nullable=True, default=lambda: {}))
            
            # 创建索引
            op.create_index('ix_conversations_project_id', 'conversations', ['current_project_id'])
            op.create_index('ix_conversations_type', 'conversations', ['conversation_type'])
            
            # 添加外键约束
            op.create_foreign_key(
                'fk_conversations_project_id',
                'conversations', 'projects',
                ['current_project_id'], ['id'],
                ondelete='SET NULL'
            )
            
            print("  ✅ conversations 表扩展完成")
        else:
            print("  ⚠️  conversations 表已有项目字段，跳过扩展")
    
    # 4. 检查并扩展 messages 表（为了支持意图识别和AI处理记录）
    if check_table_exists('messages'):
        fields_to_add = [
            ('intent_detected', sa.String(100)),
            ('project_action', sa.String(100)),
            ('ai_processing_data', sa.JSON())  # 存储AI处理过程数据
        ]
        
        fields_added = []
        for field_name, field_type in fields_to_add:
            if not check_column_exists('messages', field_name):
                fields_added.append((field_name, field_type))
        
        if fields_added:
            print(f"  💭 为 messages 表添加 {len(fields_added)} 个新字段...")
            
            with op.batch_alter_table('messages', schema=None) as batch_op:
                for field_name, field_type in fields_added:
                    batch_op.add_column(sa.Column(field_name, field_type, nullable=True))
            
            # 创建索引
            if ('intent_detected', sa.String(100)) in fields_added:
                op.create_index('ix_messages_intent', 'messages', ['intent_detected'])
            if ('project_action', sa.String(100)) in fields_added:
                op.create_index('ix_messages_project_action', 'messages', ['project_action'])
            
            print("  ✅ messages 表扩展完成")
        else:
            print("  ⚠️  messages 表已有所需字段，跳过扩展")

    print("🎉 条件化数据库升级完成！")

def downgrade():
    """安全回滚"""
    print("🔄 开始数据库回滚...")
    
    # 按依赖关系倒序删除
    if check_table_exists('project_files'):
        op.drop_table('project_files')
        print("  ✅ project_files 表已删除")
    
    if check_table_exists('projects'):
        # 先删除相关外键
        try:
            op.drop_constraint('fk_conversations_project_id', 'conversations', type_='foreignkey')
        except:
            pass
        
        op.drop_table('projects')
        print("  ✅ projects 表已删除")
    
    # 删除扩展字段
    if check_table_exists('conversations'):
        try:
            with op.batch_alter_table('conversations', schema=None) as batch_op:
                batch_op.drop_column('project_context')
                batch_op.drop_column('conversation_type')
                batch_op.drop_column('current_project_id')
            print("  ✅ conversations 表扩展字段已删除")
        except:
            pass
    
    if check_table_exists('messages'):
        try:
            with op.batch_alter_table('messages', schema=None) as batch_op:
                batch_op.drop_column('ai_processing_data')
                batch_op.drop_column('project_action')
                batch_op.drop_column('intent_detected')
            print("  ✅ messages 表扩展字段已删除")
        except:
            pass
    
    print("🎉 数据库回滚完成！")