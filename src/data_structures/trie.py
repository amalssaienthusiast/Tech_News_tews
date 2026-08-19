"""
Trie data structure for efficient keyword matching.

A Trie (prefix tree) provides O(k) lookup time where k is the length
of the search term, making it ideal for fast keyword detection in text.
This implementation supports:
- Case-insensitive matching
- Phrase matching (multi-word)
- Prefix matching
- Word boundary detection
"""

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Set, Tuple


@dataclass
class TrieNode:
    """
    Node in the Trie structure.
    
    Attributes:
        children: Map of character to child node
        is_end: Whether this node marks end of a word
        word: The complete word if is_end is True
        count: Number of times this word was added
        metadata: Optional metadata associated with the word
    """
    children: Dict[str, "TrieNode"] = field(default_factory=dict)
    is_end: bool = False
    word: Optional[str] = None
    count: int = 0
    metadata: Dict[str, any] = field(default_factory=dict)


class Trie:
    """
    High-performance Trie for keyword matching.
    
    Optimized for tech keyword detection with O(k) lookup time.
    Supports case-insensitive matching and phrase detection.
    
    Example:
        trie = Trie()
        trie.add_words(["artificial intelligence", "machine learning", "AI"])
        
        # Fast matching
        matches = trie.find_all_matches("This article about AI and machine learning")
        # Returns: [("ai", 19), ("machine learning", 27)]
    
    Time Complexity:
        - Insert: O(k) where k is word length
        - Search: O(k)
        - Find all matches: O(n*m) where n is text length, m is max word length
    
    Space Complexity: O(ALPHABET_SIZE * N * M)
        where N is number of words, M is average word length
    """
    
    def __init__(self, case_sensitive: bool = False) -> None:
        """
        Initialize the Trie.
        
        Args:
            case_sensitive: Whether matching should be case-sensitive
        """
        self._root = TrieNode()
        self._case_sensitive = case_sensitive
        self._word_count = 0
        self._max_word_length = 0
    
    def _normalize(self, text: str) -> str:
        """Normalize text based on case sensitivity setting."""
        return text if self._case_sensitive else text.lower()
    
    def insert(
        self, 
        word: str, 
        metadata: Optional[Dict[str, any]] = None
    ) -> None:
        """
        Insert a word into the Trie.
        
        Args:
            word: Word or phrase to insert
            metadata: Optional metadata to associate with the word
        """
        if not word:
            return
        
        normalized = self._normalize(word)
        node = self._root
        
        for char in normalized:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        
        if not node.is_end:
            self._word_count += 1
        
        node.is_end = True
        node.word = word  # Store original (non-normalized) word
        node.count += 1
        if metadata:
            node.metadata.update(metadata)
        
        self._max_word_length = max(self._max_word_length, len(normalized))
    
    def add_words(
        self, 
        words: List[str], 
        metadata: Optional[Dict[str, any]] = None
    ) -> None:
        """
        Add multiple words to the Trie.
        
        Args:
            words: List of words to add
            metadata: Optional metadata for all words
        """
        for word in words:
            self.insert(word, metadata)
    
    def search(self, word: str) -> bool:
        """
        Check if exact word exists in Trie.
        
        Args:
            word: Word to search for
        
        Returns:
            True if word exists, False otherwise
        """
        node = self._find_node(word)
        return node is not None and node.is_end
    
    def starts_with(self, prefix: str) -> bool:
        """
        Check if any word starts with the given prefix.
        
        Args:
            prefix: Prefix to search for
        
        Returns:
            True if any word has this prefix
        """
        return self._find_node(prefix) is not None
    
    def _find_node(self, prefix: str) -> Optional[TrieNode]:
        """Find the node for a given prefix."""
        normalized = self._normalize(prefix)
        node = self._root
        
        for char in normalized:
            if char not in node.children:
                return None
            node = node.children[char]
        
        return node
    
    def find_all_matches(
        self, 
        text: str, 
        word_boundary: bool = True
    ) -> List[Tuple[str, int]]:
        """
        Find all matching keywords in text.
        
        Uses an efficient sliding window approach to find all
        occurrences of Trie words in the input text.
        
        Args:
            text: Text to search in
            word_boundary: If True, only match at word boundaries
        
        Returns:
            List of (matched_word, position) tuples
        """
        if not text:
            return []
        
        normalized = self._normalize(text)
        matches: List[Tuple[str, int]] = []
        text_len = len(normalized)
        
        for start in range(text_len):
            # Optional word boundary check
            if word_boundary and start > 0:
                prev_char = normalized[start - 1]
                if prev_char.isalnum():
                    continue
            
            node = self._root
            
            for end in range(start, min(start + self._max_word_length + 1, text_len)):
                char = normalized[end]
                
                if char not in node.children:
                    break
                
                node = node.children[char]
                
                if node.is_end:
                    # Check word boundary at end
                    if word_boundary and end + 1 < text_len:
                        next_char = normalized[end + 1]
                        if next_char.isalnum():
                            continue
                    
                    matches.append((node.word, start))
        
        return matches
    
    def get_words_with_prefix(self, prefix: str) -> List[str]:
        """
        Get all words that start with the given prefix.
        
        Args:
            prefix: Prefix to search for
        
        Returns:
            List of matching words
        """
        node = self._find_node(prefix)
        if node is None:
            return []
        
        words: List[str] = []
        self._collect_words(node, words)
        return words
    
    def _collect_words(self, node: TrieNode, words: List[str]) -> None:
        """Recursively collect all words from a node."""
        if node.is_end and node.word:
            words.append(node.word)
        
        for child in node.children.values():
            self._collect_words(child, words)
    
    def get_all_words(self) -> List[str]:
        """Get all words in the Trie."""
        words: List[str] = []
        self._collect_words(self._root, words)
        return words
    
    def __len__(self) -> int:
        """Return number of words in Trie."""
        return self._word_count
    
    def __contains__(self, word: str) -> bool:
        """Check if word is in Trie."""
        return self.search(word)
    
    def __iter__(self) -> Iterator[str]:
        """Iterate over all words."""
        return iter(self.get_all_words())


class TechKeywordMatcher:
    """
    Specialized Trie for matching tech keywords.
    
    Pre-populated with common tech terms and provides
    additional scoring based on keyword importance.
    """
    
    # Tech keywords with importance weights
    TECH_KEYWORDS: Dict[str, float] = {
        # AI/ML (highest weight)
        "artificial intelligence": 1.0,
        "machine learning": 1.0,
        "deep learning": 1.0,
        "neural network": 1.0,
        "natural language processing": 1.0,
        "computer vision": 1.0,
        "reinforcement learning": 0.9,
        "generative ai": 1.0,
        "large language model": 1.0,
        "llm": 0.9,
        "gpt": 0.9,
        "transformer": 0.8,
        "ai": 0.7,
        "ml": 0.6,
        
        # Programming
        "programming": 0.8,
        "software development": 0.9,
        "software engineering": 0.9,
        "coding": 0.7,
        "developer": 0.7,
        "open source": 0.8,
        "git": 0.6,
        "github": 0.7,
        "api": 0.7,
        "sdk": 0.6,
        "framework": 0.6,
        "library": 0.5,
        
        # Languages
        "python": 0.7,
        "javascript": 0.7,
        "typescript": 0.7,
        "rust": 0.7,
        "golang": 0.6,
        "java": 0.6,
        "c++": 0.6,
        "kotlin": 0.6,
        "swift": 0.6,
        
        # Cloud & Infrastructure
        "cloud computing": 0.9,
        "aws": 0.8,
        "azure": 0.8,
        "google cloud": 0.8,
        "kubernetes": 0.8,
        "docker": 0.7,
        "microservices": 0.7,
        "serverless": 0.7,
        "devops": 0.7,
        "infrastructure": 0.6,
        
        # Data
        "data science": 0.9,
        "big data": 0.8,
        "database": 0.6,
        "sql": 0.5,
        "nosql": 0.6,
        "data engineering": 0.8,
        "analytics": 0.6,
        
        # Security
        "cybersecurity": 0.9,
        "security": 0.6,
        "encryption": 0.7,
        "vulnerability": 0.7,
        "hacking": 0.6,
        "malware": 0.6,
        "ransomware": 0.7,
        "zero day": 0.8,
        
        # Blockchain & Crypto
        "blockchain": 0.8,
        "cryptocurrency": 0.7,
        "bitcoin": 0.6,
        "ethereum": 0.6,
        "smart contract": 0.7,
        "web3": 0.7,
        "defi": 0.6,
        "nft": 0.5,
        
        # Hardware
        "semiconductor": 0.8,
        "chip": 0.6,
        "processor": 0.6,
        "gpu": 0.7,
        "nvidia": 0.7,
        "intel": 0.6,
        "amd": 0.6,
        
        # Companies & Products
        "startup": 0.7,
        "tech company": 0.7,
        "silicon valley": 0.6,
        "microsoft": 0.5,
        "google": 0.5,
        "apple": 0.5,
        "meta": 0.5,
        "amazon": 0.4,
        "openai": 0.8,
        "anthropic": 0.8,
        
        # Emerging Tech
        "virtual reality": 0.8,
        "augmented reality": 0.8,
        "metaverse": 0.7,
        "iot": 0.7,
        "internet of things": 0.7,
        "5g": 0.6,
        "robotics": 0.8,
        "automation": 0.6,
        "drone": 0.6,
    }
    
    def __init__(self) -> None:
        """Initialize with tech keywords."""
        self._trie = Trie(case_sensitive=False)
        self._weights: Dict[str, float] = {}
        
        for keyword, weight in self.TECH_KEYWORDS.items():
            self._trie.insert(keyword, {"weight": weight})
            self._weights[keyword.lower()] = weight
    
    def find_matches(self, text: str) -> List[Tuple[str, int, float]]:
        """
        Find all tech keyword matches with weights.
        
        Args:
            text: Text to search
        
        Returns:
            List of (keyword, position, weight) tuples
        """
        matches = self._trie.find_all_matches(text)
        return [
            (word, pos, self._weights.get(word.lower(), 0.5))
            for word, pos in matches
        ]
    
    def calculate_tech_score(self, text: str) -> Tuple[float, List[str]]:
        """
        Calculate overall tech relevance score for text.
        
        Uses a scoring algorithm that considers:
        - Number of keyword matches
        - Keyword weights
        - Text length normalization
        - Keyword diversity
        
        Args:
            text: Text to analyze
        
        Returns:
            Tuple of (score 0.0-1.0, list of matched keywords)
        """
        if not text:
            return 0.0, []
        
        matches = self.find_matches(text)
        
        if not matches:
            return 0.0, []
        
        # Extract unique keywords and their weights
        unique_keywords: Dict[str, float] = {}
        for keyword, _, weight in matches:
            key = keyword.lower()
            if key not in unique_keywords:
                unique_keywords[key] = weight
        
        # Calculate score components
        match_count = len(matches)
        unique_count = len(unique_keywords)
        total_weight = sum(unique_keywords.values())
        avg_weight = total_weight / unique_count if unique_count > 0 else 0
        
        # Text length normalization (diminishing returns)
        text_length = len(text)
        length_factor = min(1.0, text_length / 500)  # Normalize to ~500 chars
        
        # Density score (matches per 100 chars)
        density = (match_count / text_length) * 100 if text_length > 0 else 0
        density_score = min(1.0, density / 5)  # Cap at ~5 matches per 100 chars
        
        # Diversity bonus (more unique keywords = higher score)
        diversity_bonus = min(0.3, unique_count * 0.05)
        
        # Combined score
        base_score = (avg_weight * 0.4) + (density_score * 0.4) + diversity_bonus
        final_score = min(1.0, base_score * (0.5 + length_factor * 0.5))
        
        return final_score, list(unique_keywords.keys())
    
    def add_custom_keyword(self, keyword: str, weight: float = 0.7) -> None:
        """Add a custom tech keyword."""
        self._trie.insert(keyword, {"weight": weight})
        self._weights[keyword.lower()] = weight
