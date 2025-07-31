# IMERG Adaptive Date Strategy Documentation

## Overview

IMERG (Integrated Multi-satellitE Retrievals for GPM) data has inherent processing delays due to the complex multi-satellite data fusion process. This document outlines the adaptive date strategy implemented to handle IMERG data availability dynamically.

**Important Update**: This implementation uses IMERG **V07B** (Version 07B), which is the current active version. The previous V06B version has been retired and is no longer available, which was causing 404 errors in earlier implementations.

## Problem Statement

### IMERG Data Availability Challenges

1. **Processing Delays**: IMERG data typically has 2-4 day processing delays
2. **Variable Latency**: Different processing levels (Early, Late, Final) have different delays
3. **Target Date Issues**: Requesting data for recent dates (like 2025-07-23) often results in 404 errors
4. **Static Date Ranges**: Fixed date ranges fail when data is not yet available

### Original Implementation Limitation

```python
# Original static approach - fails when data not available
end_date = TARGET_DATE - timedelta(days=1)  # 2025-07-22
start_date = end_date - timedelta(days=6)   # 2025-07-16
```

**Issues:**
- Assumes data is available up to TARGET_DATE - 1
- No fallback when recent data is unavailable
- Fails entire processing when IMERG data is missing

## Adaptive Date Strategy

### Core Concept

Instead of using a fixed date range, the system dynamically finds the **last available IMERG date** and downloads 7 days backward from that point.

### Implementation Algorithm

```python
def find_last_available_imerg_date(username, password, max_lookback_days=30):
    """
    Find the most recent date with available IMERG data
    
    Strategy:
    1. Start from yesterday (TARGET_DATE - 1)
    2. Check each previous day until data is found
    3. Limit search to max_lookback_days to prevent infinite loops
    4. Return the first date with available data
    """
    
    current_date = TARGET_DATE - timedelta(days=1)
    
    for days_back in range(max_lookback_days):
        test_date = current_date - timedelta(days=days_back)
        
        # Generate IMERG filename for test date (V07B - current version)
        filename = f"3B-DAY.MS.MRG.3IMERG.{test_date.strftime('%Y%m%d')}-S000000-E235959.V07B.tif"
        url = f"https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDY.07/{test_date.strftime('%Y')}/{test_date.strftime('%j')}/{filename}"
        
        # Test availability
        response = requests.head(url, auth=(username, password), timeout=30)
        
        if response.status_code == 200:
            print(f"✅ Found available IMERG data: {test_date.strftime('%Y-%m-%d')}")
            return test_date
        else:
            print(f"⚠️ IMERG not available: {test_date.strftime('%Y-%m-%d')} (status: {response.status_code})")
    
    return None  # No data found within lookback period
```

### Adaptive Date Range Calculation

```python
def calculate_adaptive_imerg_range(username, password):
    """
    Calculate optimal IMERG date range based on data availability
    
    Returns:
    - end_date: Last available IMERG date
    - start_date: 7 days before end_date
    - date_range: List of dates to download
    """
    
    # Find last available date
    last_available = find_last_available_imerg_date(username, password)
    
    if last_available is None:
        raise ValueError("No IMERG data available within lookback period")
    
    # Calculate 7-day range ending at last available date
    end_date = last_available
    start_date = end_date - timedelta(days=6)  # 7 days total
    
    # Generate date list
    date_range = []
    current = start_date
    while current <= end_date:
        date_range.append(current)
        current += timedelta(days=1)
    
    return start_date, end_date, date_range
```

## Benefits of Adaptive Strategy

### 1. **Robustness**
- Handles IMERG processing delays gracefully
- No failures due to data unavailability
- Automatic fallback to older dates

### 2. **Data Continuity**
- Always provides 7 days of continuous IMERG data
- Maintains temporal consistency for modeling
- Maximizes data utilization

### 3. **Operational Reliability**
- Reduces script failures in operational environments
- Self-adapting to data provider schedules
- Minimal manual intervention required

### 4. **Flexibility**
- Configurable lookback period (default: 30 days)
- Adaptable to different IMERG processing schedules
- Compatible with different IMERG product versions

## Implementation Details

### Modified IMERG Processing Function

```python
def process_imerg_data_adaptive(output_dir, date_str):
    """Process IMERG data with adaptive date strategy."""
    print("\n🛰️ Processing IMERG data with adaptive date strategy")
    
    try:
        # Get credentials
        username, password = get_imerg_credentials()
        print("✅ IMERG credentials loaded from .env file")
        
        # Find optimal date range
        start_date, end_date, date_range = calculate_adaptive_imerg_range(username, password)
        
        print(f"📅 Adaptive IMERG range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        print(f"📊 Total days: {len(date_range)} days")
        
        # Continue with download and processing...
        
    except Exception as e:
        print(f"❌ IMERG adaptive processing failed: {str(e)}")
        return False
```

### Error Handling Strategy

```python
def robust_imerg_processing(output_dir, date_str):
    """
    Multi-tier fallback strategy for IMERG processing
    """
    
    strategies = [
        {
            'name': 'Primary Strategy',
            'lookback_days': 10,
            'min_days_required': 7
        },
        {
            'name': 'Extended Lookback',
            'lookback_days': 30,
            'min_days_required': 5
        },
        {
            'name': 'Emergency Fallback',
            'lookback_days': 60,
            'min_days_required': 3
        }
    ]
    
    for strategy in strategies:
        try:
            print(f"🎯 Attempting {strategy['name']}...")
            
            # Attempt to find data with current strategy
            start_date, end_date, date_range = calculate_adaptive_imerg_range(
                username, password, 
                max_lookback_days=strategy['lookback_days']
            )
            
            if len(date_range) >= strategy['min_days_required']:
                print(f"✅ {strategy['name']} successful: {len(date_range)} days found")
                return process_imerg_data_range(start_date, end_date, date_range)
            else:
                print(f"⚠️ {strategy['name']} insufficient data: {len(date_range)} < {strategy['min_days_required']} days")
                
        except Exception as e:
            print(f"❌ {strategy['name']} failed: {str(e)}")
            continue
    
    print("❌ All IMERG strategies failed")
    return False
```

## Configuration Options

### Environment Variables

```env
# IMERG processing configuration
IMERG_MAX_LOOKBACK_DAYS=30
IMERG_MIN_DAYS_REQUIRED=5
IMERG_TIMEOUT_SECONDS=60
IMERG_RETRY_ATTEMPTS=3
```

### Adaptive Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_lookback_days` | 30 | Maximum days to search backward |
| `min_days_required` | 5 | Minimum days needed for processing |
| `timeout_seconds` | 60 | HTTP request timeout |
| `retry_attempts` | 3 | Number of retry attempts per file |

## Expected Behavior Examples

### Scenario 1: Recent Data Available
```
Target Date: 2025-07-23
Search Result: 2025-07-21 (last available)
Date Range: 2025-07-15 to 2025-07-21 (7 days)
Status: ✅ Success
```

### Scenario 2: Significant Delay
```
Target Date: 2025-07-23
Search Result: 2025-07-18 (5 days delay)
Date Range: 2025-07-12 to 2025-07-18 (7 days)
Status: ✅ Success with older data
```

### Scenario 3: Extended Outage
```
Target Date: 2025-07-23
Search Result: 2025-07-10 (13 days delay)
Date Range: 2025-07-04 to 2025-07-10 (7 days)
Status: ⚠️ Success with significantly older data
```

## Monitoring and Logging

### Log Messages
```
📅 Adaptive IMERG range: 2025-07-15 to 2025-07-21
📊 Total days: 7 days
⏰ Data age: 2 days behind target
🎯 Processing 7 IMERG files...
```

### Performance Metrics
- **Data Freshness**: Days between last available and target date
- **Search Efficiency**: Number of availability checks required
- **Success Rate**: Percentage of successful adaptive processing runs
- **Fallback Usage**: Frequency of extended lookback strategies

## Future Enhancements

### 1. **Intelligent Caching**
- Cache availability results to reduce API calls
- Daily availability status tracking
- Predictive data availability modeling

### 2. **Multiple Product Support**
- Support for Early, Late, and Final IMERG products
- Automatic product selection based on availability
- Quality-based product prioritization

### 3. **Advanced Fallback Options**
- Integration with alternative precipitation datasets
- Hybrid data sources when IMERG is unavailable
- Gap-filling with climatological data

This adaptive strategy ensures robust IMERG data processing while maintaining operational reliability in production environments with variable data availability.