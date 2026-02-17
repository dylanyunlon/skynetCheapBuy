#!/usr/bin/env python
"""
CheapBuy Web Search Module
基于RepoMaster的Web搜索能力

功能:
1. Serper API Google搜索
2. Jina Reader URL解析
3. 深度搜索Agent
4. 搜索结果清理和格式化
"""

import os
import re
import json
import asyncio
import aiohttp
from typing import List, Dict, Any, Optional, Annotated
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


# ==================== 配置 ====================

SERPER_API_URL = "https://google.serper.dev/search"
JINA_READER_URL = "https://r.jina.ai/"


# ==================== Prompt模板 ====================

SYSTEM_MESSAGE_HAS_SUFFICIENT_INFO = """Analyze the search results and determine if there's enough information to answer the user's query. Respond with only 'Yes' or 'No'."""

SYSTEM_MESSAGE_GENERATE_ANSWER = """Generate a comprehensive answer to the user's query based on the provided search results. Be accurate and cite sources when possible."""

SYSTEM_MESSAGE_IMPROVE_QUERY = """You are an AI assistant tasked with improving search queries. 

Given the initial query and current search results, suggest an improved, more specific query that will help find better information.

Current time: {current_time}

Provide only the improved query without any explanation."""


# ==================== 内容清理 ====================

def clean_web_content(content: str) -> str:
    """清理网页内容"""
    # 移除URL
    content = re.sub(r'http[s]?://\S+', '', content)
    
    # 移除Markdown链接但保留文本
    content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
    
    # 移除HTML标签
    content = re.sub(r'<[^>]+>', '', content)
    
    # 移除图片标记
    content = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', content)
    
    # 移除HTML注释
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    
    # 移除导航列表
    content = re.sub(
        r'^\s*[-*]\s+(Home|About|Contact|Menu|Search|Privacy|Terms)\s*$', 
        '', content, flags=re.MULTILINE | re.IGNORECASE
    )
    
    # 移除版权信息
    content = re.sub(r'Copyright .*\d{4}.*', '', content, flags=re.IGNORECASE)
    content = re.sub(r'All rights reserved\.?', '', content, flags=re.IGNORECASE)
    
    # 移除社交媒体文本
    content = re.sub(
        r'(Follow|Like|Share|Subscribe).*(Facebook|Twitter|Instagram|LinkedIn).*', 
        '', content, flags=re.IGNORECASE
    )
    
    # 清理空行
    content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # 移除太短的行（可能是导航项）
    content = '\n'.join(line for line in content.split('\n') if len(line.split()) > 2)
    
    return content.strip()


# ==================== 搜索引擎 ====================

class SerperSearchEngine:
    """Serper搜索引擎 - Google搜索API"""
    
    def __init__(self):
        self.api_key = os.environ.get('SERPER_API_KEY', '')
        self.search_url = SERPER_API_URL
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        gl: str = 'us',
        hl: str = 'en'
    ) -> List[Dict[str, str]]:
        """
        执行Google搜索
        
        Args:
            query: 搜索查询
            max_results: 最大结果数
            gl: 地区代码
            hl: 语言代码
            
        Returns:
            搜索结果列表
        """
        if not self.api_key:
            logger.warning("SERPER_API_KEY not configured")
            return [{"error": "SERPER_API_KEY not configured"}]
        
        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        payload = {
            'q': query,
            'gl': gl,
            'hl': hl,
            'num': max_results
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.search_url, 
                    headers=headers, 
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        return [{"error": f"API error: {response.status}"}]
                    
                    data = await response.json()
                    
                    results = []
                    for item in data.get('organic', []):
                        results.append({
                            'title': item.get('title', ''),
                            'snippet': item.get('snippet', ''),
                            'link': item.get('link', ''),
                            'position': item.get('position', 0)
                        })
                    
                    return results
                    
        except asyncio.TimeoutError:
            return [{"error": "Search timeout"}]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return [{"error": str(e)}]


class WebBrowser:
    """网页浏览器 - 获取URL内容"""
    
    def __init__(self, max_content_length: int = 20000):
        self.jina_key = os.environ.get('JINA_API_KEY', '')
        self.max_content_length = max_content_length
    
    async def browse(self, url: str, clean: bool = True) -> str:
        """
        浏览URL获取内容
        
        Args:
            url: 目标URL
            clean: 是否清理内容
            
        Returns:
            网页内容（Markdown格式）
        """
        # 使用Jina Reader API
        jina_url = f"{JINA_READER_URL}{url}"
        
        headers = {
            'X-Return-Format': 'markdown',
            'X-Timeout': '15'
        }
        
        if self.jina_key:
            headers['Authorization'] = f"Bearer {self.jina_key}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    jina_url, 
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    content = await response.text()
                    
                    if clean:
                        content = clean_web_content(content)
                    
                    if len(content) > self.max_content_length:
                        content = content[:self.max_content_length] + "\n... [truncated]"
                    
                    return content
                    
        except asyncio.TimeoutError:
            return f"Error: Timeout browsing {url}"
        except Exception as e:
            logger.error(f"Browse error for {url}: {e}")
            return f"Error browsing {url}: {e}"
    
    async def browse_multiple(
        self,
        urls: List[str],
        max_parallel: int = 3
    ) -> List[Dict[str, str]]:
        """并行浏览多个URL"""
        results = []
        
        for i in range(0, len(urls), max_parallel):
            batch = urls[i:i + max_parallel]
            tasks = [self.browse(url) for url in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({'url': url, 'content': str(result), 'success': False})
                else:
                    results.append({'url': url, 'content': result, 'success': True})
        
        return results


# ==================== 深度搜索Agent ====================

class DeepSearchAgent:
    """
    深度搜索Agent - 迭代式多轮搜索
    
    特性:
    1. 自动判断信息充分性
    2. 迭代改进查询
    3. 并行获取详细内容
    4. 结果去重和排序
    """
    
    def __init__(
        self,
        ai_engine=None,
        max_iterations: int = 3,
        results_per_iteration: int = 5
    ):
        self.ai_engine = ai_engine
        self.max_iterations = max_iterations
        self.results_per_iteration = results_per_iteration
        
        self.search_engine = SerperSearchEngine()
        self.browser = WebBrowser()
    
    async def search(
        self,
        query: str,
        fetch_content: bool = True
    ) -> Dict[str, Any]:
        """
        执行深度搜索
        
        Args:
            query: 搜索查询
            fetch_content: 是否获取详细内容
            
        Returns:
            搜索结果字典
        """
        all_results = []
        seen_urls = set()
        current_query = query
        
        for iteration in range(self.max_iterations):
            logger.info(f"Deep search iteration {iteration + 1}: {current_query}")
            
            # 执行搜索
            results = await self.search_engine.search(
                current_query, 
                max_results=self.results_per_iteration
            )
            
            if not results or 'error' in results[0]:
                break
            
            # 去重
            new_results = []
            for r in results:
                if r.get('link') and r['link'] not in seen_urls:
                    seen_urls.add(r['link'])
                    new_results.append(r)
            
            if not new_results:
                break
            
            # 获取详细内容
            if fetch_content:
                urls = [r['link'] for r in new_results[:3]]
                contents = await self.browser.browse_multiple(urls)
                
                for r, c in zip(new_results[:3], contents):
                    if c['success']:
                        r['content'] = c['content'][:3000]
            
            all_results.extend(new_results)
            
            # 准备上下文并检查是否足够
            context = self._prepare_context(all_results)
            
            if await self._has_sufficient_info(query, context):
                logger.info("Sufficient information found")
                break
            
            # 改进查询
            current_query = await self._improve_query(query, context)
        
        # 按相关性排序
        all_results = self._sort_by_relevance(query, all_results)
        
        return {
            'query': query,
            'iterations': iteration + 1,
            'total_results': len(all_results),
            'results': all_results,
            'context': self._prepare_context(all_results)
        }
    
    def _prepare_context(self, results: List[Dict]) -> str:
        """准备搜索结果上下文"""
        parts = []
        for i, r in enumerate(results[:10], 1):
            part = f"[{i}] {r.get('title', 'No title')}\n"
            part += f"URL: {r.get('link', '')}\n"
            part += f"Snippet: {r.get('snippet', '')}\n"
            if r.get('content'):
                part += f"Content: {r['content'][:500]}...\n"
            parts.append(part)
        return "\n---\n".join(parts)
    
    async def _has_sufficient_info(self, query: str, context: str) -> bool:
        """检查是否有足够信息"""
        # 启发式检查
        if len(context) < 500:
            return False
        if len(context) > 5000:
            return True
        
        # 如果有AI引擎，使用AI判断
        if self.ai_engine:
            try:
                response = await self.ai_engine.get_completion(
                    messages=[{
                        "role": "user",
                        "content": f"Query: {query}\n\nContext:\n{context[:3000]}\n\nIs there enough information to answer? Reply only Yes or No."
                    }],
                    system_prompt=SYSTEM_MESSAGE_HAS_SUFFICIENT_INFO,
                    max_tokens=10
                )
                return 'yes' in response.get('content', '').lower()
            except:
                pass
        
        return len(context) > 2000
    
    async def _improve_query(self, original_query: str, context: str) -> str:
        """改进搜索查询"""
        if self.ai_engine:
            try:
                response = await self.ai_engine.get_completion(
                    messages=[{
                        "role": "user",
                        "content": f"Initial Query: {original_query}\n\nSearch Results:\n{context[:2000]}\n\nImproved query:"
                    }],
                    system_prompt=SYSTEM_MESSAGE_IMPROVE_QUERY.format(
                        current_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ),
                    max_tokens=100
                )
                improved = response.get('content', '').strip()
                if improved and improved != original_query:
                    return improved
            except:
                pass
        
        # 简单改进：添加更具体的词
        return original_query + " tutorial example how to"
    
    def _sort_by_relevance(self, query: str, results: List[Dict]) -> List[Dict]:
        """按相关性排序"""
        query_words = set(query.lower().split())
        
        def relevance_score(result: Dict) -> float:
            text = (result.get('title', '') + ' ' + result.get('snippet', '')).lower()
            matches = sum(1 for word in query_words if word in text)
            return matches / len(query_words) if query_words else 0
        
        return sorted(results, key=relevance_score, reverse=True)
    
    async def generate_answer(self, query: str, context: str) -> str:
        """基于搜索结果生成答案"""
        if not self.ai_engine:
            return "AI engine not available. Here are the search results:\n\n" + context
        
        try:
            response = await self.ai_engine.get_completion(
                messages=[{
                    "role": "user",
                    "content": f"Query: {query}\n\nSearch Results:\n{context}\n\nProvide a comprehensive answer:"
                }],
                system_prompt=SYSTEM_MESSAGE_GENERATE_ANSWER,
                max_tokens=2000
            )
            return response.get('content', 'No answer generated')
        except Exception as e:
            return f"Error generating answer: {e}"


# ==================== 工具函数 ====================

class WebSearchTools:
    """Web搜索工具集 - 可注册为Agent工具"""
    
    def __init__(self, ai_engine=None):
        self.search_engine = SerperSearchEngine()
        self.browser = WebBrowser()
        self.deep_search = DeepSearchAgent(ai_engine=ai_engine)
    
    async def searching(
        self,
        query: Annotated[str, "搜索查询"]
    ) -> str:
        """
        执行Web搜索
        
        Args:
            query: 搜索关键词
            
        Returns:
            JSON格式的搜索结果
        """
        results = await self.search_engine.search(query, max_results=10)
        return json.dumps(results, ensure_ascii=False, indent=2)
    
    async def browsing(
        self,
        query: Annotated[str, "内容过滤查询"],
        url: Annotated[str, "要浏览的URL"]
    ) -> str:
        """
        浏览特定URL获取内容
        
        Args:
            query: 用于过滤的查询
            url: 目标URL
            
        Returns:
            JSON格式的结果
        """
        content = await self.browser.browse(url)
        
        return json.dumps({
            'query': query,
            'url': url,
            'content': content
        }, ensure_ascii=False)
    
    async def deep_search(
        self,
        query: Annotated[str, "搜索查询"]
    ) -> str:
        """
        执行深度搜索
        
        Args:
            query: 搜索查询
            
        Returns:
            搜索结果和生成的答案
        """
        result = await self.deep_search.search(query)
        answer = await self.deep_search.generate_answer(query, result['context'])
        
        return json.dumps({
            'query': query,
            'iterations': result['iterations'],
            'total_results': result['total_results'],
            'answer': answer,
            'sources': [
                {'title': r['title'], 'url': r['link']}
                for r in result['results'][:5]
            ]
        }, ensure_ascii=False, indent=2)


# ==================== 便捷函数 ====================

async def quick_search(query: str) -> List[Dict]:
    """快速搜索"""
    engine = SerperSearchEngine()
    return await engine.search(query)


async def quick_browse(url: str) -> str:
    """快速浏览URL"""
    browser = WebBrowser()
    return await browser.browse(url)


async def deep_research(query: str, ai_engine=None) -> Dict:
    """深度研究"""
    agent = DeepSearchAgent(ai_engine=ai_engine)
    return await agent.search(query)


if __name__ == "__main__":
    async def test():
        # 测试搜索
        results = await quick_search("Python asyncio tutorial")
        print(f"Found {len(results)} results")
        
        if results and 'error' not in results[0]:
            # 测试浏览
            content = await quick_browse(results[0]['link'])
            print(f"Content length: {len(content)}")
    
    asyncio.run(test())
