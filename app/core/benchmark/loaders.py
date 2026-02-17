# app/core/benchmark/loaders_enhanced.py
# 增强版Benchmark任务加载器
# 支持: GitTaskBench (54 tasks), SWE-bench Verified (500 tasks), MLE-bench (75 tasks)
# 兼容现有loaders.py

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging
import json
import os

logger = logging.getLogger(__name__)


class BenchmarkType(str, Enum):
    """Benchmark类型枚举"""
    # SWE-bench系列
    SWE_BENCH = "swe_bench"
    SWE_BENCH_VERIFIED = "swe_bench_verified"
    SWE_BENCH_LITE = "swe_bench_lite"
    # MLE-bench系列
    MLE_BENCH = "mle_bench"
    MLE_BENCH_LITE = "mle_bench_lite"
    # GitTaskBench
    GITTASKBENCH = "gittaskbench"
    # 自定义
    CUSTOM = "custom"


@dataclass
class BenchmarkTaskInstance:
    """Benchmark任务实例"""
    id: str
    name: str
    description: str
    difficulty: str  # easy, medium, hard, expert
    domain: str
    modality: Optional[str] = None
    
    # 仓库信息
    repo_url: Optional[str] = None
    base_commit: Optional[str] = None
    
    # SWE-bench特有
    problem_statement: Optional[str] = None
    hints_text: Optional[str] = None
    test_patch: Optional[str] = None
    fail_to_pass: Optional[List[str]] = None
    pass_to_pass: Optional[List[str]] = None
    
    # MLE-bench特有
    competition_id: Optional[str] = None
    metric: Optional[str] = None
    dataset_size_mb: Optional[float] = None
    
    # GitTaskBench特有
    success_criteria: Optional[Dict[str, Any]] = None
    evaluation_script: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    expected_output: Optional[str] = None
    market_value_usd: Optional[float] = None
    
    # 通用元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


# ==================== GitTaskBench 任务定义 ====================
# 基于论文: 54 tasks across 7 domains

GITTASKBENCH_TASKS = [
    # ========== Image Processing (16 tasks) ==========
    # Style Transfer
    BenchmarkTaskInstance(
        id="gittaskbench_animegan_style_01",
        name="AnimeGAN 动漫风格迁移",
        description="使用AnimeGAN将真实照片转换为动漫风格图像",
        difficulty="medium",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/TachibanaYoshino/AnimeGANv3",
        success_criteria={"type": "image_quality", "metric": "CIEDE2000", "threshold": 2.0},
        market_value_usd=50.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_neural_style_01",
        name="神经风格迁移",
        description="使用神经网络将艺术风格应用到目标图像",
        difficulty="medium",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/jcjohnson/neural-style",
        success_criteria={"type": "image_quality", "metric": "SSIM", "threshold": 0.7},
        market_value_usd=60.0
    ),
    # Image Restoration
    BenchmarkTaskInstance(
        id="gittaskbench_basicsr_restore_01",
        name="图像超分辨率重建",
        description="使用BasicSR进行图像超分辨率重建，提升图像清晰度",
        difficulty="hard",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/XPixelGroup/BasicSR",
        success_criteria={"type": "image_quality", "metric": "PSNR", "threshold": 25.0},
        market_value_usd=80.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_descratch_01",
        name="图像划痕去除",
        description="使用DeScratch模型去除老照片上的划痕",
        difficulty="hard",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/TencentARC/DeScratch",
        success_criteria={"type": "image_quality", "metric": "NIQE", "threshold": 7.0},
        market_value_usd=100.0
    ),
    # Image Enhancement
    BenchmarkTaskInstance(
        id="gittaskbench_lowlight_enhance_01",
        name="低光照图像增强",
        description="增强低光照条件下拍摄的图像亮度和细节",
        difficulty="medium",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/Li-Chongyi/Zero-DCE",
        success_criteria={"type": "image_quality", "metric": "PSNR", "threshold": 20.0},
        market_value_usd=45.0
    ),
    # Image Coloring
    BenchmarkTaskInstance(
        id="gittaskbench_colorize_01",
        name="黑白照片上色",
        description="使用深度学习为黑白照片添加自然色彩",
        difficulty="medium",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/richzhang/colorization",
        success_criteria={"type": "image_quality", "metric": "CIEDE2000", "threshold": 2.0},
        market_value_usd=55.0
    ),
    # Background Processing
    BenchmarkTaskInstance(
        id="gittaskbench_rembg_01",
        name="图像背景移除",
        description="使用rembg自动移除图像背景",
        difficulty="easy",
        domain="image_processing",
        modality="image",
        repo_url="https://github.com/danielgatis/rembg",
        success_criteria={"type": "mask_quality", "metric": "IoU", "threshold": 0.9},
        market_value_usd=30.0
    ),
    
    # ========== Speech Processing (8 tasks) ==========
    # Speech Recognition
    BenchmarkTaskInstance(
        id="gittaskbench_whisper_asr_01",
        name="Whisper语音识别",
        description="使用OpenAI Whisper进行语音转文字",
        difficulty="easy",
        domain="speech_processing",
        modality="audio",
        repo_url="https://github.com/openai/whisper",
        success_criteria={"type": "asr_quality", "metric": "WER", "threshold": 0.15},
        market_value_usd=40.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_vosk_asr_01",
        name="Vosk离线语音识别",
        description="使用Vosk进行离线语音识别",
        difficulty="medium",
        domain="speech_processing",
        modality="audio",
        repo_url="https://github.com/alphacep/vosk-api",
        success_criteria={"type": "asr_quality", "metric": "WER", "threshold": 0.20},
        market_value_usd=35.0
    ),
    # Speech Enhancement
    BenchmarkTaskInstance(
        id="gittaskbench_denoiser_01",
        name="语音降噪增强",
        description="使用Facebook Denoiser去除语音中的背景噪声",
        difficulty="medium",
        domain="speech_processing",
        modality="audio",
        repo_url="https://github.com/facebookresearch/denoiser",
        success_criteria={"type": "audio_quality", "metric": "PESQ", "threshold": 2.0},
        market_value_usd=50.0
    ),
    # Speech Separation
    BenchmarkTaskInstance(
        id="gittaskbench_spleeter_01",
        name="音频源分离",
        description="使用Spleeter分离音乐中的人声和伴奏",
        difficulty="medium",
        domain="speech_processing",
        modality="audio",
        repo_url="https://github.com/deezer/spleeter",
        success_criteria={"type": "separation_quality", "metric": "SDR", "threshold": 5.0},
        market_value_usd=60.0
    ),
    
    # ========== Office Document Processing (9 tasks) ==========
    # PDF Processing
    BenchmarkTaskInstance(
        id="gittaskbench_pdf_extract_01",
        name="PDF文本提取",
        description="从PDF文档中提取结构化文本内容",
        difficulty="easy",
        domain="document_processing",
        modality="document",
        repo_url="https://github.com/pymupdf/PyMuPDF",
        success_criteria={"type": "extraction_quality", "metric": "F1", "threshold": 0.9},
        market_value_usd=25.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_pdf_table_01",
        name="PDF表格提取",
        description="从PDF中提取表格数据并转换为结构化格式",
        difficulty="medium",
        domain="document_processing",
        modality="document",
        repo_url="https://github.com/camelot-dev/camelot",
        success_criteria={"type": "table_quality", "metric": "accuracy", "threshold": 0.85},
        market_value_usd=40.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_pdf_email_01",
        name="PDF邮件地址提取",
        description="从PDF文档中提取所有邮件地址并保存到文本文件",
        difficulty="easy",
        domain="document_processing",
        modality="document",
        repo_url="https://github.com/pymupdf/PyMuPDF",
        success_criteria={"type": "extraction_quality", "metric": "recall", "threshold": 0.95},
        market_value_usd=20.0
    ),
    # Excel Processing
    BenchmarkTaskInstance(
        id="gittaskbench_excel_parse_01",
        name="Excel数据解析",
        description="解析Excel文件并提取指定工作表数据",
        difficulty="easy",
        domain="document_processing",
        modality="document",
        repo_url="https://github.com/openpyxl/openpyxl",
        success_criteria={"type": "parse_quality", "metric": "accuracy", "threshold": 0.98},
        market_value_usd=20.0
    ),
    
    # ========== Web Scraping (5 tasks) ==========
    BenchmarkTaskInstance(
        id="gittaskbench_trafilatura_01",
        name="Trafilatura网页内容提取",
        description="使用Trafilatura库从指定URL提取网页的主要文本内容，过滤广告和导航元素",
        difficulty="easy",
        domain="web_scraping",
        modality="text",
        repo_url="https://github.com/adbar/trafilatura",
        input_data={"url": "https://example.com/article"},
        success_criteria={"type": "extraction_quality", "metric": "precision", "threshold": 0.9},
        market_value_usd=25.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_scrapy_crawl_01",
        name="Scrapy网页爬取",
        description="使用Scrapy框架爬取指定网站的结构化数据",
        difficulty="medium",
        domain="web_scraping",
        modality="text",
        repo_url="https://github.com/scrapy/scrapy",
        success_criteria={"type": "crawl_quality", "metric": "completeness", "threshold": 0.85},
        market_value_usd=45.0
    ),
    
    # ========== Security & Privacy (9 tasks) ==========
    # Watermark Embedding
    BenchmarkTaskInstance(
        id="gittaskbench_watermark_embed_01",
        name="图像水印嵌入",
        description="在图像中嵌入不可见数字水印",
        difficulty="medium",
        domain="security",
        modality="image",
        repo_url="https://github.com/ShieldMnt/invisible-watermark",
        success_criteria={"type": "watermark_quality", "metric": "robustness", "threshold": 0.8},
        market_value_usd=50.0
    ),
    # Watermark Extraction
    BenchmarkTaskInstance(
        id="gittaskbench_watermark_extract_01",
        name="图像水印提取",
        description="从图像中提取嵌入的数字水印",
        difficulty="medium",
        domain="security",
        modality="image",
        repo_url="https://github.com/ShieldMnt/invisible-watermark",
        success_criteria={"type": "extraction_quality", "metric": "accuracy", "threshold": 0.9},
        market_value_usd=50.0
    ),
    # Data Simulation
    BenchmarkTaskInstance(
        id="gittaskbench_faker_data_01",
        name="合成测试数据生成",
        description="使用Faker生成符合隐私要求的测试数据",
        difficulty="easy",
        domain="security",
        modality="text",
        repo_url="https://github.com/joke2k/faker",
        success_criteria={"type": "data_quality", "metric": "validity", "threshold": 0.95},
        market_value_usd=20.0
    ),
    
    # ========== Physiological Signal Processing (4 tasks) ==========
    BenchmarkTaskInstance(
        id="gittaskbench_ecg_analysis_01",
        name="ECG心电图分析",
        description="分析ECG数据，检测心律异常",
        difficulty="hard",
        domain="biomedical",
        modality="time_series",
        repo_url="https://github.com/MIT-LCP/wfdb-python",
        success_criteria={"type": "classification", "metric": "F1", "threshold": 0.85},
        market_value_usd=120.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_eda_analysis_01",
        name="EDA皮肤电分析",
        description="分析皮肤电导数据，检测情绪变化",
        difficulty="hard",
        domain="biomedical",
        modality="time_series",
        repo_url="https://github.com/MIT-LCP/wfdb-python",
        success_criteria={"type": "detection", "metric": "accuracy", "threshold": 0.8},
        market_value_usd=100.0
    ),
    
    # ========== Video Processing (3 tasks) ==========
    BenchmarkTaskInstance(
        id="gittaskbench_video_extract_01",
        name="视频关键帧提取",
        description="从视频中提取关键帧图像",
        difficulty="medium",
        domain="video_processing",
        modality="video",
        repo_url="https://github.com/PyAV-Org/PyAV",
        success_criteria={"type": "extraction_quality", "metric": "coverage", "threshold": 0.9},
        market_value_usd=35.0
    ),
    BenchmarkTaskInstance(
        id="gittaskbench_video_subtitle_01",
        name="视频字幕生成",
        description="为视频自动生成字幕文件",
        difficulty="hard",
        domain="video_processing",
        modality="video",
        repo_url="https://github.com/openai/whisper",
        success_criteria={"type": "subtitle_quality", "metric": "WER", "threshold": 0.15},
        market_value_usd=80.0
    ),
]

# ==================== SWE-bench Verified 任务定义 ====================
# 500个人工验证任务，来自12个Python仓库

SWE_BENCH_VERIFIED_TASKS = [
    # Django (231 tasks) - 示例5个
    BenchmarkTaskInstance(
        id="django__django-11099",
        name="Django UsernameValidator尾随换行符",
        description="修复Django中UsernameValidator允许尾随换行符的问题",
        difficulty="medium",
        domain="web_framework",
        modality="code",
        repo_url="https://github.com/django/django",
        base_commit="e7fd69d051eaa67cb17f172a39b57253e9cb831a",
        problem_statement="UsernameValidator allows trailing newline in usernames",
        fail_to_pass=["tests.auth_tests.test_validators.UsernameValidatorTest.test_trailing_newline"],
        metadata={"repository": "django/django", "version": "3.0"}
    ),
    BenchmarkTaskInstance(
        id="django__django-14725",
        name="Django Formset禁止新建对象",
        description="为model formsets提供禁止创建新对象的方式",
        difficulty="medium",
        domain="web_framework",
        modality="code",
        repo_url="https://github.com/django/django",
        problem_statement="Provide a way for model formsets to disallow new object creation",
        metadata={"repository": "django/django"}
    ),
    BenchmarkTaskInstance(
        id="django__django-15104",
        name="Django迁移字段检测",
        description="修复Django ORM迁移时字段变更检测问题",
        difficulty="hard",
        domain="web_framework",
        modality="code",
        repo_url="https://github.com/django/django",
        metadata={"repository": "django/django"}
    ),
    BenchmarkTaskInstance(
        id="django__django-16046",
        name="Django NumberToWord优化",
        description="优化Django模板中的数字转文字功能",
        difficulty="easy",
        domain="web_framework",
        modality="code",
        repo_url="https://github.com/django/django",
        metadata={"repository": "django/django"}
    ),
    BenchmarkTaskInstance(
        id="django__django-16379",
        name="Django缓存后端改进",
        description="改进Django缓存后端的键值处理",
        difficulty="medium",
        domain="web_framework",
        modality="code",
        repo_url="https://github.com/django/django",
        metadata={"repository": "django/django"}
    ),
    
    # SymPy (75 tasks) - 示例5个
    BenchmarkTaskInstance(
        id="sympy__sympy-22714",
        name="SymPy simpify异常处理",
        description="修复SymPy sympify函数的异常处理问题",
        difficulty="medium",
        domain="mathematics",
        modality="code",
        repo_url="https://github.com/sympy/sympy",
        problem_statement="sympify of str('1*(2)') gives TypeError",
        metadata={"repository": "sympy/sympy"}
    ),
    BenchmarkTaskInstance(
        id="sympy__sympy-23262",
        name="SymPy Lambda表达式优化",
        description="优化SymPy Lambda表达式的符号计算",
        difficulty="hard",
        domain="mathematics",
        modality="code",
        repo_url="https://github.com/sympy/sympy",
        metadata={"repository": "sympy/sympy"}
    ),
    BenchmarkTaskInstance(
        id="sympy__sympy-23413",
        name="SymPy HNF矩阵计算",
        description="修复Hermite Normal Form矩阵计算的bug",
        difficulty="expert",
        domain="mathematics",
        modality="code",
        repo_url="https://github.com/sympy/sympy",
        metadata={"repository": "sympy/sympy"}
    ),
    BenchmarkTaskInstance(
        id="sympy__sympy-20801",
        name="SymPy Matrix求解优化",
        description="优化矩阵求解的符号计算性能",
        difficulty="hard",
        domain="mathematics",
        modality="code",
        repo_url="https://github.com/sympy/sympy",
        metadata={"repository": "sympy/sympy"}
    ),
    BenchmarkTaskInstance(
        id="sympy__sympy-kernS",
        name="SymPy kernS未绑定变量",
        description="修复kernS函数中变量未定义的问题",
        difficulty="easy",
        domain="mathematics",
        modality="code",
        repo_url="https://github.com/sympy/sympy",
        problem_statement="'kern' referenced before assignment in kernS",
        metadata={"repository": "sympy/sympy"}
    ),
    
    # Scikit-learn (32 tasks) - 示例5个
    BenchmarkTaskInstance(
        id="sklearn__sklearn-25638",
        name="Sklearn交叉验证改进",
        description="改进交叉验证的分层采样策略",
        difficulty="medium",
        domain="machine_learning",
        modality="code",
        repo_url="https://github.com/scikit-learn/scikit-learn",
        metadata={"repository": "scikit-learn/scikit-learn"}
    ),
    BenchmarkTaskInstance(
        id="sklearn__sklearn-25747",
        name="Sklearn Pipeline特征名称",
        description="修复Pipeline中特征名称传递问题",
        difficulty="medium",
        domain="machine_learning",
        modality="code",
        repo_url="https://github.com/scikit-learn/scikit-learn",
        metadata={"repository": "scikit-learn/scikit-learn"}
    ),
    BenchmarkTaskInstance(
        id="sklearn__sklearn-25969",
        name="Sklearn随机森林并行优化",
        description="优化随机森林的并行训练性能",
        difficulty="hard",
        domain="machine_learning",
        modality="code",
        repo_url="https://github.com/scikit-learn/scikit-learn",
        metadata={"repository": "scikit-learn/scikit-learn"}
    ),
    BenchmarkTaskInstance(
        id="sklearn__sklearn-26194",
        name="Sklearn PCA增量学习",
        description="修复增量PCA的内存管理问题",
        difficulty="medium",
        domain="machine_learning",
        modality="code",
        repo_url="https://github.com/scikit-learn/scikit-learn",
        metadata={"repository": "scikit-learn/scikit-learn"}
    ),
    BenchmarkTaskInstance(
        id="sklearn__sklearn-26400",
        name="Sklearn梯度提升早停",
        description="改进梯度提升的早停策略",
        difficulty="medium",
        domain="machine_learning",
        modality="code",
        repo_url="https://github.com/scikit-learn/scikit-learn",
        metadata={"repository": "scikit-learn/scikit-learn"}
    ),
    
    # Pytest (19 tasks) - 示例3个
    BenchmarkTaskInstance(
        id="pytest__pytest-11148",
        name="Pytest Fixture作用域",
        description="修复fixture作用域在参数化测试中的问题",
        difficulty="medium",
        domain="testing",
        modality="code",
        repo_url="https://github.com/pytest-dev/pytest",
        metadata={"repository": "pytest-dev/pytest"}
    ),
    BenchmarkTaskInstance(
        id="pytest__pytest-11160",
        name="Pytest断言重写优化",
        description="优化断言重写的性能",
        difficulty="hard",
        domain="testing",
        modality="code",
        repo_url="https://github.com/pytest-dev/pytest",
        metadata={"repository": "pytest-dev/pytest"}
    ),
    BenchmarkTaskInstance(
        id="pytest__pytest-11178",
        name="Pytest插件兼容性",
        description="修复第三方插件的兼容性问题",
        difficulty="medium",
        domain="testing",
        modality="code",
        repo_url="https://github.com/pytest-dev/pytest",
        metadata={"repository": "pytest-dev/pytest"}
    ),
    
    # Flask (1 task)
    BenchmarkTaskInstance(
        id="flask__flask-4992",
        name="Flask蓝图URL前缀",
        description="修复蓝图URL前缀处理问题",
        difficulty="easy",
        domain="web_framework",
        modality="code",
        repo_url="https://github.com/pallets/flask",
        metadata={"repository": "pallets/flask"}
    ),
    
    # Matplotlib (34 tasks) - 示例3个
    BenchmarkTaskInstance(
        id="matplotlib__matplotlib-26011",
        name="Matplotlib颜色映射",
        description="修复自定义颜色映射的边界处理",
        difficulty="medium",
        domain="visualization",
        modality="code",
        repo_url="https://github.com/matplotlib/matplotlib",
        metadata={"repository": "matplotlib/matplotlib"}
    ),
    BenchmarkTaskInstance(
        id="matplotlib__matplotlib-26020",
        name="Matplotlib坐标轴刻度",
        description="优化坐标轴刻度的自动计算",
        difficulty="medium",
        domain="visualization",
        modality="code",
        repo_url="https://github.com/matplotlib/matplotlib",
        metadata={"repository": "matplotlib/matplotlib"}
    ),
    BenchmarkTaskInstance(
        id="matplotlib__matplotlib-26113",
        name="Matplotlib图例位置",
        description="修复图例自动定位的计算问题",
        difficulty="easy",
        domain="visualization",
        modality="code",
        repo_url="https://github.com/matplotlib/matplotlib",
        metadata={"repository": "matplotlib/matplotlib"}
    ),
]

# ==================== MLE-bench 任务定义 ====================
# 75个Kaggle机器学习竞赛任务

MLE_BENCH_TASKS = [
    # 低复杂度 (22 tasks) - 示例5个
    BenchmarkTaskInstance(
        id="mle_bench_titanic",
        name="Titanic生存预测",
        description="预测泰坦尼克号乘客的生存概率",
        difficulty="easy",
        domain="classification",
        modality="tabular",
        competition_id="titanic",
        metric="accuracy",
        dataset_size_mb=0.1,
        metadata={"kaggle_url": "https://www.kaggle.com/c/titanic"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_house_prices",
        name="房价预测",
        description="预测爱荷华州Ames市的房屋销售价格",
        difficulty="easy",
        domain="regression",
        modality="tabular",
        competition_id="house-prices-advanced-regression-techniques",
        metric="rmse",
        dataset_size_mb=0.5,
        metadata={"kaggle_url": "https://www.kaggle.com/c/house-prices-advanced-regression-techniques"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_digit_recognizer",
        name="MNIST手写数字识别",
        description="识别手写数字图像(0-9)",
        difficulty="easy",
        domain="classification",
        modality="image",
        competition_id="digit-recognizer",
        metric="accuracy",
        dataset_size_mb=75.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/digit-recognizer"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_spaceship_titanic",
        name="Spaceship Titanic乘客预测",
        description="预测太空船泰坦尼克号乘客是否被传送到另一个维度",
        difficulty="easy",
        domain="classification",
        modality="tabular",
        competition_id="spaceship-titanic",
        metric="accuracy",
        dataset_size_mb=0.3,
        metadata={"kaggle_url": "https://www.kaggle.com/c/spaceship-titanic"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_store_sales",
        name="商店销售预测",
        description="预测商店的日销售额",
        difficulty="easy",
        domain="regression",
        modality="tabular",
        competition_id="store-sales-time-series-forecasting",
        metric="rmsle",
        dataset_size_mb=50.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/store-sales-time-series-forecasting"}
    ),
    
    # 中等复杂度 (31 tasks) - 示例5个
    BenchmarkTaskInstance(
        id="mle_bench_nlp_disaster",
        name="灾难推文分类",
        description="识别推文是否描述真实灾难",
        difficulty="medium",
        domain="nlp",
        modality="text",
        competition_id="nlp-getting-started",
        metric="f1",
        dataset_size_mb=1.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/nlp-getting-started"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_tabular_playground",
        name="表格数据分类挑战",
        description="对复杂表格数据进行多类分类",
        difficulty="medium",
        domain="classification",
        modality="tabular",
        competition_id="tabular-playground-series-jan-2022",
        metric="accuracy",
        dataset_size_mb=100.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/tabular-playground-series-jan-2022"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_feedback_prize",
        name="学生作文评分",
        description="自动评估学生论证性写作的有效性",
        difficulty="medium",
        domain="nlp",
        modality="text",
        competition_id="feedback-prize-2021",
        metric="mean_column_wise_log_loss",
        dataset_size_mb=200.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/feedback-prize-2021"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_petfinder",
        name="宠物收养速度预测",
        description="预测宠物被收养的速度",
        difficulty="medium",
        domain="classification",
        modality="multimodal",
        competition_id="petfinder-adoption-prediction",
        metric="quadratic_weighted_kappa",
        dataset_size_mb=5000.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/petfinder-adoption-prediction"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_forest_cover",
        name="森林覆盖类型分类",
        description="根据地形特征预测森林覆盖类型",
        difficulty="medium",
        domain="classification",
        modality="tabular",
        competition_id="forest-cover-type-prediction",
        metric="accuracy",
        dataset_size_mb=75.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/forest-cover-type-prediction"}
    ),
    
    # 高复杂度 (22 tasks) - 示例5个
    BenchmarkTaskInstance(
        id="mle_bench_ventilator_pressure",
        name="呼吸机压力预测",
        description="预测机械呼吸机的呼吸回路压力",
        difficulty="hard",
        domain="time_series",
        modality="tabular",
        competition_id="ventilator-pressure-prediction",
        metric="mae",
        dataset_size_mb=500.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/ventilator-pressure-prediction"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_birdclef",
        name="鸟类叫声识别",
        description="从音频记录中识别鸟类物种",
        difficulty="hard",
        domain="audio",
        modality="audio",
        competition_id="birdclef-2024",
        metric="padded_cmap",
        dataset_size_mb=30000.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/birdclef-2024"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_google_landmark",
        name="地标识别",
        description="识别图像中的著名地标",
        difficulty="hard",
        domain="computer_vision",
        modality="image",
        competition_id="landmark-recognition-2021",
        metric="gap",
        dataset_size_mb=100000.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/landmark-recognition-2021"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_rsna_mammography",
        name="乳腺癌检测",
        description="从乳房X光检查中检测乳腺癌",
        difficulty="expert",
        domain="medical",
        modality="image",
        competition_id="rsna-breast-cancer-detection",
        metric="pfbeta",
        dataset_size_mb=200000.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/rsna-breast-cancer-detection"}
    ),
    BenchmarkTaskInstance(
        id="mle_bench_llm_science",
        name="LLM科学问答",
        description="使用LLM回答科学多选题",
        difficulty="hard",
        domain="nlp",
        modality="text",
        competition_id="kaggle-llm-science-exam",
        metric="map@3",
        dataset_size_mb=10.0,
        metadata={"kaggle_url": "https://www.kaggle.com/c/kaggle-llm-science-exam"}
    ),
]


class EnhancedBenchmarkLoader:
    """增强版Benchmark加载器"""
    
    @staticmethod
    def load(benchmark_type: BenchmarkType, limit: int = 10, 
             difficulty: Optional[str] = None,
             domain: Optional[str] = None) -> List[BenchmarkTaskInstance]:
        """
        加载指定类型的Benchmark任务
        
        Args:
            benchmark_type: Benchmark类型
            limit: 返回任务数量限制
            difficulty: 难度过滤 (easy/medium/hard/expert)
            domain: 领域过滤
        
        Returns:
            任务实例列表
        """
        tasks = []
        
        if benchmark_type == BenchmarkType.GITTASKBENCH:
            tasks = GITTASKBENCH_TASKS.copy()
        elif benchmark_type in (BenchmarkType.SWE_BENCH, 
                                BenchmarkType.SWE_BENCH_VERIFIED,
                                BenchmarkType.SWE_BENCH_LITE):
            tasks = SWE_BENCH_VERIFIED_TASKS.copy()
        elif benchmark_type in (BenchmarkType.MLE_BENCH, BenchmarkType.MLE_BENCH_LITE):
            tasks = MLE_BENCH_TASKS.copy()
            if benchmark_type == BenchmarkType.MLE_BENCH_LITE:
                tasks = [t for t in tasks if t.difficulty in ('easy', 'medium')]
        
        # 过滤难度
        if difficulty:
            tasks = [t for t in tasks if t.difficulty == difficulty]
        
        # 过滤领域
        if domain:
            tasks = [t for t in tasks if t.domain == domain]
        
        return tasks[:limit]
    
    @staticmethod
    def get_benchmark_info(benchmark_type: BenchmarkType) -> Dict[str, Any]:
        """获取Benchmark信息"""
        info_map = {
            BenchmarkType.GITTASKBENCH: {
                "name": "GitTaskBench",
                "description": "54个仓库级真实世界任务，覆盖7个领域",
                "task_count": 54,
                "domains": ["image_processing", "speech_processing", "document_processing", 
                           "web_scraping", "security", "biomedical", "video_processing"],
                "modalities": ["image", "audio", "text", "document", "video", "time_series"],
                "metrics": ["ECR", "TPR", "α-score"],
                "paper_url": "https://arxiv.org/abs/2508.18993"
            },
            BenchmarkType.SWE_BENCH_VERIFIED: {
                "name": "SWE-bench Verified",
                "description": "500个人工验证的GitHub issue修复任务",
                "task_count": 500,
                "domains": ["django", "sympy", "scikit-learn", "matplotlib", "pytest", 
                           "flask", "sphinx", "astropy", "xarray", "requests", "pylint", "seaborn"],
                "repository_distribution": {
                    "django/django": 231,
                    "sympy/sympy": 75,
                    "sphinx-doc/sphinx": 44,
                    "matplotlib/matplotlib": 34,
                    "scikit-learn/scikit-learn": 32,
                    "pydata/xarray": 22,
                    "astropy/astropy": 22,
                    "pytest-dev/pytest": 19,
                    "pylint-dev/pylint": 10,
                    "psf/requests": 8,
                    "mwaskom/seaborn": 2,
                    "pallets/flask": 1
                },
                "paper_url": "https://openai.com/index/introducing-swe-bench-verified/"
            },
            BenchmarkType.MLE_BENCH: {
                "name": "MLE-bench",
                "description": "75个Kaggle机器学习竞赛任务",
                "task_count": 75,
                "domains": ["classification", "regression", "nlp", "computer_vision", 
                           "time_series", "audio", "medical"],
                "complexity_distribution": {
                    "Low": 22,
                    "Medium": 31,
                    "High": 22
                },
                "paper_url": "https://github.com/openai/mle-bench"
            }
        }
        return info_map.get(benchmark_type, {})
    
    @staticmethod
    def get_all_domains(benchmark_type: BenchmarkType) -> List[str]:
        """获取所有领域"""
        tasks = EnhancedBenchmarkLoader.load(benchmark_type, limit=1000)
        return list(set(t.domain for t in tasks))
    
    @staticmethod
    def get_task_by_id(task_id: str) -> Optional[BenchmarkTaskInstance]:
        """根据ID获取任务"""
        all_tasks = (GITTASKBENCH_TASKS + 
                     SWE_BENCH_VERIFIED_TASKS + 
                     MLE_BENCH_TASKS)
        for task in all_tasks:
            if task.id == task_id:
                return task
        return None


# 兼容旧版接口
UnifiedBenchmarkLoader = EnhancedBenchmarkLoader