#!/usr/bin/env python3
"""
Test script to validate the updated zone_wise_txt_generator.py with variable zone sizes
"""

import sys
import logging
from zone_wise_txt_generator import ZoneWiseTxtGenerator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_shapefile_loading():
    """Test shapefile loading and zone size detection"""
    logger.info("Testing shapefile loading and zone size detection")
    
    generator = ZoneWiseTxtGenerator()
    
    try:
        # Load shapefile
        shapefile_path = "geofsm-prod-all-zones-20240712.shp"
        gdf = generator.load_shapefile_data(shapefile_path)
        
        # Create zone mapping
        zone_mappings = generator.create_zone_spatial_mapping()
        
        # Print zone sizes
        logger.info("Zone sizes detected:")
        for zone, size in generator.zone_sizes.items():
            logger.info(f"  {zone}: {size} spatial units")
        
        # Test zone-specific header generation
        for zone in ['zone1', 'zone2', 'zone3', 'zone4', 'zone5', 'zone6']:
            header = generator.generate_zone_header(zone)
            logger.info(f"{zone} header length: {len(header)}")
        
        logger.info("✅ Shapefile loading test completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Shapefile loading test failed: {e}")
        return False

def test_time_conversion():
    """Test gtime to Julian date conversion"""
    logger.info("Testing gtime to Julian date conversion")
    
    generator = ZoneWiseTxtGenerator()
    
    test_cases = [
        "20250731T08",  # July 31, 2025, 08:00 (correct format with T)
        "20250101T00",  # January 1, 2025, 00:00
        "20251231T23",  # December 31, 2025, 23:00
    ]
    
    try:
        for gtime_str in test_cases:
            julian_date = generator.convert_gtime_to_julian(gtime_str)
            logger.info(f"  {gtime_str} -> {julian_date}")
        
        logger.info("✅ Time conversion test completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Time conversion test failed: {e}")
        return False

def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("TESTING ZONE GENERATOR V2 WITH VARIABLE ZONE SIZES")
    logger.info("=" * 60)
    
    tests = [
        ("Shapefile Loading", test_shapefile_loading),
        ("Time Conversion", test_time_conversion),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\nRunning {test_name} test...")
        result = test_func()
        results.append((test_name, result))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\nOverall: {passed}/{len(tests)} tests passed")
    
    if passed == len(tests):
        logger.info("🎉 All tests passed! Zone generator v2 is working correctly.")
        return 0
    else:
        logger.error("⚠️  Some tests failed. Please check the implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())