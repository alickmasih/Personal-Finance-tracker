from typing import Dict, List, Optional

# Define category keywords for rule-based matching
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    'Food & Dining': [
        'restaurant', 'food', 'dinner', 'lunch', 'breakfast', 'cafe', 'coffee',
        'zomato', 'swiggy', 'uber eats', 'doordash', 'grocery', 'groceries',
        'takeout', 'pizza', 'burger', 'meal'
    ],
    'Transportation': [
        'uber', 'lyft', 'taxi', 'cab', 'bus', 'train', 'metro', 'fuel', 'gas',
        'parking', 'car', 'auto', 'rickshaw', 'transport', 'fare'
    ],
    'Shopping': [
        'amazon', 'flipkart', 'walmart', 'target', 'store', 'mall', 'shop',
        'purchase', 'buy', 'clothes', 'clothing', 'shoes', 'accessories'
    ],
    'Entertainment': [
        'movie', 'theatre', 'concert', 'show', 'netflix', 'spotify', 'prime',
        'disney', 'hulu', 'game', 'gaming', 'entertainment'
    ],
    'Bills & Utilities': [
        'electricity', 'water', 'gas', 'internet', 'wifi', 'phone', 'mobile',
        'bill', 'utility', 'broadband', 'recharge'
    ],
    'Health & Wellness': [
        'doctor', 'hospital', 'medicine', 'medical', 'pharmacy', 'health',
        'healthcare', 'fitness', 'gym', 'workout', 'yoga'
    ],
    'Education': [
        'book', 'course', 'class', 'tutorial', 'training', 'workshop',
        'education', 'school', 'college', 'university', 'tuition'
    ],
    'Housing': [
        'rent', 'maintenance', 'repair', 'furniture', 'home', 'house',
        'apartment', 'flat', 'property'
    ]
}

def categorize_expense(note: str) -> str:
    """
    Categorize an expense based on the note using rule-based matching.
    
    Args:
        note: The expense note/description
        
    Returns:
        The predicted category
    """
    if not note:
        return 'Uncategorized'
    
    note = note.lower().strip()
    
    # Try to match keywords
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in note for keyword in keywords):
            return category
    
    return 'Uncategorized'

# Optional: Add more sophisticated NLP-based categorization
try:
    from transformers import pipeline
    
    # Initialize zero-shot classification pipeline
    classifier = pipeline("zero-shot-classification")
    
    def categorize_expense_nlp(note: str) -> str:
        """
        Categorize an expense using NLP (zero-shot classification).
        
        Args:
            note: The expense note/description
            
        Returns:
            The predicted category
        """
        if not note:
            return 'Uncategorized'
        
        # First try rule-based matching
        rule_based_category = categorize_expense(note)
        if rule_based_category != 'Uncategorized':
            return rule_based_category
        
        # If rule-based fails, use NLP
        try:
            candidate_labels = list(CATEGORY_KEYWORDS.keys())
            result = classifier(note, candidate_labels)
            return result['labels'][0]  # Return the highest confidence category
        except Exception:
            return 'Uncategorized'
            
except ImportError:
    # If transformers is not installed, fallback to rule-based categorization
    categorize_expense_nlp = categorize_expense 