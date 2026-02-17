from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import List, Optional
import aiofiles
import os
import hashlib
from pathlib import Path

from app.core.auth import get_current_user
from app.models.user import User
from app.services.file_service import FileService
from app.schemas.file import FileResponse as FileResponseSchema, FileUploadResponse
from app.dependencies import get_file_service
from app.config import settings

router = APIRouter(prefix="/api/files", tags=["files"])

# 允许的文件类型和大小限制
ALLOWED_EXTENSIONS = {
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp'],
    'document': ['.pdf', '.txt', '.doc', '.docx', '.md'],
    'code': ['.py', '.js', '.ts', '.java', '.cpp', '.yml', '.yaml', '.json'],
    'audio': ['.mp3', '.wav', '.ogg', '.m4a']
}

MAX_FILE_SIZE = {
    'image': 10 * 1024 * 1024,      # 10MB
    'document': 50 * 1024 * 1024,    # 50MB
    'code': 5 * 1024 * 1024,         # 5MB
    'audio': 20 * 1024 * 1024        # 20MB
}

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: Optional[str] = Form(None),
    process_immediately: bool = Form(True),
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    上传文件
    
    - **file**: 要上传的文件
    - **conversation_id**: 关联的会话ID（可选）
    - **process_immediately**: 是否立即处理文件内容
    """
    # 验证文件扩展名
    file_ext = Path(file.filename).suffix.lower()
    file_type = None
    
    for ftype, extensions in ALLOWED_EXTENSIONS.items():
        if file_ext in extensions:
            file_type = ftype
            break
    
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}"
        )
    
    # 验证文件大小
    file_size = 0
    contents = await file.read()
    file_size = len(contents)
    
    if file_size > MAX_FILE_SIZE.get(file_type, 10 * 1024 * 1024):
        raise HTTPException(
            status_code=413,
            detail=f"文件太大。最大允许大小: {MAX_FILE_SIZE[file_type] / 1024 / 1024}MB"
        )
    
    # 生成文件哈希和存储路径
    file_hash = hashlib.sha256(contents).hexdigest()
    file_dir = os.path.join(settings.UPLOAD_DIR, str(current_user.id), file_type)
    os.makedirs(file_dir, exist_ok=True)
    
    file_path = os.path.join(file_dir, f"{file_hash}{file_ext}")
    
    # 保存文件
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(contents)
    
    # 重置文件指针
    await file.seek(0)
    
    # 创建文件记录
    file_record = await file_service.create_file_record(
        user_id=current_user.id,
        filename=file.filename,
        file_type=file_type,
        file_size=file_size,
        file_path=file_path,
        mime_type=file.content_type
    )
    
    # 处理文件内容
    extracted_content = None
    if process_immediately:
        try:
            extracted_content = await file_service.process_file(
                file_id=file_record.id,
                file_type=file_type,
                file_path=file_path
            )
        except Exception as e:
            # 记录错误但不中断上传
            await file_service.update_file_status(
                file_id=file_record.id,
                status="failed",
                metadata={"error": str(e)}
            )
    
    return FileUploadResponse(
        id=str(file_record.id),
        filename=file_record.filename,
        file_type=file_record.file_type,
        file_size=file_record.file_size,
        uploaded_at=file_record.uploaded_at,
        status=file_record.status,
        extracted_content=extracted_content,
        conversation_id=conversation_id
    )

@router.post("/upload-multiple", response_model=List[FileUploadResponse])
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    conversation_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    上传多个文件
    """
    if len(files) > 10:
        raise HTTPException(
            status_code=400,
            detail="一次最多上传10个文件"
        )
    
    results = []
    for file in files:
        try:
            result = await upload_file(
                file=file,
                conversation_id=conversation_id,
                process_immediately=True,
                current_user=current_user,
                file_service=file_service
            )
            results.append(result)
        except Exception as e:
            # 继续处理其他文件
            results.append({
                "filename": file.filename,
                "status": "failed",
                "error": str(e)
            })
    
    return results

@router.get("/{file_id}", response_model=FileResponseSchema)
async def get_file_info(
    file_id: str,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    获取文件信息
    """
    file_record = await file_service.get_file_by_id(
        file_id=file_id,
        user_id=current_user.id
    )
    
    if not file_record:
        raise HTTPException(
            status_code=404,
            detail="文件不存在"
        )
    
    return FileResponseSchema.from_orm(file_record)

@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    下载文件
    """
    file_record = await file_service.get_file_by_id(
        file_id=file_id,
        user_id=current_user.id
    )
    
    if not file_record:
        raise HTTPException(
            status_code=404,
            detail="文件不存在"
        )
    
    if not os.path.exists(file_record.file_path):
        raise HTTPException(
            status_code=404,
            detail="文件已被删除"
        )
    
    return FileResponse(
        path=file_record.file_path,
        filename=file_record.filename,
        media_type=file_record.mime_type
    )

@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    删除文件
    """
    success = await file_service.delete_file(
        file_id=file_id,
        user_id=current_user.id
    )
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="文件不存在或无权删除"
        )
    
    return {"status": "success", "message": "文件已删除"}

@router.post("/{file_id}/process")
async def process_file(
    file_id: str,
    extract_text: bool = True,
    current_user: User = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    """
    处理文件内容（提取文本、OCR等）
    """
    file_record = await file_service.get_file_by_id(
        file_id=file_id,
        user_id=current_user.id
    )
    
    if not file_record:
        raise HTTPException(
            status_code=404,
            detail="文件不存在"
        )
    
    try:
        extracted_content = await file_service.process_file(
            file_id=file_record.id,
            file_type=file_record.file_type,
            file_path=file_record.file_path,
            extract_text=extract_text
        )
        
        return {
            "status": "success",
            "extracted_content": extracted_content,
            "metadata": file_record.metadata
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"处理文件时出错: {str(e)}"
        )