class PromptOrchestrator:
    """Prompt 编排器 - 学习 Lovable.ai 的 prompt 优化策略"""
    
    async def build_project_creation_flow(self, user_input: str) -> Dict[str, Any]:
        """构建项目创建的完整 prompt 流程"""
        
        # 第一步：元 Prompt - 优化用户输入
        meta_prompt = f"""
        作为一个资深的产品经理和架构师，帮我优化这个项目需求：
        
        用户原始输入：{user_input}
        
        请返回一个结构化的项目需求，包含：
        1. 项目类型和技术栈建议
        2. 核心功能分解
        3. 文件结构规划
        4. 部署策略
        5. 具体的实现 prompt
        
        格式要求：
        - 技术栈要具体到框架版本
        - 功能要可测试和验证
        - 文件结构要完整且实用
        - prompt 要适合 AI 代码生成
        """
        
        # 第二步：获取优化后的需求
        optimized_requirement = await self.ai_engine.generate(meta_prompt)
        
        # 第三步：构建具体的代码生成 prompt
        code_prompt = self._build_code_generation_prompt(optimized_requirement)
        
        return {
            "original_input": user_input,
            "optimized_requirement": optimized_requirement,
            "code_prompt": code_prompt,
            "execution_strategy": self._plan_execution_strategy(optimized_requirement)
        }
    
    def _build_code_generation_prompt(self, requirement: Dict) -> str:
        """构建代码生成 prompt"""
        return f"""
        基于以下需求，生成完整的项目代码：
        
        {requirement['detailed_spec']}
        
        要求：
        1. 生成所有必要的文件，包括配置文件
        2. 代码要可以直接运行，无需手动修改
        3. 包含适当的错误处理和日志
        4. 如果是 web 项目，确保响应式设计
        5. 包含基本的测试用例
        
        技术栈：{requirement['tech_stack']}
        文件结构：{requirement['file_structure']}
        """