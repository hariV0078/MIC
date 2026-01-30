# Rate Limiting and API Call Logic

## Overview

The event validation system uses a sophisticated multi-layered approach to manage API rate limits, concurrency, and reliability. This document explains the complete rate limiting and API call architecture.

---

## 1. Token Bucket Rate Limiter

### Algorithm: Rolling Window Token Bucket

**Location**: `event_validator/utils/rate_limiter.py`

The system uses a **Token Bucket** algorithm with a **rolling 60-second window** to track and enforce rate limits.

### Key Components

```python
class TokenBucketRateLimiter:
    - requests_per_minute: Effective RPM after safety factor
    - burst_size: Maximum burst requests allowed
    - safety_factor: Fraction of limit to use (default 0.9 = 90%)
    - _request_times: Deque tracking request timestamps (last 60 seconds)
    - _last_request_time: Last request timestamp for minimum spacing
```

### How It Works

1. **Request Tracking**: Maintains a deque of request timestamps from the last 60 seconds
2. **Limit Check**: Counts requests in the rolling window
3. **Delay Calculation**: 
   - If at limit: Wait until oldest request expires (oldest + 60s - now)
   - If not at limit: Ensure minimum spacing between requests
4. **Token-Aware Adjustment**: Larger requests (>1000 tokens) get slightly longer delays

### Safety Factor

- **Default**: 90% of limit (0.9)
- **Purpose**: Prevents hitting hard limits by using only 90% of capacity
- **Example**: 150 RPM limit → 135 effective RPM (150 × 0.9)

### Token-Aware Rate Limiting

```python
Token Multipliers:
- < 1000 tokens: 1.0x (no delay adjustment)
- 1000-2000 tokens: 1.1x (10% longer delay)
- > 2000 tokens: 1.2x (20% longer delay)
```

**Why?** Larger requests consume more quota, so spacing them out slightly prevents quota exhaustion.

---

## 2. Gemini API Rate Limiting

### Configuration

**Location**: `event_validator/utils/rate_limiter.py` → `get_rate_limiter()`

```python
Default Settings:
- RPM Limit: 150 (gemini-2.5-pro)
- Safety Factor: 0.9 (90%)
- Effective RPM: 135 requests/minute
- Model: gemini-2.5-pro (150 RPM, 10,000 RPD)
```

**Environment Variables**:
- `GEMINI_RPM_LIMIT`: Override RPM limit (default: 150)
- `RATE_LIMIT_SAFETY_FACTOR`: Override safety factor (default: 0.9)

### API Call Flow (Gemini)

**Location**: `event_validator/validators/gemini_client.py` → `_call_gemini()`

```
1. Check Cache
   ↓ (cache miss)
2. Estimate Tokens
   ↓
3. Acquire Rate Limiter Permission
   - Calculate delay based on rolling window
   - Apply token-aware multiplier
   - Wait if needed
   ↓
4. Make API Call
   ↓ (if fails)
5. Retry Logic (max 3 attempts)
   - Exponential backoff
   - Rate limit detection
   ↓
6. Cache Response (if successful)
   ↓
7. Return Result
```

### Caching Strategy

**Cache Keys**: SHA256 hash of `model:prompt:image_hash:pdf_hash`

- **Text calls**: `model:prompt`
- **Image calls**: `model:prompt:image_hash`
- **PDF calls**: `model:prompt:pdf_hash`

**Cache Structure**:
```python
_gemini_response_cache: Dict[str, str]  # Raw API responses
_gemini_parsed_cache: Dict[str, Dict]    # Parsed validation results
```

**Benefits**:
- Avoids redundant API calls for identical content
- Reduces costs and latency
- Improves throughput

### Retry Logic

```python
Max Retries: 3
Backoff Strategy:
- Rate limit errors: Extract delay from error message or exponential backoff
- Other errors: 1 second delay between retries
- Timeout: 30 seconds per attempt
```

---

## 3. Groq API Rate Limiting

### Configuration

**Location**: `event_validator/utils/rate_limiter.py` → `get_groq_rate_limiter()`

```python
Default Settings:
- RPM Limit: 25 (free tier: 30 RPM limit)
- Safety Factor: 0.8 (80% - very conservative)
- Effective RPM: 20 requests/minute
- Model: llama-3.1-8b-instant (text), meta-llama/llama-4-scout-17b-16e-instruct (vision)
```

**Environment Variables**:
- `GROQ_RPM_LIMIT`: Override RPM limit (default: 25)
- `GROQ_RATE_LIMIT_SAFETY_FACTOR`: Override safety factor (default: 0.8)
- `GROQ_MAX_CONCURRENT`: Max concurrent Groq calls (default: 5)

### Concurrency Control: Semaphore

**Location**: `event_validator/validators/groq_client.py`

```python
_groq_semaphore = threading.Semaphore(5)  # Max 5 concurrent Groq calls
```

**Why?** Groq has a lower rate limit (30 RPM), so limiting concurrent calls prevents burst overload.

### API Call Flow (Groq)

**Location**: `event_validator/validators/groq_client.py` → `_call_groq()`

```
1. Check Cache
   ↓ (cache miss)
2. Acquire Semaphore (max 5 concurrent)
   ↓
3. Estimate Tokens
   ↓
4. Acquire Rate Limiter Permission
   - Calculate delay based on rolling window
   - Wait if needed
   ↓
5. Make API Call
   ↓ (if 429 rate limit error)
6. Extract Retry Delay from Error Message
   - Pattern matching: "try again in 2s", "retry in 30s", etc.
   - Add 0.5s buffer
   ↓
7. Wait and Retry (max 3 attempts)
   - Re-acquire rate limiter after wait
   ↓
8. Release Semaphore (always)
   ↓
9. Cache Response (if successful)
   ↓
10. Return Result
```

### Retry Delay Extraction

**Location**: `event_validator/validators/groq_client.py` → `_extract_retry_delay()`

The system parses error messages to extract retry delays:

```python
Patterns:
- "try again in 2s"
- "retry in 30s"
- "wait 60 seconds"
- "retry after 5s"
```

**Default Fallback**: Exponential backoff starting at 2 seconds (2s, 4s, 8s, max 60s)

---

## 4. Concurrency Control

### Global Semaphore (Gemini)

**Location**: `event_validator/api/app.py`

```python
MAX_CONCURRENT_API_CALLS = OPTIMAL_CONCURRENCY * 2  # ~24 for 12 workers
_api_semaphore = threading.Semaphore(MAX_CONCURRENT_API_CALLS)
```

**Calculation**:
```python
GEMINI_RPM = 150
OPTIMAL_CONCURRENCY = min(12, (GEMINI_RPM * 0.8) / 4)  # ~30, capped at 12
MAX_CONCURRENT_API_CALLS = OPTIMAL_CONCURRENCY * 2  # 24
```

**Purpose**: Prevents too many simultaneous API calls, allowing rate limiter to manage timing.

### Thread Pool Executor

**Location**: `event_validator/orchestration/runner.py` → `process_csv()`

```python
max_workers = min(DEFAULT_MAX_WORKERS, len(rows))  # Default: 12
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    # Process submissions in parallel
```

**Benefits**:
- Parallel processing of multiple submissions
- Rate limiter ensures we stay within limits
- Semaphore prevents API overload

---

## 5. Parallel Fallback Mechanism

### Theme Alignment Fallback

**Location**: `event_validator/validators/gemini_client.py` → `check_theme_alignment()`

```
Primary: Gemini (cached)
   ↓ (if fails)
Parallel Fallback:
   ├─ Gemini Retry (no cache)
   └─ Groq Fallback
   ↓ (use first successful response)
Return Result
```

**Implementation**:
```python
with ThreadPoolExecutor(max_workers=2) as executor:
    futures = {
        executor.submit(try_gemini_retry): 'gemini',
        executor.submit(try_groq): 'groq'
    }
    # Wait for first successful response (30s timeout per call)
    for future in as_completed(futures):
        result = future.result(timeout=30)
        if result is not None:
            return result  # Use first successful
```

**Benefits**:
- **Resilience**: Multiple fallback paths
- **Speed**: Parallel execution uses fastest response
- **Efficiency**: Primary uses Gemini (150 RPM), Groq only as backup

---

## 6. Rate Limiter State Management

### Rolling Window Cleanup

The rate limiter automatically removes old requests from the tracking deque:

```python
cutoff_time = now - 60.0  # 60 seconds ago
while self._request_times and self._request_times[0] < cutoff_time:
    self._request_times.popleft()  # Remove expired requests
```

### Minimum Spacing

To prevent burst overload, the rate limiter enforces minimum spacing between requests:

```python
min_interval = 60.0 / self.requests_per_minute  # e.g., 60/135 = 0.44s
time_since_last = now - self._last_request_time
if time_since_last < min_interval:
    delay = (min_interval - time_since_last) * token_multiplier
```

---

## 7. Token Estimation

### Simple Heuristic

**Location**: `event_validator/utils/rate_limiter.py` → `estimate_tokens()`

```python
Text Tokens: len(prompt) // 4  # ~4 characters per token
Image Tokens: 1000 (if has_image)
Total: text_tokens + image_tokens
```

**Note**: This is a rough estimate. Actual tokenization may vary by model.

---

## 8. Error Handling

### Rate Limit Detection

**Gemini**:
- Detects 429 errors
- Extracts retry delays from error messages
- Applies exponential backoff if delay not found

**Groq**:
- Detects 429 errors with pattern matching
- Extracts retry delays from error messages (e.g., "try again in 2s")
- Applies exponential backoff starting at 2 seconds

### Retry Strategy

```python
Max Retries: 3
Backoff:
- Rate limit: Extract delay or exponential (2^attempt seconds)
- Other errors: 1 second delay
- Always re-acquire rate limiter after wait
```

---

## 9. Configuration Summary

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_RPM_LIMIT` | 150 | Gemini requests per minute limit |
| `RATE_LIMIT_SAFETY_FACTOR` | 0.9 | Safety factor for Gemini (90%) |
| `GROQ_RPM_LIMIT` | 25 | Groq requests per minute limit |
| `GROQ_RATE_LIMIT_SAFETY_FACTOR` | 0.8 | Safety factor for Groq (80%) |
| `GROQ_MAX_CONCURRENT` | 5 | Max concurrent Groq API calls |
| `DEFAULT_MAX_WORKERS` | 12 | Max parallel submission workers |

### Default Limits

| API | RPM Limit | Safety Factor | Effective RPM | RPD Limit |
|-----|-----------|---------------|---------------|-----------|
| **Gemini** | 150 | 0.9 (90%) | 135 | 10,000 |
| **Groq** | 25 | 0.8 (80%) | 20 | N/A |

---

## 10. Performance Characteristics

### Throughput Calculation

**For 5,000 submissions** (each needs ~4 API calls):

```
Total API Calls: 5,000 × 4 = 20,000 calls
Gemini Capacity: 135 RPM × 60 minutes = 8,100 calls/hour
Time Required: 20,000 / 8,100 ≈ 2.5 hours (theoretical)
With overhead: ~3.5-4 hours (practical)
```

### Concurrency Benefits

- **12 parallel workers**: Process 12 submissions simultaneously
- **Rate limiter**: Ensures we stay within 135 RPM
- **Semaphore**: Prevents API overload (max 24 concurrent calls)
- **Caching**: Reduces redundant calls (especially for duplicate content)

---

## 11. Best Practices

1. **Always use rate limiter**: Never make API calls without acquiring permission
2. **Respect semaphores**: Acquire before API calls, release in finally block
3. **Cache aggressively**: Use content hashes for deterministic caching
4. **Handle errors gracefully**: Retry with exponential backoff
5. **Monitor rate limits**: Log rate limiter state for debugging
6. **Use safety factors**: Never use 100% of limit (use 80-90%)

---

## 12. Debugging

### Rate Limiter State

```python
rate_limiter = get_rate_limiter()
current_rate = rate_limiter.get_current_rate()  # Current RPM
available_quota = rate_limiter.get_available_quota()  # Available requests
```

### Logging

The system logs:
- Rate limiter delays applied
- Current rate (RPM)
- Token estimates
- Cache hits/misses
- Retry attempts
- Rate limit errors

---

## Summary

The rate limiting system uses:
1. **Token Bucket Algorithm**: Rolling 60-second window
2. **Safety Factors**: 90% for Gemini, 80% for Groq
3. **Token-Aware Delays**: Larger requests get longer delays
4. **Semaphores**: Limit concurrent API calls
5. **Caching**: SHA256-based content caching
6. **Parallel Fallback**: Gemini + Groq simultaneous fallback
7. **Smart Retry**: Extract delays from error messages

This multi-layered approach ensures:
- ✅ **Reliability**: Multiple fallback paths
- ✅ **Efficiency**: Caching and token-aware delays
- ✅ **Safety**: Never exceeds rate limits
- ✅ **Performance**: Parallel processing with controlled concurrency
