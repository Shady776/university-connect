from pydantic import Field
import os
import json
from typing import Optional, Dict, Any
import httpx
from dotenv import load_dotenv
from pydantic_ai import Agent 
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings
from pydantic import BaseModel
from app.config import CONFIG

load_dotenv()

class AIGradingService:
    class GradingResponse(BaseModel):
        score: int = Field(..., description="Score of the submission from 1-100")
        percentage: float = Field(..., description="Percentage of the submission")
        feedback: str = Field(..., description="Feedback for the submission")
        detailed_breakdown: Dict[str, Any] = Field(..., description="Detailed breakdown of the submission")

        
    def __init__(self):
        self.model = OpenAIChatModel(
            CONFIG.OPENROUTER_MODEL,
            provider=OpenRouterProvider(
                api_key=CONFIG.OPENROUTER_API_KEY
            ),
            settings=ModelSettings(temperature=0)
        )
        self.agent: Agent = self._setup_agent()
    
    def _setup_agent(self) -> Agent:
        return Agent(
            model=self.model,
            output_type=self.GradingResponse,
        )  
    async def grade_submission(
        self,
        submission_content: str,
        assignment_title: str,
        assignment_description: str,
        max_score: float,
        criteria: Optional[str] = None
    ) -> Dict[str, Any]:


        # Build the grading prompt
        self.agent.system_prompt = self._build_grading_prompt(
            assignment_title=assignment_title,
            assignment_description=assignment_description,
            max_score=max_score,
            criteria=criteria
        )

        result = await self.agent.run(f"""Submission Content: {submission_content}""")
        return result.output
        
        
            
    
    def _build_grading_prompt(
        self,
        assignment_title: str,
        assignment_description: str,
        max_score: float,
        criteria: Optional[str]
    ) -> str:
        """Build the prompt for AI to grade the submission"""
        
        prompt = f"""
        You are a code grading bot, you are to grade the student coding assignments.
        Based on the following criteria
        Assignment Title: {assignment_title}
        Assignment Description: {assignment_description}
        Max Score: {max_score}
        Grading_criteria: {criteria}
        """

        return prompt