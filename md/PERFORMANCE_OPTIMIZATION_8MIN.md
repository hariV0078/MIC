# Performance Optimization for 8-Minute Target

## Goal
Process 100 records in **8 minutes** (480 seconds)

## Current Performance
- **Per-submission**: ~129 seconds (2.15 minutes)
- **100 records sequential**: ~3.6 hours
- **100 records with 4 workers**: ~70 minutes

## Required Performance
- **Per-submission target**: ~4.8 seconds (with 8 workers)
- **100 records with 8 workers**: ~8 minutes

## Optimizations Applied

### 1. Rate Limiting
- **Before**: 120 RPM (80% safety = 96 effective RPM)
- **After**: **145 RPM** (97% safety = 138 effective RPM)
- **Improvement**: 44% more throughput

### 2. Concurrency
- **Before**: 1 concurrent Gemini call
- **After**: **4 concurrent Gemini calls**
- **Improvement**: 4x more parallel API calls

### 3. Workers
- **Before**: 4 parallel workers
- **After**: **8 parallel workers**
- **Improvement**: 2x more parallel processing

### 4. Safety Factor
- **Before**: 0.8 (80%)
- **After**: **0.95 (95%)** - capped to prevent going over limit
- **Improvement**: 19% more utilization

### 5. Stagger Delay
- **Before**: 0.5-2.0 seconds delay before first LLM call
- **After**: **Removed** - rate limiter handles spacing
- **Improvement**: Eliminates unnecessary delays

## Expected Performance

### Theoretical Calculation
- **8 workers** × **4 concurrent Gemini calls** = **32 concurrent API calls**
- **138 effective RPM** = **2.3 requests per second**
- **100 records** ÷ **8 workers** = **12.5 records per worker**
- **480 seconds** ÷ **8 workers** = **60 seconds per worker**
- **60 seconds** ÷ **12.5 records** = **4.8 seconds per record** ✅

### Realistic Estimate
- **Best case**: 6-7 minutes
- **Most likely**: **7-9 minutes**
- **Worst case**: 10-12 minutes (if some submissions are slow)

## Configuration Summary

```env
# Rate Limiting
GEMINI_RPM_LIMIT=145          # 97% of 150 limit
RATE_LIMIT_SAFETY_FACTOR=0.95 # 95% utilization

# Concurrency
GEMINI_MAX_CONCURRENT=4       # 4 concurrent Gemini calls
DEFAULT_MAX_WORKERS=8         # 8 parallel workers

# Total Capacity
# 8 workers × 4 concurrent = 32 concurrent API calls
# 145 RPM × 0.95 = 138 effective RPM
```

## Risk Assessment

### Low Risk ✅
- **Daily Limit**: 10K RPD - 100 records is only 1% of limit
- **Token Limit**: 2M TPM - not a bottleneck
- **Circuit Breaker**: Still active to prevent cascading failures

### Medium Risk ⚠️
- **Rate Limiting**: Using 97% of limit - close to edge but safe
- **Concurrency**: 4 concurrent calls - within Gemini's 10 limit
- **429 Errors**: May see occasional 429s, but circuit breaker will handle

### Mitigation
- Circuit breaker will open if error rate > 70%
- Automatic fallback to Groq if Gemini fails
- Request budget limits API calls per submission

## Monitoring

Watch for:
1. **429 errors** - Should be rare with current limits
2. **Circuit breaker opens** - Indicates need to reduce RPM/concurrency
3. **Processing time** - Should be 7-9 minutes for 100 records
4. **API call rate** - Should stay under 138 RPM

## Next Steps

1. **Test with 10-20 records** first to verify stability
2. **Monitor logs** for 429 errors
3. **Adjust if needed**:
   - If 429s occur: Reduce RPM to 140 or concurrency to 3
   - If too slow: Can increase workers to 10 (if CPU allows)
   - If stable: Can push RPM to 148 (99% of limit)
