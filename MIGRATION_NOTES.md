# Migration Notes

## Gemini API Package Migration

The `google.generativeai` package has been deprecated. The code now supports both the new and legacy packages.

### Current Status

- **New Package**: `google-genai` (preferred)
- **Legacy Package**: `google-generativeai` (deprecated, but still works)

### Installation

**Option 1: Use New Package (Recommended)**
```bash
pip install google-genai
```

**Option 2: Use Legacy Package (Shows Deprecation Warning)**
```bash
pip install google-generativeai
```

### Code Changes

The code automatically detects which package is installed:
- If `google-genai` is available, it uses the new API
- If only `google-generativeai` is available, it falls back to the legacy API

### Warning Suppression

The deprecation warning is suppressed in the code, but you may still see it during import. To completely eliminate it:

1. Install the new package: `pip install google-genai`
2. Uninstall the old package: `pip uninstall google-generativeai`

### API Differences

**New API (google-genai):**
```python
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)
contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
response = client.models.generate_content(model="gemini-1.5-pro", contents=contents)
```

**Legacy API (google-generativeai):**
```python
import google.generativeai as genai

genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-pro')
response = model.generate_content(prompt)
```

The code handles both automatically.

