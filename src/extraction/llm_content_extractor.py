import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class LLMContentExtractor:
    """
    Uses a small, fast LLM to identify article content vs noise based on semantic understanding.
    Can run locally with quantized models or use API calls.
    """
    
    # Prompt template for content extraction
    EXTRACTION_PROMPT = """
    Analyze the following HTML and extract ONLY the main article content.
    Remove: headers, footers, navigation, ads, related posts, sidebars, comments.
    Preserve: article title, author, publish date, and the full article body.
    
    Return the extracted content as clean text, maintaining paragraphs.
    
    HTML:
    {html_snippet}
    
    Extracted Content:
    """

    def __init__(self, use_local: bool = True, model_path: str = None):
        """
        Args:
            use_local: If True, uses local quantized model (Llama-3-8B-Q4)
            model_path: Path to local model file
        """
        self.use_local = use_local
        self.model_path = model_path
        
        if use_local:
            try:
                from llama_cpp import Llama
                self.model = Llama(
                    model_path=model_path or "models/llama-3-8b-q4.gguf",
                    n_ctx=2048,
                    n_threads=4,
                    verbose=False
                )
                logger.info("Local LLM loaded for content extraction")
            except ImportError:
                logger.warning("llama-cpp not installed, falling back to heuristic mode")
                self.use_local = False
                self.model = None
            except Exception as e:
                logger.warning(f"Failed to load local LLM: {e}")
                self.use_local = False
                self.model = None
        else:
            # Could integrate with OpenAI/Anthropic APIs
            self.model = None

    def extract_with_llm(self, html: str, url: str) -> Optional[str]:
        """Use LLM to intelligently extract content"""
        
        # Pre-process: extract main content area to reduce token usage
        html_snippet = self._extract_main_content_area(html)
        
        if len(html_snippet) < 1000:
            logger.warning("HTML snippet too short for LLM analysis")
            return None
        
        if self.use_local and self.model:
            try:
                prompt = self.EXTRACTION_PROMPT.format(html_snippet=html_snippet[:15000])
                
                response = self.model(
                    prompt,
                    max_tokens=4000,
                    temperature=0.1,
                    stop=["</s>", "HTML:"],
                    echo=False
                )
                
                extracted = response['choices'][0]['text'].strip()
                
                # Validate extracted content
                if len(extracted) > 500 and '\n\n' in extracted:
                    logger.info(f"LLM extraction successful: {len(extracted)} chars")
                    return extracted
                
            except Exception as e:
                logger.error(f"LLM extraction failed: {e}")
        
        return None
    
    def _extract_main_content_area(self, html: str) -> str:
        """Smart pre-processing to extract potential content areas"""
        
        # Look for article tags
        article_match = re.search(r'<article[^>]*>.*?</article>', html, re.S | re.I)
        if article_match:
            return article_match.group(0)
        
        # Look for main content divs
        main_match = re.search(r'<main[^>]*>.*?</main>', html, re.S | re.I)
        if main_match:
            return main_match.group(0)
        
        # Look for content-rich divs by class/id patterns
        patterns = [
            r'<div[^>]*class="[^"]*(content|article|post|story)[^"]*"[^>]*>.*?</div>',
            r'<div[^>]*id="[^"]*(content|article|post|story)[^"]*"[^>]*>.*?</div>'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.S | re.I)
            if match:
                return match.group(0)
        
        # Fallback: return entire body
        body_match = re.search(r'<body[^>]*>.*?</body>', html, re.S | re.I)
        return body_match.group(0) if body_match else html
