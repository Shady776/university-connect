import os
import json
from typing import Optional, Dict, Any
import httpx
from dotenv import load_dotenv

load_dotenv()

class AIGradingService:
    
    def __init__(self):
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        
        self.api_key = api_key
        self.base_url = "https://openrouter.ai/api/v1"
        # Free models on OpenRouter (availability may vary):
        # - "google/gemini-2.0-flash-exp:free"
        # - "meta-llama/llama-3-8b-instruct:free"
        # - "microsoft/phi-3-mini-128k-instruct:free"
        self.model = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it:free")
    
    async def grade_submission(
        self,
        submission_content: str,
        assignment_title: str,
        assignment_description: str,
        max_score: float,
        criteria: Optional[str] = None
    ) -> Dict[str, Any]:


        # Build the grading prompt
        prompt = self._build_grading_prompt(
            submission_content=submission_content,
            assignment_title=assignment_title,
            assignment_description=assignment_description,
            max_score=max_score,
            criteria=criteria
        )
        
        try:
            # Call OpenRouter API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": os.getenv("APP_URL", "http://localhost:8000"),
                        "X-Title": "Academic Grading System"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "max_tokens": 2000,
                        "temperature": 0  # Temperature 0 for deterministic, consistent grading
                    },
                    timeout=60.0
                )
                
                response.raise_for_status()
                data = response.json()
            
            # Extract response text from OpenRouter format
            response_text = data["choices"][0]["message"]["content"]
            
            # Try to extract JSON from the response
            # Some models might include markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            # Parse the JSON response
            result = json.loads(response_text)
            
            # Validate and return
            return {
                "score": min(float(result.get("score", 0)), max_score),
                "percentage": float(result.get("percentage", 0)),
                "feedback": result.get("feedback", ""),
                "detailed_breakdown": result.get("detailed_breakdown", {})
            }
            
        except json.JSONDecodeError as e:
            # Fallback if response is not valid JSON
            print(f"JSON decode error: {str(e)}")
            print(f"Response text: {response_text}")
            return {
                "score": 0.0,
                "percentage": 0.0,
                "feedback": "Error: Could not parse AI grading response. Please try again.",
                "detailed_breakdown": {}
            }
        except httpx.HTTPStatusError as e:
            raise Exception(f"OpenRouter API error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise Exception(f"AI grading failed: {str(e)}")
    
    def _build_grading_prompt(
        self,
        submission_content: str,
        assignment_title: str,
        assignment_description: str,
        max_score: float,
        criteria: Optional[str]
    ) -> str:
        """Build the prompt for AI to grade the submission"""
        
        prompt = f"""You are an expert academic grader. Grade the following student submission objectively and fairly.

ASSIGNMENT DETAILS:
Title: {assignment_title}
Description: {assignment_description}
Maximum Score: {max_score}

"""
        
        if criteria:
            prompt += f"""GRADING CRITERIA:
{criteria}

"""
        
        prompt += f"""STUDENT SUBMISSION:
{submission_content}

INSTRUCTIONS:
1. Evaluate the submission based on the assignment description and criteria provided
2. Provide a detailed assessment of strengths and areas for improvement
3. Assign a fair score out of {max_score}
4. Calculate the percentage score
5. DO NOT use any markdown formatting (no bold, italic, headers, or code blocks) in your feedback
6. Write feedback in plain text only, using simple paragraphs

Respond ONLY with a valid JSON object in this exact format (no markdown, no code blocks, no extra text):
{{
    "score": <numeric score out of {max_score}>,
    "percentage": <percentage score 0-100>,
    "feedback": "<comprehensive feedback in plain text without any markdown formatting>",
    "detailed_breakdown": {{
        "strengths": ["<strength 1>", "<strength 2>"],
        "areas_for_improvement": ["<area 1>", "<area 2>"]
    }}
}}

CRITICAL: Return ONLY the JSON object. No markdown code blocks, no additional text before or after."""
        
        return prompt