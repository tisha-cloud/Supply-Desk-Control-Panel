import os
import json
import re
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class AIClient:
    """
    Unified multi-model AI Client supporting Google Gemini, OpenAI, and Anthropic Claude APIs.
    """
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

        self.claude_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.claude_model = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022").strip()

        self.default_provider = os.getenv("DEFAULT_AI_PROVIDER", "gemini").lower()

    def get_active_provider(self):
        """Returns the active AI provider based on key availability."""
        if self.default_provider == "gemini" and self.gemini_key:
            return "gemini"
        if self.default_provider == "openai" and self.openai_key:
            return "openai"
        if self.default_provider == "claude" and self.claude_key:
            return "claude"

        # Fallback to any provider with an available API key
        if self.gemini_key: return "gemini"
        if self.openai_key: return "openai"
        if self.claude_key: return "claude"
        return "none"

    def generate_text(self, prompt, provider=None, system_prompt=None):
        """Generates text completion using the specified or default AI provider."""
        target_provider = provider or self.get_active_provider()

        if target_provider == "gemini" and self.gemini_key:
            return self._call_gemini(prompt, system_prompt)
        elif target_provider == "openai" and self.openai_key:
            return self._call_openai(prompt, system_prompt)
        elif target_provider == "claude" and self.claude_key:
            return self._call_claude(prompt, system_prompt)
        else:
            return f"[AI Client Note: API Key not set for {target_provider}. Please configure GEMINI_API_KEY in .env file.]"

    def _call_gemini(self, prompt, system_prompt=None):
        """Calls Google Gemini REST API."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_key}"
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System Context: {system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {"contents": contents}
        headers = {"Content-Type": "application/json"}

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
            return f"Gemini API Response Error ({resp.status_code}): {resp.text}"
        except Exception as e:
            return f"Gemini Connection Error: {str(e)}"

    def _call_openai(self, prompt, system_prompt=None):
        """Calls OpenAI Chat Completions REST API."""
        url = "https://api.openai.com/v1/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.openai_model,
            "messages": messages,
            "temperature": 0.7
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_key}"
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            return f"OpenAI API Response Error ({resp.status_code}): {resp.text}"
        except Exception as e:
            return f"OpenAI Connection Error: {str(e)}"

    def _call_claude(self, prompt, system_prompt=None):
        """Calls Anthropic Claude REST API."""
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": self.claude_model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_prompt:
            payload["system"] = system_prompt

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.claude_key,
            "anthropic-version": "2023-06-01"
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data["content"][0]["text"].strip()
            return f"Claude API Response Error ({resp.status_code}): {resp.text}"
        except Exception as e:
            return f"Claude Connection Error: {str(e)}"

    def parse_natural_language_query(self, user_query):
        """Parses a user search prompt into structured search criteria using Gemini AI or smart regex fallback."""
        if not user_query or not user_query.strip():
            return {"query": ""}

        active = self.get_active_provider()
        if active != "none":
            prompt = f"""
            You are an AI Real Estate Analyst. Parse the user search query into a clean JSON object with keys:
            - micromarket: string or null (e.g. "Outer Ring Road", "Whitefield", "Koramangala", "Hebbal", "E-City", "Indiranagar", "CBD")
            - fitout: string or null (e.g. "Warm Shell", "Bare Shell", "Fully Furnished", "Managed Office")
            - min_area: number or null
            - max_area: number or null
            - min_rent: number or null
            - max_rent: number or null
            - developer: string or null

            User Query: "{user_query}"
            Return ONLY raw JSON, no markdown formatting.
            """
            result_text = self.generate_text(prompt)
            if result_text and not result_text.startswith("Gemini"):
                try:
                    cleaned = result_text.replace("```json", "").replace("```", "").strip()
                    return json.loads(cleaned)
                except Exception:
                    pass

        # Smart regex extraction fallback
        parsed = {"query": user_query}
        mm_m = re.search(r'(ORR|Outer Ring Road|Whitefield|Koramangala|Indiranagar|Hebbal|E-City|CBD|HSR)', user_query, re.I)
        fit_m = re.search(r'(Warm Shell|Bare Shell|Fully Furnished|Managed Office|Plug & Play)', user_query, re.I)
        area_m = re.search(r'(\d+)\s*(?:k|thousand|sqft|sft|sq ft)', user_query, re.I)
        rent_m = re.search(r'(?:under|below|max)\s*(\d+)', user_query, re.I)

        if mm_m: parsed['micromarket'] = mm_m.group(1)
        if fit_m: parsed['fitout'] = fit_m.group(1)
        if area_m:
            val = float(area_m.group(1))
            if val < 500 and 'k' in user_query.lower(): val *= 1000
            parsed['min_area'] = val
        if rent_m: parsed['max_rent'] = float(rent_m.group(1))

        return parsed
