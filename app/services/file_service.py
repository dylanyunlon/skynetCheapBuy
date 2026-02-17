import os
import shutil
from typing import Optional, List, Dict, Any
from uuid import UUID
from pathlib import Path
import aiofiles
import magic
from PIL import Image
import pytesseract
import PyPDF2
import docx
import chardet
from sqlalchemy.orm import Session
import aioredis
from app.models.file import File
from app.models.user import  User
from app.config import settings
from app.utils.file_handler import extract_text_from_pdf, extract_text_from_docx

class FileService:
    """文件处理服务"""
    
    def __init__(self, db: Session, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_file_record(
        self,
        user_id: UUID,
        filename: str,
        file_type: str,
        file_size: int,
        file_path: str,
        mime_type: str
    ) -> File:
        """创建文件记录"""
        file_record = File(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            file_path=file_path,
            mime_type=mime_type
        )
        
        self.db.add(file_record)
        self.db.commit()
        self.db.refresh(file_record)
        
        return file_record
    
    async def get_file_by_id(
        self,
        file_id: UUID,
        user_id: UUID
    ) -> Optional[File]:
        """根据ID获取文件"""
        return self.db.query(File).filter(
            File.id == file_id,
            File.user_id == user_id
        ).first()
    
    async def process_file(
        self,
        file_id: UUID,
        file_type: str,
        file_path: str,
        extract_text: bool = True
    ) -> Optional[str]:
        """处理文件内容"""
        try:
            # 更新状态为处理中
            await self.update_file_status(file_id, "processing")
            
            extracted_content = None
            
            if extract_text:
                if file_type == "image":
                    extracted_content = await self._extract_text_from_image(file_path)
                elif file_type == "document":
                    extracted_content = await self._extract_text_from_document(file_path)
                elif file_type == "code":
                    extracted_content = await self._read_text_file(file_path)
            
            # 更新文件记录
            file_record = self.db.query(File).filter(File.id == file_id).first()
            if file_record:
                file_record.extracted_text = extracted_content
                file_record.status = "processed"
                self.db.commit()
            
            return extracted_content
            
        except Exception as e:
            # 更新状态为失败
            await self.update_file_status(
                file_id,
                "failed",
                {"error": str(e)}
            )
            raise
    
    async def _extract_text_from_image(self, file_path: str) -> str:
        """从图像中提取文本（OCR）"""
        try:
            # 打开图像
            image = Image.open(file_path)
            
            # 使用OCR提取文本
            text = pytesseract.image_to_string(image, lang='eng+chi_sim')
            
            return text.strip()
        except Exception as e:
            print(f"OCR错误: {e}")
            return ""
    
    async def _extract_text_from_document(self, file_path: str) -> str:
        """从文档中提取文本"""
        file_ext = Path(file_path).suffix.lower()
        
        try:
            if file_ext == '.pdf':
                return await self._extract_pdf_text(file_path)
            elif file_ext in ['.doc', '.docx']:
                return await self._extract_docx_text(file_path)
            elif file_ext in ['.txt', '.md']:
                return await self._read_text_file(file_path)
            else:
                return ""
        except Exception as e:
            print(f"文档提取错误: {e}")
            return ""
    
    async def _extract_pdf_text(self, file_path: str) -> str:
        """从PDF中提取文本"""
        text = ""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n"
        except Exception as e:
            print(f"PDF提取错误: {e}")
        
        return text.strip()
    
    async def _extract_docx_text(self, file_path: str) -> str:
        """从DOCX中提取文本"""
        try:
            doc = docx.Document(file_path)
            text = []
            for paragraph in doc.paragraphs:
                text.append(paragraph.text)
            return '\n'.join(text)
        except Exception as e:
            print(f"DOCX提取错误: {e}")
            return ""
    
    async def _read_text_file(self, file_path: str) -> str:
        """读取文本文件"""
        try:
            # 检测文件编码
            with open(file_path, 'rb') as file:
                raw_data = file.read()
                encoding = chardet.detect(raw_data)['encoding'] or 'utf-8'
            
            # 读取文件内容
            async with aiofiles.open(file_path, 'r', encoding=encoding) as file:
                content = await file.read()
                return content
        except Exception as e:
            print(f"文本文件读取错误: {e}")
            return ""
    
    async def update_file_status(
        self,
        file_id: UUID,
        status: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """更新文件状态"""
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if file_record:
            file_record.status = status
            if metadata:
                current_metadata = file_record.metadata or {}
                current_metadata.update(metadata)
                file_record.metadata = current_metadata
            self.db.commit()
    
    async def delete_file(self, file_id: UUID, user_id: UUID) -> bool:
        """删除文件"""
        file_record = await self.get_file_by_id(file_id, user_id)
        if not file_record:
            return False
        
        # 删除物理文件
        try:
            if os.path.exists(file_record.file_path):
                os.remove(file_record.file_path)
        except Exception as e:
            print(f"删除文件错误: {e}")
        
        # 删除数据库记录
        self.db.delete(file_record)
        self.db.commit()
        
        return True
    
    async def get_user_files(
        self,
        user_id: UUID,
        file_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[File]:
        """获取用户文件列表"""
        query = self.db.query(File).filter(File.user_id == user_id)
        
        if file_type:
            query = query.filter(File.file_type == file_type)
        
        return query.order_by(File.uploaded_at.desc()).offset(offset).limit(limit).all()
    
    async def get_file_statistics(self, user_id: UUID) -> Dict[str, Any]:
        """获取用户文件统计"""
        stats = {
            "total_files": 0,
            "total_size": 0,
            "by_type": {},
            "by_status": {}
        }
        
        files = self.db.query(File).filter(File.user_id == user_id).all()
        
        for file in files:
            stats["total_files"] += 1
            stats["total_size"] += file.file_size
            
            # 按类型统计
            if file.file_type not in stats["by_type"]:
                stats["by_type"][file.file_type] = {"count": 0, "size": 0}
            stats["by_type"][file.file_type]["count"] += 1
            stats["by_type"][file.file_type]["size"] += file.file_size
            
            # 按状态统计
            if file.status not in stats["by_status"]:
                stats["by_status"][file.status] = 0
            stats["by_status"][file.status] += 1
        
        return stats
    
    async def cleanup_old_files(self, days: int = 30):
        """清理旧文件"""
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        old_files = self.db.query(File).filter(
            File.uploaded_at < cutoff_date
        ).all()
        
        for file in old_files:
            try:
                if os.path.exists(file.file_path):
                    os.remove(file.file_path)
                self.db.delete(file)
            except Exception as e:
                print(f"清理文件错误: {e}")
        
        self.db.commit()
    
    async def validate_file(
        self,
        file_path: str,
        expected_type: str
    ) -> bool:
        """验证文件类型"""
        try:
            # 使用python-magic验证文件类型
            file_mime = magic.from_file(file_path, mime=True)
            
            type_mappings = {
                'image': ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
                'document': ['application/pdf', 'application/msword', 
                           'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                           'text/plain', 'text/markdown'],
                'code': ['text/x-python', 'text/x-java', 'text/x-c++', 'application/json',
                        'text/yaml', 'text/plain'],
                'audio': ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/mp4']
            }
            
            expected_mimes = type_mappings.get(expected_type, [])
            
            return any(mime in file_mime for mime in expected_mimes)
            
        except Exception as e:
            print(f"文件验证错误: {e}")
            return False
    
    async def convert_file_format(
        self,
        file_id: UUID,
        target_format: str
    ) -> Optional[str]:
        """转换文件格式（例如图片格式转换）"""
        file_record = self.db.query(File).filter(File.id == file_id).first()
        if not file_record:
            return None
        
        if file_record.file_type == "image":
            return await self._convert_image_format(
                file_record.file_path,
                target_format
            )
        
        return None
    
    async def _convert_image_format(
        self,
        source_path: str,
        target_format: str
    ) -> str:
        """转换图片格式"""
        try:
            image = Image.open(source_path)
            
            # 生成新文件路径
            source_path_obj = Path(source_path)
            new_path = source_path_obj.with_suffix(f'.{target_format}')
            
            # 转换并保存
            if target_format.upper() == 'JPG':
                target_format = 'JPEG'
            
            image.save(str(new_path), target_format.upper())
            
            return str(new_path)
            
        except Exception as e:
            print(f"图片转换错误: {e}")
            raise