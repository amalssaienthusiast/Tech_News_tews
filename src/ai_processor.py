"""
AI processing utilities for summarization and semantic search.

This module provides AI-powered text processing capabilities using
transformer models for summarization and sentence embeddings for
semantic search functionality.

Models used:
- Summarization: DistilBART (sshleifer/distilbart-cnn-6-6)
- Semantic Search: Sentence-BERT (all-MiniLM-L6-v2)
"""

import logging
from typing import Any, Dict, List, Optional

import torch
from sentence_transformers import SentenceTransformer, util
from transformers import pipeline

from config.settings import (
    MAX_CONTENT_FOR_SUMMARY,
    SEARCH_MODEL,
    SUMMARIZATION_MODEL,
    SUMMARY_MAX_LENGTH,
    SUMMARY_MIN_LENGTH,
)

logger = logging.getLogger(__name__)

# Global variables for AI models (lazy initialization)
_summarizer: Optional[Any] = None
_search_model: Optional[SentenceTransformer] = None
_device: str = "cpu"
_models_initialized: bool = False


def initialize_ai_models() -> bool:
    """
    Initialize AI models for summarization and search.
    
    Loads the summarization pipeline and sentence transformer model.
    Models are loaded lazily and cached globally.
    
    Returns:
        True if models initialized successfully, False otherwise.
    """
    global _summarizer, _search_model, _device, _models_initialized
    
    if _models_initialized:
        return True
    
    try:
        _device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {_device}")
        
        # Initialize summarization pipeline
        logger.info(f"Loading summarization model: {SUMMARIZATION_MODEL}")
        _summarizer = pipeline(
            "summarization",
            model=SUMMARIZATION_MODEL,
            device=0 if _device == "cuda" else -1,
        )
        
        # Initialize sentence transformer model
        logger.info(f"Loading search model: {SEARCH_MODEL}")
        _search_model = SentenceTransformer(SEARCH_MODEL, device=_device)
        
        _models_initialized = True
        logger.info("AI models initialized successfully.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize AI models: {e}")
        _summarizer = None
        _search_model = None
        _models_initialized = False
        return False


def is_initialized() -> bool:
    """
    Check if AI models are initialized.
    
    Returns:
        True if models are ready for use.
    """
    return _models_initialized


def get_device() -> str:
    """
    Get the current compute device.
    
    Returns:
        Device string ('cuda' or 'cpu').
    """
    return _device


def summarize_text(text: str) -> str:
    """
    Generate a summary of the given text.
    
    Uses the DistilBART model to create extractive summaries.
    Handles text truncation and error cases gracefully.
    
    Args:
        text: Text content to summarize.
    
    Returns:
        Generated summary string. Returns placeholder if model
        unavailable or text too short.
    """
    if not _summarizer:
        return "AI summarization is disabled."
    
    if not text:
        return "No content to summarize."
    
    if len(text) < 200:
        return "Text too short for summarization."
    
    try:
        # Truncate text if too long for model
        truncated_content = text[:MAX_CONTENT_FOR_SUMMARY]
        
        # Generate summary
        summary_result = _summarizer(
            truncated_content,
            max_length=SUMMARY_MAX_LENGTH,
            min_length=SUMMARY_MIN_LENGTH,
            do_sample=False,
        )
        
        return summary_result[0]["summary_text"]
        
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return f"Summary generation failed: {str(e)[:100]}"


def build_search_index(articles: List[Dict[str, Any]]) -> Optional[torch.Tensor]:
    """
    Build a semantic search index from articles.
    
    Creates embeddings for article titles and summaries using
    sentence transformers for efficient similarity search.
    
    Args:
        articles: List of article dictionaries with 'title' and
                 optional 'ai_summary' fields.
    
    Returns:
        Tensor of embeddings if successful, None otherwise.
    """
    if not _search_model:
        logger.warning("Search model unavailable.")
        return None
    
    if not articles:
        logger.warning("No articles to index.")
        return None
    
    try:
        # Build corpus from titles and summaries
        corpus = [
            article["title"] + " " + article.get("ai_summary", "")
            for article in articles
        ]
        
        if not corpus:
            return None
        
        logger.info(f"Building search index for {len(corpus)} articles...")
        
        embeddings = _search_model.encode(
            corpus,
            convert_to_tensor=True,
            show_progress_bar=False,
            device=_device
        )
        
        logger.info("Search index built successfully.")
        return embeddings
        
    except Exception as e:
        logger.error(f"Error building search index: {e}")
        return None


def semantic_search(
    query: str,
    embeddings: torch.Tensor,
    articles: List[Dict[str, Any]],
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Perform semantic search on articles.
    
    Uses cosine similarity between query embedding and article
    embeddings to find the most relevant articles.
    
    Args:
        query: Search query string.
        embeddings: Pre-computed article embeddings tensor.
        articles: List of article dictionaries.
        top_k: Number of top results to return.
    
    Returns:
        List of result dictionaries with 'score' and 'article' keys,
        sorted by relevance score descending.
    """
    if not _search_model:
        logger.error("Search model unavailable.")
        return []
    
    if embeddings is None:
        logger.error("No embeddings available for search.")
        return []
    
    if not articles:
        logger.error("No articles to search.")
        return []
    
    try:
        # Encode query
        query_embedding = _search_model.encode(
            query,
            convert_to_tensor=True,
            device=_device
        )
        
        # Calculate cosine similarity
        cos_scores = util.pytorch_cos_sim(query_embedding, embeddings)[0]
        
        # Get top results
        top_results_count = min(top_k, len(articles))
        top_results = torch.topk(cos_scores, k=top_results_count)
        
        results: List[Dict[str, Any]] = []
        for score, idx in zip(top_results[0], top_results[1]):
            results.append({
                "score": score.item(),
                "article": articles[idx.item()]
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Error during semantic search: {e}")
        return []


def get_embedding(text: str) -> Optional[torch.Tensor]:
    """
    Get the embedding vector for a piece of text.
    
    Args:
        text: Text to encode.
    
    Returns:
        Embedding tensor if successful, None otherwise.
    """
    if not _search_model:
        return None
    
    try:
        return _search_model.encode(
            text,
            convert_to_tensor=True,
            device=_device
        )
    except Exception as e:
        logger.error(f"Error getting embedding: {e}")
        return None


def compute_similarity(text1: str, text2: str) -> float:
    """
    Compute semantic similarity between two texts.
    
    Args:
        text1: First text.
        text2: Second text.
    
    Returns:
        Cosine similarity score (0.0 to 1.0).
    """
    if not _search_model:
        return 0.0
    
    try:
        emb1 = _search_model.encode(text1, convert_to_tensor=True, device=_device)
        emb2 = _search_model.encode(text2, convert_to_tensor=True, device=_device)
        
        similarity = util.pytorch_cos_sim(emb1, emb2)[0][0]
        return similarity.item()
        
    except Exception as e:
        logger.error(f"Error computing similarity: {e}")
        return 0.0