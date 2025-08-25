"""
Field Extractor - Parse field requests from natural language
"""

import re
from typing import Dict, List

class FieldExtractor:
    """Extract field details from Jira ticket text"""
    
    def extract_field_details(self, summary: str, description: str) -> Dict:
        """Extract field name, type, and options from ticket text"""
        text = f"{summary} {description}".lower()
        print(f"🔍 Analyzing text for field details: '{text[:100]}...'")
        
        field_name = self._extract_field_name(text)
        field_type = self._detect_field_type(text)
        options = self._extract_options(text, field_type)
        
        if field_name:
            field_name = self._clean_field_name(field_name)
            print(f"🧹 Cleaned field name: '{field_name}'")
        
        result = {
            "field_name": field_name,
            "field_type": field_type,
            "field_options": options[:10],
            "raw_text": text[:200]
        }
        
        print(f"📋 Final extracted details: {result}")
        return result
    
    def _extract_field_name(self, text: str) -> str:
        """Extract field name using improved patterns"""
        field_name = ""
        
        name_patterns = [
            r'field called\s+"([^"]+)"',
            r'field called\s+([^"\n,\.]+)',
            r'create.*?field.*?called["\s]*([^"\'\n,\.]+)',
            r'field.*?called["\s]*([^"\'\n,\.]+)', 
            r'custom field["\s]*["\']([^"\'\n]+)["\']',
            r'field.*?named["\s]*([^"\'\n,\.]+)'
        ]
        
        for i, pattern in enumerate(name_patterns):
            match = re.search(pattern, text)
            if match:
                field_name = match.group(1).strip().strip('"\'')
                print(f"✅ Pattern {i+1} matched: '{field_name}'")
                if field_name and len(field_name) > 2:
                    break
        
        return field_name
    
    def _detect_field_type(self, text: str) -> str:
        """Detect field type from text"""
        if any(word in text for word in ["select", "dropdown", "list", "options", "choice"]):
            return "select"
        elif any(word in text for word in ["multiselect", "multiple"]):
            return "multiselect"
        elif any(word in text for word in ["textarea", "text area", "long text"]):
            return "textarea"
        elif any(word in text for word in ["number", "numeric", "integer"]):
            return "number"
        elif any(word in text for word in ["date", "calendar"]):
            return "date"
        else:
            return "text"
    
    def _extract_options(self, text: str, field_type: str) -> List[str]:
        """Extract options for select fields"""
        options = []
        
        if field_type not in ["select", "multiselect"]:
            return options
        
        print(f"🎚️  Looking for options since this is a {field_type} field...")
        
        option_patterns = [
            r'options?\s+"([^"]+)"',
            r'with\s+the\s+options?\s+"([^"]+)"',
            r'with\s+"([^"]+)"',
            r'options?\s*:\s*"([^"]+)"',
            r'options?\s*:\s*([^\.]+)',
            r'with\s+([^\.]+)'
        ]
        
        for pattern in option_patterns:
            match = re.search(pattern, text)
            if match:
                options_text = match.group(1).strip()
                print(f"🎯 Found options text: '{options_text}'")
                
                raw_options = re.split(r'[,;/\n]|\sand\s|\sor\s', options_text)
                options = [opt.strip().strip('"\'') for opt in raw_options if opt.strip() and len(opt.strip()) > 1]
                options = [opt for opt in options if opt.lower() not in ['the', 'options', 'list', 'with', 'following']]
                
                print(f"📝 Parsed options: {options}")
                if options:
                    break
        
        return options
    
    def _clean_field_name(self, field_name: str) -> str:
        """Clean up field name for proper formatting"""
        for separator in [' need', ' with', ' for', ' in', ' that', ' which', ' options']:
            if separator in field_name.lower():
                field_name = field_name[:field_name.lower().find(separator)]
                break
        
        field_name = field_name.strip()
        field_name = ' '.join(word.capitalize() for word in field_name.split())
        
        if len(field_name) > 50:
            words = field_name.split()
            field_name = ' '.join(words[:4])
        
        return field_name

# Create a standalone function for backward compatibility
_extractor = FieldExtractor()
extract_field_details = _extractor.extract_field_details