# skynetCheapBuy - Agentic Loop 改造项目

## 文件清单 (2026-02-17 20:29)

### 🔴 第一优先级：AI 调用链核心
```
app/core/ai_engine.py          # 旧 AI 引擎
app/core/ai/engine.py          # 新 AI 引擎（重构版）
app/core/ai/plugin_system.py   # 插件系统
app/plugins/ai_providers/      # Provider 实现（实际调 API）
app/config.py                  # 配置（API KEY/BASE URL）
```

### 🟠 第二优先级：代码提取 & 执行
```
app/core/code_extractor.py     # 从 AI 回复中提取代码
app/core/script_executor.py    # 执行提取的代码
app/services/enhanced_code_service.py  # 增强代码服务
```

### 🟡 第三优先级：Agent & API
```
app/api/v2/agent.py            # Agent API 端点
app/api/v2/chat.py             # Chat API 端点
app/core/agents/code_agent.py  # Code Agent 实现
```
