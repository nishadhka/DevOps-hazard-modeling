# Local to Cluster Testing Strategy for Flox Operations

## Overview
This guide outlines a systematic approach for testing the unified climate dataset with flox polygon operations locally before deploying to a Coiled Dask cluster.

## Testing Strategy Framework

### Phase 1: Local Validation (Single Zone, Small Dataset)

#### Test Configuration
```python
# Minimal test parameters
TEST_CONFIG = {
    'zones': ['zone1'],  # Single zone for initial testing
    'time_range': pd.date_range('2024-01-01', periods=3, freq='D'),
    'variables': ['pet', 'chirps', 'imerg'],
    'chunks': (1, 100, 100),  # Small chunks for local testing
    'resolution': '1km'
}
```

#### Local Test Script
```python
# test_local_flox_operations.py
import xarray as xr
import pandas as pd
from dask.distributed import Client, LocalCluster
import time
from utils import process_zone_from_combined, zone_mean_df

def test_local_polygon_operations():
    """Test flox operations on unified dataset locally"""
    
    # 1. Setup local Dask client
    cluster = LocalCluster(
        n_workers=2,
        threads_per_worker=2, 
        memory_limit='2GB'
    )
    client = Client(cluster)
    
    try:
        # 2. Load unified dataset (small subset)
        unified_ds = create_test_unified_dataset()
        
        # 3. Load and process zone shapefile
        zone_ds, subset_ds, zone_extent = process_zone_from_combined(
            'zones_shapefiles_20250320/zone1.shp',
            'zone1',
            1,  # 1km resolution
            unified_ds
        )
        
        # 4. Test flox aggregation for each variable
        results = {}
        for var in ['pet', 'chirps', 'imerg']:
            print(f"Testing {var} aggregation...")
            start_time = time.time()
            
            var_ds = subset_ds[var]
            zone_results = zone_mean_df(var_ds, zone_ds)
            
            runtime = time.time() - start_time
            results[var] = {
                'data': zone_results,
                'runtime': runtime,
                'memory_usage': var_ds.nbytes / 1e6  # MB
            }
            
            print(f"{var}: {runtime:.2f}s, {results[var]['memory_usage']:.1f}MB")
        
        return results
        
    finally:
        client.close()
        cluster.close()

def create_test_unified_dataset():
    """Create small test version of unified dataset"""
    # Implementation from create_east_africa_virtual_dataset.py
    # but with reduced spatial/temporal dimensions
    pass
```

### Phase 2: Local Scaling (Multiple Zones, Extended Time)

#### Scaling Test Configuration
```python
SCALING_CONFIG = {
    'zones': ['zone1', 'zone2', 'zone3'],  # Multiple zones
    'time_range': pd.date_range('2024-01-01', periods=15, freq='D'),
    'chunks': (5, 300, 300),  # Intermediate chunk size
    'parallel_zones': True  # Test concurrent zone processing
}
```

#### Performance Benchmarking
```python
def benchmark_local_performance():
    """Benchmark local performance before cluster scaling"""
    
    performance_metrics = {
        'single_zone': {},
        'multi_zone': {},
        'memory_profile': {},
        'scaling_efficiency': {}
    }
    
    # Test 1: Single zone performance
    for time_steps in [1, 5, 10, 15]:
        runtime = test_zone_with_timesteps('zone1', time_steps)
        performance_metrics['single_zone'][time_steps] = runtime
    
    # Test 2: Multi-zone parallel processing
    for num_zones in [1, 2, 3, 6]:
        zones = [f'zone{i}' for i in range(1, num_zones + 1)]
        runtime = test_multiple_zones_parallel(zones)
        performance_metrics['multi_zone'][num_zones] = runtime
    
    # Test 3: Memory scaling
    performance_metrics['memory_profile'] = profile_memory_usage()
    
    return performance_metrics
```

### Phase 3: Cluster Preparation and Testing

#### Cluster Configuration
```python
# cluster_config.py
CLUSTER_CONFIG = {
    'coiled': {
        'name': 'climate-flox-cluster',
        'software': 'environment.yml',
        'n_workers': 10,
        'worker_memory': '8GB',
        'scheduler_memory': '4GB',
        'worker_cpu': 2
    },
    'chunks': (5, 500, 500),  # Production chunk sizes
    'zones': 'all',  # Process all available zones
    'time_range': 'full'  # Complete temporal coverage
}
```

#### Environment Configuration
```yaml
# environment.yml for Coiled cluster
name: climate-processing
channels:
  - conda-forge
  - pyviz
dependencies:
  - python=3.11
  - xarray>=2023.1.0
  - dask>=2023.1.0
  - flox>=0.7.0
  - geopandas>=0.13.0
  - rioxarray>=0.13.0
  - netcdf4>=1.6.0
  - zarr>=2.13.0
  - rasterio>=1.3.0
  - xesmf>=0.7.0
  - pandas>=2.0.0
  - numpy>=1.24.0
  - prefect>=2.0.0
```

#### Cluster Testing Script
```python
# test_cluster_operations.py
from coiled import Cluster
import time

def test_cluster_deployment():
    """Test flox operations on Coiled cluster"""
    
    cluster = Cluster(**CLUSTER_CONFIG['coiled'])
    
    with cluster.client() as client:
        print(f"Cluster ready with {len(client.workers())} workers")
        
        # Upload test functions to cluster
        client.upload_file('utils.py')
        client.upload_file('create_east_africa_virtual_dataset.py')
        
        # Test 1: Single zone on cluster
        start_time = time.time()
        future = client.submit(process_single_zone_cluster, 'zone1')
        result = future.result()
        cluster_runtime = time.time() - start_time
        
        print(f"Cluster single zone: {cluster_runtime:.2f}s")
        
        # Test 2: All zones parallel processing
        start_time = time.time()
        futures = []
        for zone in get_all_zones():
            future = client.submit(process_single_zone_cluster, zone)
            futures.append(future)
        
        results = client.gather(futures)
        total_runtime = time.time() - start_time
        
        print(f"All zones parallel: {total_runtime:.2f}s")
        
        return {
            'single_zone_runtime': cluster_runtime,
            'all_zones_runtime': total_runtime,
            'scaling_factor': len(futures),
            'efficiency': (len(futures) * cluster_runtime) / total_runtime
        }
```

## Testing Checklist

### Pre-Cluster Validation
- [ ] **Dataset Integrity**: Verify unified dataset structure and alignment
- [ ] **Shapefile Processing**: Confirm all zones load and rasterize correctly  
- [ ] **Flox Operations**: Test groupby aggregation on single zone
- [ ] **Memory Usage**: Profile memory consumption with production chunk sizes
- [ ] **Error Handling**: Test failure modes and recovery strategies

### Local Performance Baselines
- [ ] **Single Zone Timing**: Benchmark one zone across time range
- [ ] **Multi-Zone Scaling**: Test parallel zone processing locally
- [ ] **Memory Scaling**: Profile memory growth with data size
- [ ] **Chunk Optimization**: Find optimal chunk sizes for hardware

### Cluster Readiness
- [ ] **Environment Setup**: Verify all dependencies in cluster environment
- [ ] **Data Transfer**: Test dataset upload/access from cluster
- [ ] **Network Performance**: Benchmark data I/O between cluster and storage
- [ ] **Monitoring Setup**: Configure cluster monitoring and logging

## Performance Expectations

### Local Benchmarks (Reference Hardware: 8 cores, 16GB RAM)
```python
EXPECTED_LOCAL_PERFORMANCE = {
    'single_zone_3_days': '< 30 seconds',
    'single_zone_15_days': '< 2 minutes', 
    'three_zones_15_days': '< 5 minutes',
    'memory_peak': '< 4GB',
    'chunk_processing': '< 10MB per chunk'
}
```

### Cluster Scaling Targets
```python
CLUSTER_SCALING_TARGETS = {
    'all_zones_15_days': '< 5 minutes',
    'scaling_efficiency': '> 70%',  # vs linear scaling
    'memory_per_worker': '< 6GB',
    'data_throughput': '> 100MB/s per worker'
}
```

## Error Recovery Strategies

### Common Issues and Solutions
1. **Memory Overflow**: Reduce chunk sizes, increase cluster memory
2. **Zone Processing Failures**: Implement zone-by-zone error handling
3. **Network Timeouts**: Add retry logic for cluster operations
4. **Data Corruption**: Validate intermediate results at each step

### Monitoring and Debugging
```python
# Add to cluster testing
def monitor_cluster_performance(client):
    """Monitor cluster performance during operations"""
    
    # Resource utilization
    workers_info = client.workers_info()
    for worker, info in workers_info.items():
        print(f"Worker {worker}: {info['memory_percent']:.1f}% memory")
    
    # Task performance
    performance = client.performance()
    print(f"Total tasks: {performance['total']}")
    print(f"Failed tasks: {performance['failed']}")
    
    # Network metrics
    network_stats = client.network_stats()
    print(f"Data transfer: {network_stats['bytes_sent']:.1f}MB sent")
```

## Success Criteria

### Phase 1 (Local): Ready for Phase 2 when:
- Single zone processes without errors
- Memory usage is predictable and reasonable  
- Performance scales linearly with time steps
- All three variables (PET, CHIRPS, IMERG) aggregate correctly

### Phase 2 (Local Scaling): Ready for Phase 3 when:
- Multiple zones process in parallel successfully
- Memory usage remains stable across zones
- Performance scales reasonably with zone count
- Error recovery mechanisms are tested

### Phase 3 (Cluster): Production ready when:
- All zones process successfully on cluster
- Performance meets or exceeds scaling targets
- Error handling works reliably in distributed environment
- Results match local validation outputs

This systematic approach ensures reliable deployment to production Coiled clusters while maintaining data quality and performance standards.