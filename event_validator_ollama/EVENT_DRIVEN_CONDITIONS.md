# Event Driven Conditions

## Overview
The `event_driven` field controls how event titles are validated. There are 4 possible values, with **Event Driven 3** being the strictest.

---

## Event Driven Values

| Value | Title Source | Matching Type |
|-------|--------------|---------------|
| **1** | Canonical (system) | Fuzzy |
| **2** | Generated (system) | Fuzzy |
| **3** | User-provided | **STRICT** |
| **4** | Canonical (system) | Fuzzy |

---

## Validation Rules

### Event Driven 1, 2, 4 (Lenient)
- Uses system-generated or canonical title
- Allows fuzzy matching (similar titles accepted)
- More flexible for title variations

**Example**: "AI Ethics Workshop" matches "Workshop on AI Ethics" ✓

---

### Event Driven 3 (Strict)
- Uses user-provided title
- Requires exact match
- No flexibility for variations

**Example**: "AI Ethics Workshop" does NOT match "Workshop on AI Ethics" ✗

---

## Critical Rule: Event Driven 3 Hard Fail

> [!WARNING]
> **If Event Driven = 3 AND PDF title doesn't match → ALL PDF validations fail (0/25 points)**

### What Fails:
1. PDF Title Matches (7 points) → 0
2. Expert Details Present (7 points) → 0
3. Learning Outcomes Align (3 points) → 0
4. Objectives Match (3 points) → 0
5. Participant Info Matches (5 points) → 0

**Total Loss: 25 points**

---

## Validation Flow

### Event Driven 1, 2, 4
```
1. Get system title (canonical/generated)
2. Compare PDF title (fuzzy match OK)
3. Validate theme alignment
4. Run all PDF validations
```

### Event Driven 3
```
1. Get user-provided title
2. Compare PDF title (MUST match exactly)
3. IF mismatch → FAIL all PDF validations
4. IF match → Run all PDF validations
5. Validate theme alignment (strict)
```

---

## Examples

### ✓ Event Driven 3 - Pass
```
event_driven: 3
user_title: "Workshop on AI Ethics"
pdf_title: "Workshop on AI Ethics"

Result: All validations proceed (up to 25 PDF points)
```

### ✗ Event Driven 3 - Fail
```
event_driven: 3
user_title: "Workshop on AI Ethics"
pdf_title: "AI Ethics Seminar"

Result: ALL PDF validations fail (0/25 points)
```

### ✓ Event Driven 1 - Pass
```
event_driven: 1
canonical_title: "Workshop on AI Ethics"
pdf_title: "AI Ethics Workshop"

Result: Fuzzy match accepted (up to 25 PDF points)
```

---

## Quick Reference

> [!TIP]
> - Use **Event Driven 1, 2, or 4** when title flexibility is needed
> - Use **Event Driven 3** only when exact title matching is critical

> [!IMPORTANT]
> Event Driven 3 is the strictest mode - a single title mismatch loses 25 points!

---

_Last updated: 2026-02-13_
