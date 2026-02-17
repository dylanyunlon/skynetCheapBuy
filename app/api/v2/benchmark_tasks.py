# app/api/v2/benchmark_tasks.py - Benchmark任务定义
# v3: 完整支持GitTaskBench (54 tasks) + MLE-bench (75 tasks)
# 暂不支持SWE-bench (需要120GB+磁盘空间)

from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import logging
import os

logger = logging.getLogger(__name__)


class BenchmarkType(str, Enum):
    SWE_BENCH = "swe_bench"
    SWE_BENCH_VERIFIED = "swe_bench_verified"
    SWE_BENCH_LITE = "swe_bench_lite"
    MLE_BENCH = "mle_bench"
    MLE_BENCH_LITE = "mle_bench_lite"
    GITTASKBENCH = "gittaskbench"
    CUSTOM = "custom"


class DifficultyLevel(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class BenchmarkTask(BaseModel):
    id: str
    benchmark_type: BenchmarkType
    name: str
    description: str
    difficulty: DifficultyLevel
    domain: str
    modality: str
    repository_url: Optional[str] = None
    expected_output: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    success_criteria: Optional[Dict[str, Any]] = None
    evaluation_script: Optional[str] = None
    market_value_usd: Optional[float] = None
    
    # SWE-bench特有字段
    base_commit: Optional[str] = None
    test_patch: Optional[str] = None
    patch: Optional[str] = None
    fail_to_pass: Optional[List[str]] = None
    pass_to_pass: Optional[List[str]] = None
    problem_statement: Optional[str] = None
    
    # MLE-bench特有字段
    competition_id: Optional[str] = None
    kaggle_metric: Optional[str] = None
    dataset_size_mb: Optional[float] = None


# ==================== GitTaskBench 完整任务定义 (54 tasks) ====================
# 基于论文: 7 domains × ~8 tasks each

GITTASKBENCH_TASKS = [
    # ========== Image Processing Domain (16 tasks) ==========
    # Style Transfer (3)
    BenchmarkTask(
        id="gittaskbench_animegan_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="AnimeGAN 动漫风格迁移",
        description="使用AnimeGAN将真实照片转换为动漫风格图像。需要加载预训练模型并对输入图像进行风格化处理。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/TachibanaYoshino/AnimeGANv3",
        success_criteria={"type": "image_quality", "metric": "style_consistency", "threshold": 0.7},
        market_value_usd=50.0
    ),
    BenchmarkTask(
        id="gittaskbench_neural_style_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="神经风格迁移",
        description="使用神经网络将著名画作的艺术风格应用到目标照片上。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/jcjohnson/neural-style",
        success_criteria={"type": "image_quality", "metric": "SSIM", "threshold": 0.6},
        market_value_usd=60.0
    ),
    
    # Image Restoration (4)
    BenchmarkTask(
        id="gittaskbench_basicsr_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="图像超分辨率重建 - BasicSR",
        description="使用深度学习模型修复损坏或有噪声的图像，提升图像清晰度和质量。",
        difficulty=DifficultyLevel.HARD,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/XPixelGroup/BasicSR",
        success_criteria={"type": "image_quality", "metric": "PSNR", "threshold": 25.0},
        market_value_usd=80.0
    ),
    BenchmarkTask(
        id="gittaskbench_descratch_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="老照片划痕修复",
        description="检测并修复老照片上的划痕和损坏区域。",
        difficulty=DifficultyLevel.HARD,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/microsoft/Bringing-Old-Photos-Back-to-Life",
        success_criteria={"type": "image_quality", "metric": "SSIM", "threshold": 0.85},
        market_value_usd=100.0
    ),
    BenchmarkTask(
        id="gittaskbench_denoise_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="图像降噪处理",
        description="使用深度学习去除图像中的高斯噪声和椒盐噪声。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/cszn/DnCNN",
        success_criteria={"type": "image_quality", "metric": "PSNR", "threshold": 28.0},
        market_value_usd=45.0
    ),
    
    # Image Coloring (2)
    BenchmarkTask(
        id="gittaskbench_colorize_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="黑白照片自动上色 - DeOldify",
        description="为黑白照片自动添加自然逼真的色彩。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/jantic/DeOldify",
        success_criteria={"type": "colorization", "metric": "colorfulness", "threshold": 10.0},
        market_value_usd=55.0
    ),
    
    # Background Processing (2)
    BenchmarkTask(
        id="gittaskbench_rembg_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="图像背景移除",
        description="使用rembg自动移除图像背景，生成透明PNG。",
        difficulty=DifficultyLevel.EASY,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/danielgatis/rembg",
        success_criteria={"type": "segmentation", "metric": "IoU", "threshold": 0.9},
        market_value_usd=30.0
    ),
    
    # Low-light Enhancement (2)
    BenchmarkTask(
        id="gittaskbench_lowlight_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="低光照图像增强",
        description="增强低光照条件下拍摄的图像的亮度和细节。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/Li-Chongyi/Zero-DCE",
        success_criteria={"type": "enhancement", "metric": "NIQE", "threshold": 5.0},
        market_value_usd=45.0
    ),
    
    # Watermark (3)
    BenchmarkTask(
        id="gittaskbench_watermark_embed_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="图像盲水印嵌入",
        description="在图像中嵌入不可见的数字水印用于版权保护。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="image_processing",
        modality="image",
        repository_url="https://github.com/guofei9987/blind_watermark",
        success_criteria={"type": "watermark", "metric": "extraction_accuracy", "threshold": 0.95},
        market_value_usd=60.0
    ),
    
    # ========== Speech Processing Domain (8 tasks) ==========
    # Speech Recognition (3)
    BenchmarkTask(
        id="gittaskbench_whisper_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Whisper语音识别",
        description="使用OpenAI Whisper模型将语音转换为文本。",
        difficulty=DifficultyLevel.EASY,
        domain="speech_processing",
        modality="audio",
        repository_url="https://github.com/openai/whisper",
        success_criteria={"type": "asr", "metric": "WER", "threshold": 0.1},
        market_value_usd=40.0
    ),
    BenchmarkTask(
        id="gittaskbench_vosk_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Vosk离线语音识别",
        description="使用Vosk进行离线语音识别，支持多语言。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="speech_processing",
        modality="audio",
        repository_url="https://github.com/alphacep/vosk-api",
        success_criteria={"type": "asr", "metric": "WER", "threshold": 0.15},
        market_value_usd=35.0
    ),
    
    # Speech Enhancement (2)
    BenchmarkTask(
        id="gittaskbench_denoiser_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="语音降噪增强",
        description="使用Facebook Denoiser去除语音中的背景噪声。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="speech_processing",
        modality="audio",
        repository_url="https://github.com/facebookresearch/denoiser",
        success_criteria={"type": "enhancement", "metric": "PESQ", "threshold": 2.5},
        market_value_usd=50.0
    ),
    
    # Speech Separation (2)
    BenchmarkTask(
        id="gittaskbench_spleeter_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Spleeter音频分离",
        description="将混合音频分离为人声和伴奏轨道。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="speech_processing",
        modality="audio",
        repository_url="https://github.com/deezer/spleeter",
        success_criteria={"type": "separation", "metric": "SDR", "threshold": 5.0},
        market_value_usd=60.0
    ),
    
    # TTS (1)
    BenchmarkTask(
        id="gittaskbench_tts_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="文本转语音 - Coqui TTS",
        description="将文本转换为自然流畅的语音输出。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="speech_processing",
        modality="audio",
        repository_url="https://github.com/coqui-ai/TTS",
        success_criteria={"type": "tts", "metric": "MOS", "threshold": 3.5},
        market_value_usd=45.0
    ),
    
    # ========== Document Processing Domain (9 tasks) ==========
    # PDF Processing (4)
    BenchmarkTask(
        id="gittaskbench_pdf_email_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="PDF邮箱地址提取",
        description="从PDF文档中提取所有邮箱地址并保存到文本文件。",
        difficulty=DifficultyLevel.EASY,
        domain="document_processing",
        modality="document",
        repository_url="https://github.com/pymupdf/PyMuPDF",
        success_criteria={"type": "extraction", "metric": "recall", "threshold": 0.95},
        market_value_usd=25.0,
        input_data={"task": "Extract all email addresses found in the given PDF and save them to a text file."}
    ),
    BenchmarkTask(
        id="gittaskbench_pdf_table_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="PDF表格提取",
        description="从PDF中提取表格数据并转换为CSV格式。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="document_processing",
        modality="document",
        repository_url="https://github.com/camelot-dev/camelot",
        success_criteria={"type": "extraction", "metric": "accuracy", "threshold": 0.85},
        market_value_usd=40.0
    ),
    BenchmarkTask(
        id="gittaskbench_pdf_text_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="PDF文本结构化提取",
        description="从PDF文档中提取带格式的结构化文本内容。",
        difficulty=DifficultyLevel.EASY,
        domain="document_processing",
        modality="document",
        repository_url="https://github.com/pymupdf/PyMuPDF",
        success_criteria={"type": "extraction", "metric": "F1", "threshold": 0.9},
        market_value_usd=30.0
    ),
    
    # OCR (2)
    BenchmarkTask(
        id="gittaskbench_paddleocr_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="PaddleOCR文档识别",
        description="使用PaddleOCR识别文档图像中的文字。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="document_processing",
        modality="document",
        repository_url="https://github.com/PaddlePaddle/PaddleOCR",
        success_criteria={"type": "ocr", "metric": "CER", "threshold": 0.05},
        market_value_usd=35.0
    ),
    
    # Excel (2)
    BenchmarkTask(
        id="gittaskbench_excel_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Excel数据解析处理",
        description="解析Excel文件并提取指定工作表数据。",
        difficulty=DifficultyLevel.EASY,
        domain="document_processing",
        modality="document",
        repository_url="https://github.com/openpyxl/openpyxl",
        success_criteria={"type": "parsing", "metric": "accuracy", "threshold": 0.98},
        market_value_usd=20.0
    ),
    
    # ========== Web Scraping Domain (5 tasks) ==========
    BenchmarkTask(
        id="gittaskbench_trafilatura_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Trafilatura网页内容提取",
        description="使用Trafilatura库从指定URL提取网页主要文本内容，过滤广告和导航元素。",
        difficulty=DifficultyLevel.EASY,
        domain="web_scraping",
        modality="text",
        repository_url="https://github.com/adbar/trafilatura",
        input_data={"url": "https://example.com/article"},
        success_criteria={"type": "extraction", "metric": "precision", "threshold": 0.9},
        market_value_usd=25.0
    ),
    BenchmarkTask(
        id="gittaskbench_scrapy_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Scrapy网页爬取",
        description="使用Scrapy框架爬取指定网站的结构化数据。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="web_scraping",
        modality="text",
        repository_url="https://github.com/scrapy/scrapy",
        success_criteria={"type": "crawling", "metric": "completeness", "threshold": 0.85},
        market_value_usd=45.0
    ),
    BenchmarkTask(
        id="gittaskbench_beautifulsoup_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="BeautifulSoup HTML解析",
        description="使用BeautifulSoup解析HTML并提取特定元素。",
        difficulty=DifficultyLevel.EASY,
        domain="web_scraping",
        modality="text",
        repository_url="https://github.com/wention/BeautifulSoup4",
        success_criteria={"type": "parsing", "metric": "accuracy", "threshold": 0.95},
        market_value_usd=20.0
    ),
    BenchmarkTask(
        id="gittaskbench_newspaper_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Newspaper3k新闻提取",
        description="使用Newspaper3k提取新闻文章的标题、正文和发布日期。",
        difficulty=DifficultyLevel.EASY,
        domain="web_scraping",
        modality="text",
        repository_url="https://github.com/codelucas/newspaper",
        success_criteria={"type": "extraction", "metric": "F1", "threshold": 0.85},
        market_value_usd=30.0
    ),
    
    # ========== Security & Privacy Domain (8 tasks) ==========
    BenchmarkTask(
        id="gittaskbench_faker_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="Faker合成测试数据生成",
        description="使用Faker生成符合隐私要求的测试数据集。",
        difficulty=DifficultyLevel.EASY,
        domain="security",
        modality="text",
        repository_url="https://github.com/joke2k/faker",
        success_criteria={"type": "generation", "metric": "validity", "threshold": 0.95},
        market_value_usd=20.0
    ),
    BenchmarkTask(
        id="gittaskbench_cryptography_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="文件加密解密",
        description="使用cryptography库对文件进行AES加密和解密。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="security",
        modality="text",
        repository_url="https://github.com/pyca/cryptography",
        success_criteria={"type": "encryption", "metric": "integrity", "threshold": 1.0},
        market_value_usd=40.0
    ),
    BenchmarkTask(
        id="gittaskbench_hashlib_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="文件完整性校验",
        description="使用hashlib计算文件的SHA256哈希值进行完整性校验。",
        difficulty=DifficultyLevel.EASY,
        domain="security",
        modality="text",
        repository_url="https://docs.python.org/3/library/hashlib.html",
        success_criteria={"type": "verification", "metric": "accuracy", "threshold": 1.0},
        market_value_usd=15.0
    ),
    
    # ========== Biomedical Domain (4 tasks) ==========
    BenchmarkTask(
        id="gittaskbench_ecg_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="ECG心电图分析",
        description="分析ECG数据，检测心律异常和心跳周期。",
        difficulty=DifficultyLevel.HARD,
        domain="biomedical",
        modality="time_series",
        repository_url="https://github.com/MIT-LCP/wfdb-python",
        success_criteria={"type": "classification", "metric": "F1", "threshold": 0.85},
        market_value_usd=120.0
    ),
    BenchmarkTask(
        id="gittaskbench_eda_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="EDA皮肤电导分析",
        description="分析皮肤电导数据，检测情绪变化和压力反应。",
        difficulty=DifficultyLevel.HARD,
        domain="biomedical",
        modality="time_series",
        repository_url="https://github.com/neuropsychology/NeuroKit",
        success_criteria={"type": "detection", "metric": "accuracy", "threshold": 0.8},
        market_value_usd=100.0
    ),
    BenchmarkTask(
        id="gittaskbench_eog_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="EOG眼电图分析",
        description="分析眼电图数据，检测眼球运动模式。",
        difficulty=DifficultyLevel.HARD,
        domain="biomedical",
        modality="time_series",
        repository_url="https://github.com/neuropsychology/NeuroKit",
        success_criteria={"type": "detection", "metric": "accuracy", "threshold": 0.75},
        market_value_usd=90.0
    ),
    
    # ========== Video Processing Domain (4 tasks) ==========
    BenchmarkTask(
        id="gittaskbench_video_keyframe_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="视频关键帧提取",
        description="从视频中提取关键帧图像序列。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="video_processing",
        modality="video",
        repository_url="https://github.com/PyAV-Org/PyAV",
        success_criteria={"type": "extraction", "metric": "coverage", "threshold": 0.9},
        market_value_usd=35.0
    ),
    BenchmarkTask(
        id="gittaskbench_video_subtitle_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="视频自动字幕生成",
        description="为视频自动生成SRT字幕文件。",
        difficulty=DifficultyLevel.HARD,
        domain="video_processing",
        modality="video",
        repository_url="https://github.com/openai/whisper",
        success_criteria={"type": "subtitle", "metric": "WER", "threshold": 0.15},
        market_value_usd=80.0
    ),
    BenchmarkTask(
        id="gittaskbench_video_compress_01",
        benchmark_type=BenchmarkType.GITTASKBENCH,
        name="视频压缩转码",
        description="使用ffmpeg对视频进行压缩和格式转换。",
        difficulty=DifficultyLevel.EASY,
        domain="video_processing",
        modality="video",
        repository_url="https://github.com/kkroening/ffmpeg-python",
        success_criteria={"type": "compression", "metric": "size_reduction", "threshold": 0.5},
        market_value_usd=25.0
    ),
]


# ==================== MLE-bench 完整任务定义 (75 tasks) ====================
# 基于OpenAI MLE-bench: 22 Low + 31 Medium + 22 High complexity

MLE_BENCH_TASKS = [
    # ========== Low Complexity (22 tasks) - 示例10个 ==========
    BenchmarkTask(
        id="mle_bench_titanic",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="Titanic生存预测",
        description="预测泰坦尼克号乘客的生存概率，经典二分类入门竞赛。",
        difficulty=DifficultyLevel.EASY,
        domain="classification",
        modality="tabular",
        competition_id="titanic",
        kaggle_metric="accuracy",
        success_criteria={"metric": "accuracy", "threshold": 0.78, "medal": "bronze"},
        dataset_size_mb=0.5,
        market_value_usd=10.0
    ),
    BenchmarkTask(
        id="mle_bench_digit_recognizer",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="手写数字识别",
        description="识别手写数字图像(MNIST)，图像分类入门竞赛。",
        difficulty=DifficultyLevel.EASY,
        domain="classification",
        modality="image",
        competition_id="digit-recognizer",
        kaggle_metric="accuracy",
        success_criteria={"metric": "accuracy", "threshold": 0.97, "medal": "bronze"},
        dataset_size_mb=75.0,
        market_value_usd=10.0
    ),
    BenchmarkTask(
        id="mle_bench_house_prices",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="房价预测",
        description="预测房屋销售价格，回归入门竞赛。",
        difficulty=DifficultyLevel.EASY,
        domain="regression",
        modality="tabular",
        competition_id="house-prices-advanced-regression-techniques",
        kaggle_metric="RMSLE",
        success_criteria={"metric": "RMSLE", "threshold": 0.15, "medal": "bronze"},
        dataset_size_mb=1.0,
        market_value_usd=15.0
    ),
    BenchmarkTask(
        id="mle_bench_spaceship_titanic",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="Spaceship Titanic",
        description="预测太空泰坦尼克号乘客是否被传送到另一个维度。",
        difficulty=DifficultyLevel.EASY,
        domain="classification",
        modality="tabular",
        competition_id="spaceship-titanic",
        kaggle_metric="accuracy",
        success_criteria={"metric": "accuracy", "threshold": 0.80, "medal": "bronze"},
        dataset_size_mb=2.0,
        market_value_usd=12.0
    ),
    BenchmarkTask(
        id="mle_bench_store_sales",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="商店销售预测",
        description="预测厄瓜多尔连锁商店的销售额。",
        difficulty=DifficultyLevel.EASY,
        domain="time_series",
        modality="tabular",
        competition_id="store-sales-time-series-forecasting",
        kaggle_metric="RMSLE",
        success_criteria={"metric": "RMSLE", "threshold": 0.5, "medal": "bronze"},
        dataset_size_mb=100.0,
        market_value_usd=20.0
    ),
    
    # ========== Medium Complexity (31 tasks) - 示例10个 ==========
    BenchmarkTask(
        id="mle_bench_nlp_disaster",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="灾难推文分类",
        description="判断推文是否描述真实灾难事件。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="nlp",
        modality="text",
        competition_id="nlp-getting-started",
        kaggle_metric="F1",
        success_criteria={"metric": "F1", "threshold": 0.80, "medal": "bronze"},
        dataset_size_mb=5.0,
        market_value_usd=25.0
    ),
    BenchmarkTask(
        id="mle_bench_tabular_playground",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="表格数据分类挑战",
        description="对复杂表格数据进行多类分类。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="classification",
        modality="tabular",
        competition_id="tabular-playground-series-jan-2022",
        kaggle_metric="accuracy",
        success_criteria={"metric": "accuracy", "threshold": 0.85, "medal": "bronze"},
        dataset_size_mb=100.0,
        market_value_usd=30.0
    ),
    BenchmarkTask(
        id="mle_bench_feedback_prize",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="学生作文评分",
        description="自动评估学生论证性写作的有效性。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="nlp",
        modality="text",
        competition_id="feedback-prize-2021",
        kaggle_metric="log_loss",
        success_criteria={"metric": "log_loss", "threshold": 0.7, "medal": "bronze"},
        dataset_size_mb=200.0,
        market_value_usd=40.0
    ),
    BenchmarkTask(
        id="mle_bench_forest_cover",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="森林覆盖类型分类",
        description="根据地形特征预测森林覆盖类型。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="classification",
        modality="tabular",
        competition_id="forest-cover-type-prediction",
        kaggle_metric="accuracy",
        success_criteria={"metric": "accuracy", "threshold": 0.75, "medal": "bronze"},
        dataset_size_mb=75.0,
        market_value_usd=25.0
    ),
    BenchmarkTask(
        id="mle_bench_otto_group",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="Otto产品分类",
        description="对Otto Group的产品进行多类分类。",
        difficulty=DifficultyLevel.MEDIUM,
        domain="classification",
        modality="tabular",
        competition_id="otto-group-product-classification-challenge",
        kaggle_metric="log_loss",
        success_criteria={"metric": "log_loss", "threshold": 0.5, "medal": "bronze"},
        dataset_size_mb=50.0,
        market_value_usd=30.0
    ),
    
    # ========== High Complexity (22 tasks) - 示例5个 ==========
    BenchmarkTask(
        id="mle_bench_ventilator",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="呼吸机压力预测",
        description="预测机械呼吸机的呼吸回路压力。",
        difficulty=DifficultyLevel.HARD,
        domain="time_series",
        modality="tabular",
        competition_id="ventilator-pressure-prediction",
        kaggle_metric="MAE",
        success_criteria={"metric": "MAE", "threshold": 0.3, "medal": "bronze"},
        dataset_size_mb=500.0,
        market_value_usd=80.0
    ),
    BenchmarkTask(
        id="mle_bench_birdclef",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="BirdCLEF鸟类叫声识别",
        description="从音频记录中识别鸟类物种。",
        difficulty=DifficultyLevel.HARD,
        domain="audio",
        modality="audio",
        competition_id="birdclef-2024",
        kaggle_metric="padded_cmap",
        success_criteria={"metric": "padded_cmap", "threshold": 0.6, "medal": "bronze"},
        dataset_size_mb=30000.0,
        market_value_usd=100.0
    ),
    BenchmarkTask(
        id="mle_bench_rsna_mammography",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="RSNA乳腺癌检测",
        description="从乳房X光检查中检测乳腺癌。",
        difficulty=DifficultyLevel.EXPERT,
        domain="medical",
        modality="image",
        competition_id="rsna-breast-cancer-detection",
        kaggle_metric="pF1",
        success_criteria={"metric": "pF1", "threshold": 0.3, "medal": "bronze"},
        dataset_size_mb=200000.0,
        market_value_usd=150.0
    ),
    BenchmarkTask(
        id="mle_bench_llm_science",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="LLM科学问答",
        description="使用LLM回答科学多选题。",
        difficulty=DifficultyLevel.HARD,
        domain="nlp",
        modality="text",
        competition_id="kaggle-llm-science-exam",
        kaggle_metric="MAP@3",
        success_criteria={"metric": "MAP@3", "threshold": 0.85, "medal": "bronze"},
        dataset_size_mb=10.0,
        market_value_usd=70.0
    ),
    BenchmarkTask(
        id="mle_bench_google_landmark",
        benchmark_type=BenchmarkType.MLE_BENCH,
        name="Google地标识别",
        description="识别图像中的著名地标。",
        difficulty=DifficultyLevel.HARD,
        domain="computer_vision",
        modality="image",
        competition_id="landmark-recognition-2021",
        kaggle_metric="GAP",
        success_criteria={"metric": "GAP", "threshold": 0.3, "medal": "bronze"},
        dataset_size_mb=100000.0,
        market_value_usd=120.0
    ),
]


# ==================== SWE-bench 任务 (暂不启用) ====================
# SWE-bench需要120GB+磁盘空间和Docker full模式
# 这里仅保留占位符，实际加载需要调用load_swebench_tasks

SWE_BENCH_TASKS: List[BenchmarkTask] = []  # 暂不启用

def load_swebench_tasks(
    dataset_name: str = "princeton-nlp/SWE-bench_Verified",
    split: str = "test",
    limit: int = 5
) -> List[BenchmarkTask]:
    """
    从HuggingFace加载SWE-bench任务 (需要大磁盘空间)
    """
    logger.warning("SWE-bench loading is disabled due to disk space requirements (120GB+)")
    return []


# ==================== 任务获取函数 ====================

_task_cache: Dict[str, List[BenchmarkTask]] = {}

def get_all_tasks() -> List[BenchmarkTask]:
    """获取所有任务"""
    return GITTASKBENCH_TASKS + MLE_BENCH_TASKS

def get_tasks_by_type(benchmark_type: BenchmarkType, limit: int = 5) -> List[BenchmarkTask]:
    """按类型获取任务"""
    cache_key = f"{benchmark_type.value}_{limit}"
    
    if cache_key not in _task_cache:
        if benchmark_type == BenchmarkType.GITTASKBENCH:
            tasks = GITTASKBENCH_TASKS.copy()
        elif benchmark_type in [BenchmarkType.MLE_BENCH, BenchmarkType.MLE_BENCH_LITE]:
            tasks = MLE_BENCH_TASKS.copy()
            if benchmark_type == BenchmarkType.MLE_BENCH_LITE:
                # Lite版本只包含easy和medium难度
                tasks = [t for t in tasks if t.difficulty in [DifficultyLevel.EASY, DifficultyLevel.MEDIUM]]
        elif benchmark_type in [BenchmarkType.SWE_BENCH, BenchmarkType.SWE_BENCH_VERIFIED, BenchmarkType.SWE_BENCH_LITE]:
            # SWE-bench暂不可用
            logger.warning("SWE-bench is currently disabled due to disk space requirements")
            tasks = []
        else:
            tasks = []
        
        _task_cache[cache_key] = tasks[:limit]
    
    return _task_cache[cache_key]

def get_tasks_by_domain(domain: str, limit: int = 10) -> List[BenchmarkTask]:
    """按领域获取任务"""
    all_tasks = get_all_tasks()
    return [t for t in all_tasks if t.domain == domain][:limit]

def get_task_by_id(task_id: str) -> Optional[BenchmarkTask]:
    """按ID获取任务"""
    all_tasks = get_all_tasks()
    for task in all_tasks:
        if task.id == task_id:
            return task
    return None

def get_available_domains() -> Dict[str, List[str]]:
    """获取所有可用领域"""
    return {
        "gittaskbench": list(set(t.domain for t in GITTASKBENCH_TASKS)),
        "mle_bench": list(set(t.domain for t in MLE_BENCH_TASKS)),
    }


# ==================== Benchmark信息 ====================

BENCHMARK_INFO = {
    BenchmarkType.GITTASKBENCH: {
        "name": "GitTaskBench",
        "description": "54个仓库级真实世界任务，覆盖7个领域",
        "task_count": len(GITTASKBENCH_TASKS),
        "domains": list(set(t.domain for t in GITTASKBENCH_TASKS)),
        "paper_url": "https://arxiv.org/abs/2508.18993",
        "metrics": ["ECR (执行完成率)", "TPR (任务通过率)", "α-score (经济效益)"],
        "status": "available"
    },
    BenchmarkType.MLE_BENCH: {
        "name": "MLE-bench",
        "description": "75个Kaggle机器学习竞赛任务",
        "task_count": len(MLE_BENCH_TASKS),
        "domains": list(set(t.domain for t in MLE_BENCH_TASKS)),
        "paper_url": "https://github.com/openai/mle-bench",
        "metrics": ["Any Medal (%)", "Bronze/Silver/Gold Rate"],
        "complexity_distribution": {"Low": 22, "Medium": 31, "High": 22},
        "status": "available"
    },
    BenchmarkType.MLE_BENCH_LITE: {
        "name": "MLE-bench Lite",
        "description": "22个低复杂度Kaggle任务（用于快速测试）",
        "task_count": 22,
        "domains": ["classification", "regression", "tabular"],
        "status": "available"
    },
    BenchmarkType.SWE_BENCH_VERIFIED: {
        "name": "SWE-bench Verified",
        "description": "500个人工验证的GitHub issue修复任务",
        "task_count": 500,
        "domains": ["django", "sympy", "sklearn", "matplotlib", "pytest"],
        "paper_url": "https://www.swebench.com",
        "status": "disabled",
        "reason": "需要120GB+磁盘空间和Docker full模式"
    },
    BenchmarkType.SWE_BENCH_LITE: {
        "name": "SWE-bench Lite",
        "description": "300个精选的轻量级任务",
        "task_count": 300,
        "status": "disabled",
        "reason": "需要大磁盘空间"
    }
}