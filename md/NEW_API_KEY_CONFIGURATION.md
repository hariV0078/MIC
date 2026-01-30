# New API Key Configuration

## Gemini API Rate Limits (gemini-2.5-pro)

Based on actual API limits:
- **RPM**: 150 requests per minute
- **TPM**: 2M tokens per minute  
- **RPD**: 10K requests per day

## Configuration Changes

### 1. Rate Limiting
- **GEMINI_RPM_LIMIT**: Set to **120 RPM** (80% of 150 limit)
  - Leaves 20% safety buffer
  - Prevents hitting hard limits
  - Allows for burst handling

### 2. Concurrency
- **GEMINI_MAX_CONCURRENT**: **1** (unchanged)
  - Gemini is strict about concurrent requests
  - Even with higher RPM, concurrency must stay at 1

### 3. Removed Fixed Delays
- **Removed 5-second minimum delay** before API calls
  - Rate limiter now handles spacing automatically
  - With 120 RPM, minimum spacing is ~0.5 seconds
  - More efficient while still safe

### 4. Safety Factor
- **RATE_LIMIT_SAFETY_FACTOR**: **0.8** (80%)
  - Effective rate: 120 RPM × 0.8 = **96 RPM**
  - Double safety buffer for stability

### 5. Jitter
- **Enabled**: Random spacing multiplier (0.9x - 1.6x)
  - Prevents thread synchronization
  - Smooths request distribution

## Expected Performance

### For 100 Records:
- **Before** (30 RPM): ~26 minutes
- **After** (96 effective RPM): **~8-10 minutes** (2.5-3x faster)

### For 5000 Records:
- **Before**: ~21 hours
- **After**: **~7-8 hours** (2.5-3x faster)

## Key Improvements

1. **4x Higher Throughput**: 96 RPM vs 24 RPM (30 × 0.8)
2. **No Fixed Delays**: Rate limiter handles spacing intelligently
3. **Proper Safety Buffers**: 20% buffer at RPM level, 20% at safety factor
4. **Maintains Stability**: Still conservative enough to avoid 429s

## Environment Variables (.env)

```env
# Gemini Rate Limiting (New API Key)
GEMINI_RPM_LIMIT=120
GEMINI_MAX_CONCURRENT=1
RATE_LIMIT_SAFETY_FACTOR=0.8
GEMINI_JITTER_ENABLED=true
GEMINI_JITTER_MIN=0.9
GEMINI_JITTER_MAX=1.6

# Groq Rate Limiting (Unchanged)
GROQ_RPM_LIMIT=20
GROQ_MAX_CONCURRENT=1
GROQ_RATE_LIMIT_SAFETY_FACTOR=0.8

# Concurrency
DEFAULT_MAX_WORKERS=4
```

## Important Notes

1. **Daily Limit**: 10K RPD - monitor usage for large batches
2. **Token Limit**: 2M TPM - should not be a bottleneck
3. **Concurrency**: Must stay at 1 for Gemini (API limitation)
4. **Rate Limiter**: Automatically enforces proper spacing

## Testing Recommendations

1. Start with small batch (10-50 records) to verify stability
2. Monitor logs for 429 errors
3. Check rate limiter stats: `get_current_rate()`
4. Verify circuit breaker doesn't open prematurely
5. Scale up gradually to full batch size
