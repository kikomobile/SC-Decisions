"""DeepSeek V3 API integration for re-extracting uncertain labels on low-confidence cases.

Uses OpenAI-compatible API. Budget-tracked with $5 total limit.
"""

import os
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum

# Try to import OpenAI client
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("Warning: openai package not installed. LLM fallback will not work.")
    print("Install with: pip install openai>=1.0.0")

# Configuration
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Custom exception for LLM-related errors."""
    pass


@dataclass
class BudgetTracker:
    """Track API usage costs against a budget."""
    total_budget: float = 5.00  # USD
    input_rate: float = 0.27e-6  # $/token for input
    output_rate: float = 1.10e-6  # $/token for output
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    
    @property
    def total_cost(self) -> float:
        """Calculate total cost so far."""
        return (self.total_input_tokens * self.input_rate + 
                self.total_output_tokens * self.output_rate)
    
    @property
    def budget_remaining(self) -> float:
        """Calculate remaining budget."""
        return max(0.0, self.total_budget - self.total_cost)
    
    def can_afford(self, est_input_tokens: int, est_output_tokens: int) -> bool:
        """Check if we can afford estimated token usage."""
        est_cost = (est_input_tokens * self.input_rate + 
                   est_output_tokens * self.output_rate)
        return est_cost <= self.budget_remaining
    
    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Record token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        logger.info(f"Recorded usage: {input_tokens} input, {output_tokens} output tokens. "
                   f"Total cost: ${self.total_cost:.4f}, Remaining: ${self.budget_remaining:.4f}")


def get_client():
    """Get DeepSeek API client.
    
    Reads DEEPSEEK_API_KEY from environment.
    
    Returns:
        OpenAI client configured for DeepSeek API
        
    Raises:
        ValueError: If DEEPSEEK_API_KEY is not set
        ImportError: If openai package is not installed
    """
    if not OPENAI_AVAILABLE:
        raise ImportError("openai package not installed. Install with: pip install openai>=1.0.0")
    
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError(
            "DEEPSEEK_API_KEY environment variable not set. "
            "Set it with: export DEEPSEEK_API_KEY=your_key_here"
        )
    
    return OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL
    )


# System prompt for extraction
SYSTEM_PROMPT = """You are extracting structured fields from Philippine Supreme Court case text.
Given the raw text of a court case, extract the requested fields as JSON.

Output format:
{
  "labels": [
    {
      "label": "<label_name>",
      "text": "<exact text from the input — include OCR errors as-is>",
      "start_offset": <0-based char offset within the provided text>,
      "end_offset": <0-based char offset (exclusive)>
    }
  ]
}

Rules:
- Extract the EXACT text as it appears (preserve OCR errors, original spacing).
- Offsets are character positions within the text you receive (0-based).
- For multi-line fields (parties, votes), include newline characters in the text.
- For ponente, extract ONLY the surname (e.g., "GUTIERREZ, JR." not "GUTIERREZ, JR., J.:").
- For "votes", extract the voting line that appears near the end of the decision, typically formatted as:
  "CONCURRING AND DISSENTING" headers followed by justice names, or
  a single line like "SO ORDERED." followed by justice surnames, or
  lines listing justices with their vote status (e.g., "(On official leave)", "(No part)", "concur", "dissent").
  Include the full voting block from the first justice name to the last.
- If a field is not present in the text, omit it from the output.
- The case text is enclosed in <case_text> tags. Only extract text from within those tags.
"""


def _call_with_retry(client, messages: List[Dict[str, str]], max_retries: int = 3) -> Dict[str, Any]:
    """Call DeepSeek API with retry logic.
    
    Args:
        client: OpenAI client
        messages: List of message dicts for the API
        max_retries: Maximum number of retries on rate limit errors
        
    Returns:
        API response
        
    Raises:
        LLMError: If API call fails after retries
    """
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            return response
        except Exception as e:
            # Check if it's a rate limit error
            error_str = str(e).lower()
            if "rate limit" in error_str and attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(f"Rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                raise LLMError(f"API call failed: {e}")
    
    raise LLMError(f"API call failed after {max_retries} retries")


def extract_with_llm(
    case_text: str,
    labels_to_extract: List[str],
    existing_labels: List[Dict[str, Any]],
    budget: BudgetTracker,
    client = None,
    case_id: str = "unknown"
) -> Optional[List[Dict[str, Any]]]:
    """Extract labels from case text using DeepSeek V3.
    
    Args:
        case_text: Raw text of the case
        labels_to_extract: List of label names to extract
        existing_labels: Existing annotations from regex extraction (for context)
        budget: BudgetTracker to track costs
        client: Optional OpenAI client (will create one if not provided)
        case_id: Case ID for logging
        
    Returns:
        List of annotation dicts in format_version=2 schema, or None if budget exhausted
    """
    if not OPENAI_AVAILABLE:
        logger.warning("OpenAI package not available, skipping LLM extraction")
        return None
    
    # Create client if not provided
    if client is None:
        try:
            client = get_client()
        except (ValueError, ImportError) as e:
            logger.warning(f"Cannot create DeepSeek client: {e}")
            return None
    
    # Estimate token usage (rough approximation)
    # System prompt + user prompt + existing labels context
    est_input_tokens = len(case_text) // 4 + 500  # Rough estimate
    est_output_tokens = 500  # Conservative estimate for JSON response
    
    # Check budget
    if not budget.can_afford(est_input_tokens, est_output_tokens):
        logger.warning(f"Budget exhausted for case {case_id}. "
                      f"Required: ${est_input_tokens * budget.input_rate + est_output_tokens * budget.output_rate:.4f}, "
                      f"Remaining: ${budget.budget_remaining:.4f}")
        return None
    
    # Build user prompt
    existing_context = ""
    if existing_labels:
        existing_context = "Existing annotations (may contain errors):\n"
        for ann in existing_labels:
            label = ann.get("label", "")
            text = ann.get("text", "")
            # Truncate long text for context
            if len(text) > 200:
                text = text[:200] + "..."
            existing_context += f"- {label}: {text}\n"
    
    user_prompt = f"""Extract the following labels from this court case text: {', '.join(labels_to_extract)}

{existing_context}

<case_text>
{case_text}
</case_text>

Extract ONLY from the text between <case_text> tags. Return JSON with the "labels" array."""
    
    # Prepare messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        # Call API with retry
        logger.info(f"Calling DeepSeek API for case {case_id}, extracting {len(labels_to_extract)} labels")
        response = _call_with_retry(client, messages)
        
        # Parse response
        response_text = response.choices[0].message.content
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for case {case_id}: {e}")
            logger.debug(f"Response: {response_text}")
            return None
        
        # Extract labels from response
        llm_labels = result.get("labels", [])
        if not isinstance(llm_labels, list):
            logger.error(f"Invalid response format for case {case_id}: 'labels' is not a list")
            return None
        
        # Record usage
        input_tokens = response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else est_input_tokens
        output_tokens = response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else est_output_tokens
        budget.record_usage(input_tokens, output_tokens)
        
        logger.info(f"Successfully extracted {len(llm_labels)} labels for case {case_id}. "
                   f"Tokens: {input_tokens} in, {output_tokens} out. Cost: ${input_tokens * budget.input_rate + output_tokens * budget.output_rate:.6f}")
        
        return llm_labels
        
    except LLMError as e:
        logger.error(f"LLM API error for case {case_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during LLM extraction for case {case_id}: {e}")
        return None


def convert_llm_labels_to_annotations(
    llm_labels: List[Dict[str, Any]],
    case_start_char: int,
    case_id: str
) -> List[Dict[str, Any]]:
    """Convert LLM-extracted labels to annotation format.
    
    Args:
        llm_labels: Labels from LLM response
        case_start_char: Character offset of case start in volume
        case_id: Case ID for logging
        
    Returns:
        List of annotation dicts in format_version=2 schema
    """
    annotations = []
    
    for label_data in llm_labels:
        label = label_data.get("label", "")
        text = label_data.get("text", "")
        start_offset = label_data.get("start_offset")
        end_offset = label_data.get("end_offset")
        
        # Validate required fields
        if not label or not text or start_offset is None or end_offset is None:
            logger.warning(f"Skipping invalid label data in case {case_id}: {label_data}")
            continue
        
        # Convert case-relative offsets to volume-relative offsets
        start_char = case_start_char + start_offset
        end_char = case_start_char + end_offset
        
        # Basic validation
        if end_offset <= start_offset:
            logger.warning(f"Invalid offsets for label '{label}' in case {case_id}: "
                          f"start_offset={start_offset}, end_offset={end_offset}")
            continue
        
        # Create annotation dict
        annotation = {
            "label": label,
            "text": text,
            "start_char": start_char,
            "end_char": end_char,
            "start_page": None,  # Will be filled by pipeline
            "end_page": None,    # Will be filled by pipeline
            "group": None        # Default, can be updated later
        }
        
        # Special handling for grouped labels
        if label == "case_number":
            annotation["group"] = 0  # Default group for case_number
        
        annotations.append(annotation)
    
    return annotations


def determine_labels_to_re_extract(
    confidence_result: Dict[str, Any],
    confidence_checks: Dict[str, float]
) -> List[str]:
    """Determine which labels to re-extract based on confidence scores.
    
    Args:
        confidence_result: ConfidenceResult from confidence scoring or dict with 'score' and 'flags'
        confidence_checks: Individual check scores (dict check_name -> score)
        
    Returns:
        List of label names to re-extract
    """
    labels_to_re_extract = []
    
    # Check which confidence checks failed (score < 0.5)
    failed_checks = [check_name for check_name, score in confidence_checks.items() 
                     if score < 0.5]
    
    # Map failed checks to affected labels
    check_to_labels = {
        "required_labels_present": ["case_number", "date", "division", 
                                   "doc_type", "votes"],
        "parties_length": ["parties"],
        "votes_length": ["votes"],
        "ponente_known": ["ponente"],
        "ordering_correct": [],  # Affects multiple labels, handled separately
        "no_overlaps": [],  # Affects multiple labels, handled separately
        "date_valid": ["date"]
    }
    
    # Add labels from failed checks
    for check in failed_checks:
        labels_to_re_extract.extend(check_to_labels.get(check, []))
    
    # For ordering and overlap checks, re-extract all labels
    if "ordering_correct" in failed_checks or "no_overlaps" in failed_checks:
        # Re-extract all content labels (not position labels)
        content_labels = [
            "case_number", "date", "division", "parties", "start_syllabus",
            "end_syllabus", "counsel", "ponente", "doc_type", "votes"
        ]
        labels_to_re_extract.extend(content_labels)
    
    # Remove duplicates and ensure we only extract valid labels
    valid_labels = [
        "case_number", "date", "division", "parties",
        "start_syllabus", "end_syllabus", "counsel", "ponente", "doc_type",
        "votes", "start_opinion", "end_opinion"
    ]
    
    labels_to_re_extract = [label for label in set(labels_to_re_extract) 
                           if label in valid_labels]
    
    # Filter out boundary labels that should never be re-extracted by LLM
    boundary_labels = {"start_of_case", "end_of_case", "start_decision", "end_decision"}
    labels_to_re_extract = [label for label in labels_to_re_extract 
                           if label not in boundary_labels]
    
    return labels_to_re_extract


if __name__ == "__main__":
    """Test the LLM fallback module."""
    print("Testing LLM Fallback Module...")
    
    # Check for API key
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("Warning: DEEPSEEK_API_KEY not set. Some tests will be skipped.")
        print("Set it with: export DEEPSEEK_API_KEY=your_key_here")
    
    # Test BudgetTracker
    print("\n1. Testing BudgetTracker...")
    budget = BudgetTracker(total_budget=5.0)
    print(f"  Initial budget: ${budget.total_budget}")
    print(f"  Initial remaining: ${budget.budget_remaining}")
    
    # Test can_afford
    assert budget.can_afford(1000, 500), "Should afford 1000+500 tokens"
    budget.record_usage(1000, 500)
    print(f"  After 1000+500 tokens: remaining=${budget.budget_remaining:.4f}")
    
    # Test get_client (will fail if no API key)
    print("\n2. Testing get_client...")
    try:
        client = get_client()
        print("  [OK] Client created successfully")
    except (ValueError, ImportError) as e:
        print(f"  [FAIL] Client creation failed (expected if no API key): {e}")
    
    # Test label determination
    print("\n3. Testing determine_labels_to_re_extract...")
    test_confidence_checks = {
        "required_labels_present": 0.8,
        "parties_length": 0.0,  # Failed
        "votes_length": 1.0,
        "ponente_known": 0.0,   # Failed
        "ordering_correct": 1.0,
        "no_overlaps": 1.0,
        "date_valid": 1.0
    }
    
    labels = determine_labels_to_re_extract({}, test_confidence_checks)
    print(f"  Failed checks: parties_length, ponente_known")
    print(f"  Labels to re-extract: {labels}")
    assert "parties" in labels, "Should include parties"
    assert "ponente" in labels, "Should include ponente"
    assert "date" not in labels, "Should not include date (check passed)"
    
    # Test conversion function
    print("\n4. Testing convert_llm_labels_to_annotations...")
    test_llm_labels = [
        {
            "label": "parties",
            "text": "LYDIA D. MILANO, petitioner, vs. EMPLOYEES' COMPENSATION COMMISSION",
            "start_offset": 0,
            "end_offset": 70
        },
        {
            "label": "ponente",
            "text": "GUTIERREZ, JR.",
            "start_offset": 100,
            "end_offset": 113
        }
    ]
    
    case_start_char = 1000
    annotations = convert_llm_labels_to_annotations(test_llm_labels, case_start_char, "test_case")
    print(f"  Converted {len(annotations)} annotations")
    for ann in annotations:
        print(f"    - {ann['label']}: '{ann['text'][:50]}...' at chars {ann['start_char']}-{ann['end_char']}")
    
    assert len(annotations) == 2, f"Expected 2 annotations, got {len(annotations)}"
    assert annotations[0]['start_char'] == 1000, f"Expected start_char 1000, got {annotations[0]['start_char']}"
    assert annotations[0]['end_char'] == 1070, f"Expected end_char 1070, got {annotations[0]['end_char']}"
    
    # Test with invalid data
    print("\n5. Testing with invalid LLM labels...")
    invalid_labels = [
        {"label": "parties", "text": "test"},  # missing offsets
        {"label": "", "text": "test", "start_offset": 0, "end_offset": 4},  # empty label
        {"label": "date", "text": "May 30, 1986", "start_offset": 10, "end_offset": 5},  # invalid offsets
    ]
    
    annotations = convert_llm_labels_to_annotations(invalid_labels, 0, "invalid_test")
    print(f"  Converted {len(annotations)} valid annotations from {len(invalid_labels)} invalid inputs")
    assert len(annotations) == 0, "Should skip all invalid labels"
    
    print("\nAll tests passed!")
    print("\nNote: To test actual API calls, set DEEPSEEK_API_KEY environment variable.")
    
   