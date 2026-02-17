# scripts/manage_db.py
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
import logging
from alembic import command
from alembic.config import Config
from app.db.init_db import init_db, init_data, reset_database, check_tables_exist
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@click.group()
def cli():
    """数据库管理命令行工具"""
    pass

@cli.command()
def init():
    """初始化数据库表"""
    click.echo("Initializing database...")
    init_db()
    click.echo("Database initialized successfully!")

@cli.command()
def seed():
    """填充初始数据"""
    click.echo("Seeding initial data...")
    init_data()
    click.echo("Initial data seeded successfully!")

@cli.command()
def reset():
    """重置数据库（慎用！）"""
    if settings.ENVIRONMENT == "production":
        click.echo("Cannot reset database in production environment!")
        return
    
    if click.confirm("Are you sure you want to reset the database? This will delete all data!"):
        reset_database()
        click.echo("Database reset successfully!")

@cli.command()
def check():
    """检查数据库状态"""
    click.echo("Checking database status...")
    if check_tables_exist():
        click.echo("All required tables exist.")
    else:
        click.echo("Some tables are missing. Run 'init' to create them.")

@cli.command()
@click.option('--message', '-m', required=True, help='Migration message')
def migrate(message):
    """创建新的数据库迁移"""
    alembic_cfg = Config("alembic.ini")
    command.revision(alembic_cfg, autogenerate=True, message=message)
    click.echo(f"Migration created: {message}")

@cli.command()
def upgrade():
    """应用数据库迁移"""
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    click.echo("Database upgraded to latest migration!")

@cli.command()
def downgrade():
    """回滚上一个迁移"""
    alembic_cfg = Config("alembic.ini")
    command.downgrade(alembic_cfg, "-1")
    click.echo("Database downgraded by one migration!")

if __name__ == "__main__":
    cli()