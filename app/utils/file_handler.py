# app/utils/file_handler.py
import os
import mimetypes
from typing import Optional, Dict, Any
import aiofiles
from pathlib import Path

# 尝试导入可选依赖
try:
    import PyPDF2
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False

try:
    import docx
    HAS_DOCX_SUPPORT = True
except ImportError:
    HAS_DOCX_SUPPORT = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def extract_text_from_pdf(file_path: str) -> str:
    """从PDF文件提取文本"""
    if not HAS_PDF_SUPPORT:
        return "PDF support not available. Please install PyPDF2."
    
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            content = []
            for page in pdf_reader.pages:
                content.append(page.extract_text())
            return '\n'.join(content)
    except Exception as e:
        return f"Error reading PDF: {str(e)}"


def extract_text_from_docx(file_path: str) -> str:
    """从Word文档提取文本"""
    if not HAS_DOCX_SUPPORT:
        return "DOCX support not available. Please install python-docx."
    
    try:
        doc = docx.Document(file_path)
        content = []
        for paragraph in doc.paragraphs:
            content.append(paragraph.text)
        return '\n'.join(content)
    except Exception as e:
        return f"Error reading document: {str(e)}"


def extract_text_from_txt(file_path: str) -> str:
    """从文本文件提取内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading text file: {str(e)}"


def extract_text_from_csv(file_path: str) -> str:
    """从CSV文件提取内容"""
    if not HAS_PANDAS:
        # 如果没有pandas，使用基础方法
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading CSV: {str(e)}"
    
    try:
        df = pd.read_csv(file_path)
        return df.to_string()
    except Exception as e:
        return f"Error reading CSV file: {str(e)}"


def extract_text_from_excel(file_path: str) -> str:
    """从Excel文件提取内容"""
    if not HAS_PANDAS:
        return "Excel support not available. Please install pandas."
    
    try:
        df = pd.read_excel(file_path)
        return df.to_string()
    except Exception as e:
        return f"Error reading Excel file: {str(e)}"


async def extract_file_content(file_path: str, mime_type: Optional[str] = None) -> Dict[str, Any]:
    """
    从文件中提取内容
    
    Args:
        file_path: 文件路径
        mime_type: MIME类型
        
    Returns:
        包含提取内容的字典
    """
    if not os.path.exists(file_path):
        return {"type": "error", "content": "File not found"}
    
    if not mime_type:
        mime_type, _ = mimetypes.guess_type(file_path)
    
    file_extension = Path(file_path).suffix.lower()
    
    try:
        # 文本文件
        if mime_type and mime_type.startswith('text/') or file_extension in ['.txt', '.md', '.log']:
            content = extract_text_from_txt(file_path)
            return {"type": "text", "content": content}
        
        # PDF文件
        elif mime_type == 'application/pdf' or file_extension == '.pdf':
            content = extract_text_from_pdf(file_path)
            return {"type": "pdf", "content": content}
        
        # Word文档
        elif mime_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 
                          'application/msword'] or file_extension in ['.docx', '.doc']:
            content = extract_text_from_docx(file_path)
            return {"type": "document", "content": content}
        
        # Excel文件
        elif mime_type in ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                          'application/vnd.ms-excel'] or file_extension in ['.xlsx', '.xls']:
            content = extract_text_from_excel(file_path)
            return {"type": "spreadsheet", "content": content}
        
        # CSV文件
        elif mime_type == 'text/csv' or file_extension == '.csv':
            content = extract_text_from_csv(file_path)
            return {"type": "csv", "content": content}
        
        # 代码文件
        elif file_extension in ['.py', '.js', '.java', '.cpp', '.c', '.go', '.rs', '.php', '.rb']:
            content = extract_text_from_txt(file_path)
            return {"type": "code", "content": content, "language": file_extension[1:]}
        
        # 默认：返回文件信息
        else:
            file_stat = os.stat(file_path)
            return {
                "type": "unsupported",
                "content": f"File type not supported for content extraction",
                "file_info": {
                    "size": file_stat.st_size,
                    "mime_type": mime_type,
                    "extension": file_extension
                }
            }
            
    except Exception as e:
        return {
            "type": "error",
            "content": f"Error extracting file content: {str(e)}"
        }


def get_file_info(file_path: str) -> Dict[str, Any]:
    """获取文件信息"""
    if not os.path.exists(file_path):
        return {"error": "File not found"}
    
    file_stat = os.stat(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    
    return {
        "filename": os.path.basename(file_path),
        "size": file_stat.st_size,
        "mime_type": mime_type,
        "extension": Path(file_path).suffix,
        "created": file_stat.st_ctime,
        "modified": file_stat.st_mtime
    }