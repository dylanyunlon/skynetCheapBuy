#!/usr/bin/env python3
# claude_code - Claude Code CLI 工具

import asyncio
import click
import sys
from pathlib import Path
from typing import Optional
import json
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.panel import Panel

from app.cli.client import ClaudeCodeClient

console = Console()

@click.group()
@click.option('--api-url', default='http://localhost:8000', help='API URL')
@click.option('--token', envvar='CLAUDE_CODE_TOKEN', help='Authentication token')
@click.pass_context
def cli(ctx, api_url, token):
    """Claude Code - AI驱动的代码生成和执行工具"""
    ctx.ensure_object(dict)
    ctx.obj['client'] = ClaudeCodeClient(api_url, token)

@cli.command()
@click.argument('request')
@click.option('--model', default='claude-opus-4-20250514', help='AI model to use')
@click.option('--execute/--no-execute', default=True, help='Auto execute after generation')
@click.option('--debug/--no-debug', default=True, help='Auto debug on failure')
@click.option('--output', '-o', help='Output directory')
@click.pass_context
async def create(ctx, request, model, execute, debug, output):
    """创建新项目"""
    client = ctx.obj['client']
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # 分析需求
        task = progress.add_task("分析需求...", total=None)
        result = await client.create_project(
            request=request,
            model=model,
            auto_execute=execute,
            max_debug_attempts=3 if debug else 0
        )
        progress.remove_task(task)
    
    if result['success']:
        console.print(f"[green]✓[/green] 项目创建成功！")
        console.print(f"项目ID: {result['project_id']}")
        console.print(f"项目路径: {result['project_path']}")
        
        # 显示文件列表
        table = Table(title="生成的文件")
        table.add_column("文件", style="cyan")
        table.add_column("类型", style="magenta")
        
        for file in result['files']:
            table.add_row(file, "code")
        
        console.print(table)
        
        # 显示执行结果
        if result.get('execution_result'):
            exec_result = result['execution_result']
            if exec_result['success']:
                console.print("\n[green]✓[/green] 执行成功！")
                if exec_result['execution_result']['stdout']:
                    console.print(Panel(
                        exec_result['execution_result']['stdout'],
                        title="输出",
                        border_style="green"
                    ))
            else:
                console.print(f"\n[red]✗[/red] 执行失败 (尝试 {exec_result['attempts']} 次)")
                if exec_result['last_error']['stderr']:
                    console.print(Panel(
                        exec_result['last_error']['stderr'],
                        title="错误",
                        border_style="red"
                    ))
        
        # 复制到输出目录
        if output:
            await client.export_project(result['project_id'], output)
            console.print(f"\n[green]✓[/green] 项目已导出到: {output}")
    else:
        console.print(f"[red]✗[/red] 创建失败: {result.get('error', 'Unknown error')}")

@cli.command()
@click.argument('project_id')
@click.option('--max-attempts', default=3, help='Maximum debug attempts')
@click.pass_context
async def run(ctx, project_id, max_attempts):
    """运行项目"""
    client = ctx.obj['client']
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("执行项目...", total=None)
        result = await client.execute_project(
            project_id=project_id,
            max_debug_attempts=max_attempts
        )
        progress.remove_task(task)
    
    if result['success']:
        console.print(f"[green]✓[/green] 执行成功！")
        if result['stdout']:
            console.print(Panel(result['stdout'], title="输出", border_style="green"))
    else:
        console.print(f"[red]✗[/red] 执行失败")
        if result['stderr']:
            console.print(Panel(result['stderr'], title="错误", border_style="red"))

@cli.command()
@click.argument('project_id')
@click.argument('file_path')
@click.pass_context
async def show(ctx, project_id, file_path):
    """显示项目文件内容"""
    client = ctx.obj['client']
    
    content = await client.get_file_content(project_id, file_path)
    
    # 使用语法高亮显示
    syntax = Syntax(content, "python", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=f"{file_path}", border_style="blue"))

@cli.command()
@click.argument('project_id')
@click.argument('file_path')
@click.option('--prompt', '-p', required=True, help='Edit instruction')
@click.pass_context
async def edit(ctx, project_id, file_path, prompt):
    """编辑项目文件"""
    client = ctx.obj['client']
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("修改文件...", total=None)
        result = await client.edit_file(
            project_id=project_id,
            file_path=file_path,
            edit_prompt=prompt
        )
        progress.remove_task(task)
    
    if result['success']:
        console.print(f"[green]✓[/green] 文件修改成功！")
        
        # 显示修改内容
        syntax = Syntax(result['new_content'], "python", theme="monokai")
        console.print(Panel(syntax, title=f"修改后的 {file_path}", border_style="green"))
    else:
        console.print(f"[red]✗[/red] 修改失败: {result.get('error', 'Unknown error')}")

@cli.command()
@click.pass_context
async def list(ctx):
    """列出所有项目"""
    client = ctx.obj['client']
    
    projects = await client.list_projects()
    
    if projects:
        table = Table(title="项目列表")
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="magenta")
        table.add_column("类型", style="green")
        table.add_column("创建时间", style="yellow")
        
        for project in projects:
            table.add_row(
                project['id'][:8],
                project['name'],
                project['type'],
                project['created_at']
            )
        
        console.print(table)
    else:
        console.print("[yellow]没有找到项目[/yellow]")

def main():
    """主函数"""
    try:
        cli(_anyio_backend="asyncio")
    except Exception as e:
        console.print(f"[red]错误: {e}[/red]")
        sys.exit(1)

if __name__ == '__main__':
    main()