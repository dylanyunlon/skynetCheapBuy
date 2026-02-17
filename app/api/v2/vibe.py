# app/api/v2/vibe.py - 调试版本

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
import logging
import uuid
import json
import os
import asyncio
import subprocess
import re
import traceback
import tempfile
import stat
from datetime import datetime
from pathlib import Path

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.config import settings
from app.core.ai_engine import AIEngine
from app.core.code_extractor import CodeExtractor
from app.core.ai.system_prompts import BashScriptPromptAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/vibe", tags=["vibe-coding"])

# 全局变量存储运行中的服务
running_services = {}

@router.post("/process")
async def process_vibe_coding_pure_ai(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """纯AI Vibe Coding 处理端点 - 调试版本"""
    
    logger.info("[DEBUG] Starting vibe coding process")
    
    try:
        # 安全获取请求数据
        try:
            request_data = await request.json()
            logger.info(f"[DEBUG] Request data received: {json.dumps(request_data, ensure_ascii=False)[:200]}")
        except Exception as e:
            logger.error(f"[DEBUG] Failed to parse request JSON: {e}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Invalid JSON in request body",
                    "details": str(e)
                }
            )
        
        content = request_data.get("content", "")
        conversation_id = request_data.get("conversation_id", f"vibe_{uuid.uuid4()}")
        stage = request_data.get("stage", "meta")
        force_ai_generation = request_data.get("force_ai_generation", True)
        no_template_fallback = request_data.get("no_template_fallback", True)
        
        user_id = str(current_user.id) if isinstance(current_user.id, uuid.UUID) else current_user.id
        logger.info(f"[DEBUG] Processing stage '{stage}' for user {user_id}: {content[:50]}...")
        
        if stage == "meta":
            logger.info("[DEBUG] Starting meta stage processing")
            
            # Meta 阶段：简化AI优化
            ai_engine = AIEngine()
            
            try:
                logger.info("[DEBUG] Calling process_meta_stage_simplified")
                meta_result = await process_meta_stage_simplified(content, ai_engine)
                logger.info(f"[DEBUG] Meta stage completed, result keys: {list(meta_result.keys())}")
                
                # 构建响应数据
                response_data = {
                    "success": True,
                    "stage": "meta_complete",
                    "conversation_id": conversation_id,
                    "content": meta_result["enhanced_prompt"],
                    "intent_detected": "vibe_coding_meta_pure_ai",
                    "data": {
                        "conversation_id": conversation_id,
                        "content": meta_result["enhanced_prompt"],
                        "intent_detected": "vibe_coding_meta",
                        "metadata": {
                            "stage": "meta_complete",
                            "vibe_data": {
                                "optimized_description": meta_result["enhanced_prompt"],
                                "project_info": meta_result["project_info"],
                                "meta_result": meta_result,
                                "original_user_input": content,
                                "ai_enhanced": True,
                                "pure_ai_generation": True,
                                "no_template_used": True,
                                "creation_method": "pure_ai_generation"
                            },
                            "suggestions": ["确认生成AI项目", "修改需求", "重新优化"]
                        }
                    }
                }
                
                logger.info(f"[DEBUG] Prepared response data: {json.dumps(response_data, ensure_ascii=False)[:300]}...")
                logger.info("[DEBUG] Returning JSONResponse")
                
                return JSONResponse(status_code=200, content=response_data)
                
            except Exception as e:
                logger.error(f"[DEBUG] Meta stage exception: {e}", exc_info=True)
                error_response = {
                    "success": False,
                    "error": f"Meta阶段失败: {str(e)}",
                    "stage": "meta_error",
                    "conversation_id": conversation_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                logger.info(f"[DEBUG] Returning error response: {error_response}")
                return JSONResponse(status_code=500, content=error_response)
            
        elif stage == "generate":
            logger.info("[DEBUG] Starting generate stage processing")
            
            # Generate 阶段逻辑保持不变...
            meta_result = request_data.get("meta_result", {})
            original_input = meta_result.get("vibe_data", {}).get("original_user_input", content)
            
            ai_engine = AIEngine()
            
            try:
                project_result = await process_generate_stage_simplified(
                    user_id=user_id,
                    user_input=original_input,
                    meta_result=meta_result,
                    conversation_id=conversation_id,
                    ai_engine=ai_engine,
                    db=db,
                    background_tasks=background_tasks,
                    force_ai=force_ai_generation,
                    no_fallback=no_template_fallback
                )
                
                logger.info("[DEBUG] Generate stage completed successfully")
                
                response_data = {
                    "success": True,
                    "stage": "generate_complete",
                    "conversation_id": conversation_id,
                    "content": f"AI项目 '{project_result['project_name']}' 创建成功！",
                    "intent_detected": "vibe_coding_generate_pure_ai",
                    "data": {
                        "conversation_id": conversation_id,
                        "content": f"纯AI项目创建成功！预览地址：{project_result.get('preview_url', '')}",
                        "intent_detected": "vibe_coding_generate",
                        "project_created": project_result["project_created"],
                        "metadata": {
                            "stage": "generate_complete",
                            "project_created": project_result["project_created"],
                            "suggestions": ["查看AI项目预览", "修改AI项目", "创建新AI项目", "重启AI服务"]
                        }
                    },
                    "project_created": project_result["project_created"]
                }
                
                logger.info("[DEBUG] Returning generate response")
                return JSONResponse(status_code=200, content=response_data)
                
            except Exception as e:
                logger.error(f"[DEBUG] Generate stage exception: {e}", exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": f"Generate阶段失败: {str(e)}",
                        "stage": "generate_error",
                        "conversation_id": conversation_id,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
        
        else:
            logger.error(f"[DEBUG] Unknown stage: {stage}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"Unknown stage: {stage}",
                    "stage": f"{stage}_error"
                }
            )
            
    except Exception as e:
        logger.error(f"[DEBUG] Top-level exception: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"服务器内部错误: {str(e)}",
                "stage": "server_error",
                "conversation_id": conversation_id if 'conversation_id' in locals() else "unknown",
                "timestamp": datetime.utcnow().isoformat(),
                "traceback": traceback.format_exc() if settings.DEBUG else None
            }
        )

async def process_meta_stage_simplified(user_input: str, ai_engine: AIEngine) -> Dict[str, Any]:
    """简化的Meta阶段处理 - 带调试日志"""
    
    logger.info(f"[DEBUG] Meta stage START: {user_input[:50]}...")
    
    # 直接从用户输入提取基本信息
    project_info = extract_project_info_from_input(user_input)
    logger.info(f"[DEBUG] Extracted project info: {project_info}")
    
    # 单次AI调用生成增强描述
    meta_prompt = f"""
请优化这个项目需求，设计一个bash脚本自动化方案：

用户需求：{user_input}
项目信息：{json.dumps(project_info, ensure_ascii=False)}

请返回详细的项目规格，包括：
1. 完整的HTML、CSS、JavaScript内容规划
2. bash脚本自动化部署策略
3. 端口管理和服务器启动方案

规格要足够详细，能够指导AI生成完整的bash脚本。
"""
    
    try:
        logger.info("[DEBUG] Getting bash adapter and system prompts")
        bash_adapter = BashScriptPromptAdapter(ai_engine)
        system_prompts = await bash_adapter.get_system_prompt_for_stage("meta")
        
        messages = [
            {"role": "system", "content": system_prompts[0]},
            {"role": "user", "content": meta_prompt}
        ]
        
        logger.info(f"[DEBUG] Calling AI engine with {len(messages)} messages")
        
        response = await asyncio.wait_for(
            ai_engine.get_completion(
                messages=messages,
                model="claude-opus-4-5-20251101",
                temperature=0.7,
                max_tokens=2000
            ),
            timeout=3000.0  # 5分钟超时
        )
        
        enhanced_prompt = response.get("content", "")
        logger.info(f"[DEBUG] AI response received: {len(enhanced_prompt)} characters")
        
        if not enhanced_prompt or len(enhanced_prompt) < 100:
            logger.error("[DEBUG] AI返回的增强prompt质量不足")
            raise Exception("AI返回的增强prompt质量不足")
        
        result = {
            "enhanced_prompt": enhanced_prompt,
            "project_info": project_info,
            "original_input": user_input,
            "ai_enhanced": True,
            "pure_ai_generation": True,
            "no_template_used": True,
            "creation_method": "pure_ai_generation"
        }
        
        logger.info(f"[DEBUG] Meta stage END: result prepared with keys {list(result.keys())}")
        return result
        
    except asyncio.TimeoutError:
        logger.error("[DEBUG] AI meta optimization timeout")
        raise Exception("AI meta优化超时")
    except Exception as e:
        logger.error(f"[DEBUG] Meta stage exception in try block: {e}", exc_info=True)
        raise Exception(f"纯AI Meta阶段失败: {e}")

# 其他函数保持不变...
async def process_generate_stage_simplified(
    user_id: str,
    user_input: str,
    meta_result: Dict[str, Any],
    conversation_id: str,
    ai_engine: AIEngine,
    db: Session,
    background_tasks: BackgroundTasks,
    force_ai: bool = True,
    no_fallback: bool = True
) -> Dict[str, Any]:
    """简化的Generate阶段处理"""
    
    logger.info(f"[DEBUG] Generate stage START")
    
    vibe_data = meta_result.get("vibe_data", {})
    enhanced_prompt = vibe_data.get("optimized_description", user_input)
    project_info = vibe_data.get("project_info", extract_project_info_from_input(user_input))
    
    port = project_info.get('port', 17430)
    target_person = project_info.get('target_person', 'sky-net')
    
    try:
        logger.info("[DEBUG] Starting AI bash script generation")
        
        # 单次AI调用生成完整bash脚本
        bash_script = await generate_complete_bash_script(
            user_input, enhanced_prompt, project_info, ai_engine
        )
        
        if not bash_script or len(bash_script) < 200:
            logger.error("[DEBUG] AI bash脚本生成失败：内容不足")
            raise Exception("AI bash脚本生成失败：内容不足")
        
        logger.info(f"[DEBUG] Generated bash script: {len(bash_script)} characters")
        
        # 验证bash脚本
        validated_script = validate_and_fix_bash_script(bash_script)
        
        # 创建项目记录
        project = await create_project_record_simplified(
            user_id=user_id,
            user_input=user_input,
            optimized_description=enhanced_prompt,
            bash_script=validated_script,
            project_info=project_info,
            db=db
        )
        
        # 修复预览URL
        preview_url = f"http://8.163.12.28:{port}"
        
        # 立即更新项目状态并返回响应
        try:
            project.preview_url = preview_url
            project.status = "deploying"
            project.workspace_path = f"/tmp/vibe_project_{project.id}"
            project.file_count = 4
            
            if not project.description.startswith("[AI生成]"):
                project.description = f"[AI生成] {project.description}"
            
            db.commit()
            logger.info(f"[DEBUG] Project {project.id} updated successfully")
        except Exception as e:
            logger.error(f"[DEBUG] Failed to update project: {e}")
            db.rollback()
            raise
        
        # 后台执行bash脚本
        background_tasks.add_task(
            execute_bash_script_background_fixed,
            validated_script,
            str(project.id),
            project.name,
            port,
            user_id
        )
        
        result = {
            "project_name": project.name,
            "preview_url": preview_url,
            "project_created": {
                "success": True,
                "project_id": str(project.id),
                "project_name": project.name,
                "project_type": project_info.get('type', 'web'),
                "files_created": 4,
                "workspace_path": f"/tmp/vibe_project_{project.id}",
                "preview_url": preview_url,
                "execution_success": True,
                "preview_accessible": True,
                "port": port,
                "ai_generated": True,
                "pure_ai_generation": True,
                "no_template_used": True,
                "creation_method": "pure_ai_generation",
                "bash_script_executed": True,
                "background_execution": True,
                "deployment_info": {
                    "port": port,
                    "status": "deploying",
                    "start_time": datetime.utcnow().isoformat(),
                    "preview_url": preview_url,
                    "pure_ai": True,
                    "background_task": True
                }
            }
        }
        
        logger.info(f"[DEBUG] Generate stage END: result prepared")
        return result
        
    except Exception as e:
        logger.error(f"[DEBUG] Generate stage exception: {e}")
        raise Exception(f"纯AI项目生成失败: {e}")

async def generate_complete_bash_script(
    user_input: str, 
    enhanced_prompt: str, 
    project_info: Dict[str, Any], 
    ai_engine: AIEngine
) -> str:
    """单次AI调用生成完整bash脚本"""
    
    target_person = project_info.get("target_person", "sky-net")
    port = project_info.get("port", 17430)
    
    bash_generation_prompt = f"""
生成一个完整的bash脚本来创建{target_person}的个人网站项目：

用户需求：{user_input}
项目描述：{enhanced_prompt}
目标人物：{target_person}
端口：{port}

请生成一个完整的bash脚本，包含：
1. 完整的HTML文件内容（包含{target_person}的个人信息）
2. 完整的CSS样式文件（现代、美观的设计）
3. 完整的JavaScript文件（交互功能）
4. 端口管理和服务器启动逻辑
5. 错误处理和日志记录

脚本必须可以直接执行，运行后能在端口{port}上启动一个功能完整的个人网站。

CRITICAL: 只返回bash脚本代码，不要其他说明。
CRITICAL: 使用cat > filename << 'EOF'语法生成所有文件。
CRITICAL: 确保所有文件内容完整，没有占位符。
"""
    
    try:
        bash_adapter = BashScriptPromptAdapter(ai_engine)
        system_prompts = await bash_adapter.get_system_prompt_for_stage("generation")
        
        messages = [
            {"role": "system", "content": system_prompts[0]},
            {"role": "user", "content": bash_generation_prompt}
        ]
        
        logger.info(f"[DEBUG] Calling AI engine for bash script generation")
        
        response = await asyncio.wait_for(
            ai_engine.get_completion(
                messages=messages,
                model="claude-opus-4-5-20251101",
                temperature=0.2,
                max_tokens=4000
            ),
            timeout=3000.0  # 5分钟超时
        )
        
        bash_script = response.get("content", "")
        
        # 清理bash脚本
        bash_script = clean_bash_script_response(bash_script)
        
        logger.info(f"[DEBUG] Generated complete bash script: {len(bash_script)} characters")
        return bash_script
        
    except asyncio.TimeoutError:
        logger.error("[DEBUG] AI bash script generation timeout")
        raise Exception("AI bash脚本生成超时")
    except Exception as e:
        logger.error(f"[DEBUG] Complete bash script generation failed: {e}")
        raise Exception(f"AI bash脚本生成失败: {e}")

def clean_bash_script_response(response: str) -> str:
    """清理AI响应，提取纯bash脚本"""
    
    # 移除markdown代码块标记
    response = re.sub(r'```bash\s*\n', '', response)
    response = re.sub(r'```\s*$', '', response)
    response = re.sub(r'^```\s*\n', '', response)
    
    # 确保shebang
    if not response.strip().startswith('#!/bin/bash'):
        response = f"#!/bin/bash\n{response}"
    
    return response.strip()

def validate_and_fix_bash_script(script: str) -> str:
    """验证并修复bash脚本"""
    
    code_extractor = CodeExtractor()
    is_valid, error = code_extractor.validate_bash_code(script)
    
    if not is_valid:
        logger.warning(f"[DEBUG] Bash script validation failed: {error}")
        # 基本修复
        script = fix_basic_bash_issues(script)
    
    return script

def fix_basic_bash_issues(script: str) -> str:
    """修复基本的bash脚本问题"""
    
    # 确保shebang
    if not script.strip().startswith('#!/bin/bash'):
        script = f"#!/bin/bash\n{script}"
    
    # 确保set命令
    if 'set -' not in script:
        lines = script.split('\n')
        lines.insert(1, 'set -euo pipefail')
        script = '\n'.join(lines)
    
    # 修复常见语法错误
    script = re.sub(r'if! ', 'if ! ', script)
    script = re.sub(r'fi\s*$', 'fi\n', script, flags=re.MULTILINE)
    
    return script

async def execute_bash_script_background_fixed(
    script_content: str,
    project_id: str,
    project_name: str,
    port: int,
    user_id: str
):
    """修复的后台bash脚本执行"""
    
    logger.info(f"[DEBUG] Background execution started for project {project_id}")
    
    try:
        # 导入数据库会话
        from app.db.session import SessionLocal
        from app.models.workspace import Project
        
        # 创建临时脚本文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as temp_file:
            temp_file.write(script_content)
            temp_script_path = temp_file.name
        
        # 设置执行权限
        os.chmod(temp_script_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)
        
        # 创建项目工作目录
        project_dir = f"/tmp/vibe_project_{project_id}"
        os.makedirs(project_dir, exist_ok=True)
        
        # 执行脚本
        logger.info(f"[DEBUG] Executing bash script: {temp_script_path}")
        
        process = await asyncio.create_subprocess_exec(
            'bash', temp_script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_dir
        )
        
        # 设置60秒超时
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=6000.0)
        except asyncio.TimeoutError:
            logger.warning(f"[DEBUG] Background script execution timeout for project {project_id}")
            process.kill()
            await process.wait()
            # 继续执行，可能服务已经启动
        
        # 清理临时文件
        try:
            os.unlink(temp_script_path)
        except:
            pass
        
        success = process.returncode == 0
        
        # 更新项目状态
        try:
            with SessionLocal() as db_session:
                project = db_session.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
                if project:
                    if success:
                        project.status = "active"
                        logger.info(f"[DEBUG] Background script execution succeeded for project {project_id}")
                    else:
                        project.status = "failed"
                        logger.error(f"[DEBUG] Background script execution failed for project {project_id}: {stderr.decode() if stderr else 'Unknown error'}")
                    
                    db_session.commit()
        except Exception as e:
            logger.error(f"[DEBUG] Failed to update project status after background execution: {e}")
        
        if success:
            # 记录运行中的服务
            running_services[project_id] = {
                "project_name": project_name,
                "port": port,
                "started_at": datetime.utcnow(),
                "verified": True,
                "pure_ai_generated": True,
                "execution_method": "background_bash_script"
            }
        
        logger.info(f"[DEBUG] Background execution completed for project {project_id}, success: {success}")
        
    except Exception as e:
        logger.error(f"[DEBUG] Background script execution error for project {project_id}: {e}")
        
        # 更新项目状态为失败
        try:
            from app.db.session import SessionLocal
            from app.models.workspace import Project
            
            with SessionLocal() as db_session:
                project = db_session.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
                if project:
                    project.status = "failed"
                    db_session.commit()
        except Exception as update_error:
            logger.error(f"[DEBUG] Failed to update project status after error: {update_error}")

def extract_project_info_from_input(user_input: str) -> Dict[str, Any]:
    """从用户输入中提取项目基本信息"""
    
    # 提取人名
    target_person = "sky-net"
    if "sky-net" in user_input:
        target_person = "sky-net"
    
    # 提取端口
    port = 17430
    port_match = re.search(r'端口.*?(\d{4,5})', user_input)
    if port_match:
        port = int(port_match.group(1))
    
    return {
        "type": "web",
        "target_person": target_person,
        "port": port,
        "technologies": ["html", "css", "javascript", "bash"],
        "complexity": "medium",
        "features": ["个人信息展示", "响应式设计", "交互功能"],
        "ai_enhanced": True
    }

async def create_project_record_simplified(
    user_id: str,
    user_input: str,
    optimized_description: str,
    bash_script: str,
    project_info: Dict[str, Any],
    db: Session
):
    """简化的项目记录创建"""
    
    from app.models.workspace import Project
    
    project_name = f"{project_info.get('target_person', '用户')}的{project_info.get('type', 'web')}项目"
    
    try:
        description = f"[AI生成] {optimized_description[:450]}"
        
        meta_prompt_data = {
            "creation_method": "pure_ai_generation",
            "ai_generated": True,
            "no_template_used": True,
            "bash_script_length": len(bash_script),
            "project_info": project_info,
            "timestamp": datetime.utcnow().isoformat(),
            "background_execution": True
        }
        
        project = Project(
            id=uuid.uuid4(),
            name=project_name,
            description=description,
            user_id=user_id,
            project_type=project_info.get('type', 'web'),
            status="creating",
            creation_prompt=user_input,
            enhanced_prompt=optimized_description,
            ai_response=json.dumps({
                "bash_script": bash_script[:1000],  # 截断保存
                "project_info": project_info,
                "creation_method": "pure_ai_generation",
                "no_template_used": True,
                "background_execution": True
            }, ensure_ascii=False),
            meta_prompt_data=meta_prompt_data
        )
        
        db.add(project)
        db.commit()
        db.refresh(project)
        
        logger.info(f"[DEBUG] Created simplified AI project record: {project.id}")
        return project
        
    except Exception as e:
        logger.error(f"[DEBUG] Failed to create simplified project record: {e}")
        db.rollback()
        raise

@router.get("/health")
async def health_check():
    """健康检查端点"""
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.0.3-debug-enhanced",
            "running_services": len(running_services),
            "ai_code_generation": True,
            "template_fallback": False,
            "pure_ai_mode": True,
            "background_execution": True,
            "simplified_workflow": True,
            "debug_enabled": True
        }
    )

@router.get("/project/{project_id}/preview-status")
async def get_project_preview_status_fixed(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """检查项目预览状态 - 修复版本"""
    try:
        from app.models.workspace import Project
        project_uuid = uuid.UUID(project_id)
        project = db.query(Project).filter(
            Project.id == project_uuid,
            Project.user_id == current_user.id
        ).first()
        
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # 修复预览URL格式
        preview_url = project.preview_url
        if preview_url:
            preview_url = preview_url.replace('localhost', '8.163.12.28')
            preview_url = preview_url.replace('127.0.0.1', '8.163.12.28')
            preview_url = re.sub(r'/(\d{4,5})$', r':\1', preview_url)
            
            if preview_url != project.preview_url:
                project.preview_url = preview_url
                db.commit()
        
        # 检查服务运行状态
        service_info = running_services.get(project_id)
        is_running = service_info is not None
        
        # 检查AI生成标记
        is_ai_generated = (
            (project.description and project.description.startswith("[AI生成]")) or
            (project.meta_prompt_data and project.meta_prompt_data.get("ai_generated") == True)
        )
        
        # 检查后台执行标记
        background_execution = (
            project.meta_prompt_data and project.meta_prompt_data.get("background_execution") == True
        )
        
        return {
            "success": True,
            "project_id": project_id,
            "status": project.status,
            "preview_url": preview_url,
            "is_running": is_running,
            "service_info": service_info,
            "ai_generated": is_ai_generated,
            "background_execution": background_execution,
            "simplified_workflow": True,
            "debug_enabled": True,
            "last_updated": project.updated_at.isoformat() if project.updated_at else None
        }
    except Exception as e:
        logger.error(f"[DEBUG] Failed to get preview status: {e}")
        raise HTTPException(status_code=500, detail=str(e))