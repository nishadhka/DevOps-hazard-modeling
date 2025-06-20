import cdsapi
import os

def get_user_input():
    """Get year and month from user input"""
    print("ECMWF Seasonal Data Downloader")
    print("==============================")
    
    while True:
        try:
            year = input("Enter year (1981-2025): ").strip()
            year_int = int(year)
            
            if 1981 <= year_int <= 2025:
                break
            else:
                print("Error: Year must be between 1981 and 2025")
        except ValueError:
            print("Error: Please enter a valid year (numbers only)")
    
    while True:
        try:
            month = input("Enter month (1-12): ").strip()
            month_int = int(month)
            
            if 1 <= month_int <= 12:
                # Format month with leading zero if needed
                month_formatted = f"{month_int:02d}"
                break
            else:
                print("Error: Month must be between 1 and 12")
        except ValueError:
            print("Error: Please enter a valid month (numbers only)")
    
    return year, month_formatted

def main():
    # Get user input
    year, month = get_user_input()
    
    # Create filename
    filename = f"ecmwf_seasonal_{year}_{month}.grib"
    
    print(f"\nDownload Details:")
    print(f"- Year: {year}")
    print(f"- Month: {month}")
    print(f"- Output file: {filename}")
    print(f"- Estimated size: ~600 MB")
    print(f"- Variables: 11 meteorological variables")
    print(f"- Lead times: 860 time steps (6-hour intervals)")
    print(f"- Area: [23°N, 21°E] to [-12°S, 53°E]")
    
    # Choose download option
    print("\nChoose an option:")
    print("1. Download immediately to your computer")
    print("2. Just initiate request (download later from CDS website)")
    print("3. Cancel")
    
    while True:
        choice = input("Enter your choice (1/2/3): ").strip()
        if choice in ['1', '2', '3']:
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")
    
    if choice == '3':
        print("Cancelled.")
        return
    
    download_now = (choice == '1')
    
    # Check if file already exists (only for immediate download)
    if download_now and os.path.exists(filename):
        print(f"\nWarning: File '{filename}' already exists!")
        overwrite = input("Do you want to overwrite it? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("Download cancelled.")
            return
    
    # CDS dataset and request configuration
    dataset = "seasonal-original-single-levels"
    request = {
        "originating_centre": "ecmwf",
        "system": "51",
        "variable": [
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
            "2m_temperature",
            "evaporation",
            "maximum_2m_temperature_in_the_last_24_hours",
            "minimum_2m_temperature_in_the_last_24_hours",
            "surface_net_solar_radiation",
            "surface_net_thermal_radiation",
            "surface_solar_radiation_downwards",
            "surface_thermal_radiation_downwards",
            "total_precipitation"
        ],
        "year": [year],
        "month": [month],
        "day": ["01"],
        "leadtime_hour": [
            "6", "12", "18", "24", "30", "36", "42", "48", "54", "60", "66", "72",
            "78", "84", "90", "96", "102", "108", "114", "120", "126", "132", "138", "144",
            "150", "156", "162", "168", "174", "180", "186", "192", "198", "204", "210", "216",
            "222", "228", "234", "240", "246", "252", "258", "264", "270", "276", "282", "288",
            "294", "300", "306", "312", "318", "324", "330", "336", "342", "348", "354", "360",
            "366", "372", "378", "384", "390", "396", "402", "408", "414", "420", "426", "432",
            "438", "444", "450", "456", "462", "468", "474", "480", "486", "492", "498", "504",
            "510", "516", "522", "528", "534", "540", "546", "552", "558", "564", "570", "576",
            "582", "588", "594", "600", "606", "612", "618", "624", "630", "636", "642", "648",
            "654", "660", "666", "672", "678", "684", "690", "696", "702", "708", "714", "720",
            "726", "732", "738", "744", "750", "756", "762", "768", "774", "780", "786", "792",
            "798", "804", "810", "816", "822", "828", "834", "840", "846", "852", "858", "864",
            "870", "876", "882", "888", "894", "900", "906", "912", "918", "924", "930", "936",
            "942", "948", "954", "960", "966", "972", "978", "984", "990", "996", "1002", "1008",
            "1014", "1020", "1026", "1032", "1038", "1044", "1050", "1056", "1062", "1068", "1074", "1080",
            "1086", "1092", "1098", "1104", "1110", "1116", "1122", "1128", "1134", "1140", "1146", "1152",
            "1158", "1164", "1170", "1176", "1182", "1188", "1194", "1200", "1206", "1212", "1218", "1224",
            "1230", "1236", "1242", "1248", "1254", "1260", "1266", "1272", "1278", "1284", "1290", "1296",
            "1302", "1308", "1314", "1320", "1326", "1332", "1338", "1344", "1350", "1356", "1362", "1368",
            "1374", "1380", "1386", "1392", "1398", "1404", "1410", "1416", "1422", "1428", "1434", "1440",
            "1446", "1452", "1458", "1464", "1470", "1476", "1482", "1488", "1494", "1500", "1506", "1512",
            "1518", "1524", "1530", "1536", "1542", "1548", "1554", "1560", "1566", "1572", "1578", "1584",
            "1590", "1596", "1602", "1608", "1614", "1620", "1626", "1632", "1638", "1644", "1650", "1656",
            "1662", "1668", "1674", "1680", "1686", "1692", "1698", "1704", "1710", "1716", "1722", "1728",
            "1734", "1740", "1746", "1752", "1758", "1764", "1770", "1776", "1782", "1788", "1794", "1800",
            "1806", "1812", "1818", "1824", "1830", "1836", "1842", "1848", "1854", "1860", "1866", "1872",
            "1878", "1884", "1890", "1896", "1902", "1908", "1914", "1920", "1926", "1932", "1938", "1944",
            "1950", "1956", "1962", "1968", "1974", "1980", "1986", "1992", "1998", "2004", "2010", "2016",
            "2022", "2028", "2034", "2040", "2046", "2052", "2058", "2064", "2070", "2076", "2082", "2088",
            "2094", "2100", "2106", "2112", "2118", "2124", "2130", "2136", "2142", "2148", "2154", "2160",
            "2166", "2172", "2178", "2184", "2190", "2196", "2202", "2208", "2214", "2220", "2226", "2232",
            "2238", "2244", "2250", "2256", "2262", "2268", "2274", "2280", "2286", "2292", "2298", "2304",
            "2310", "2316", "2322", "2328", "2334", "2340", "2346", "2352", "2358", "2364", "2370", "2376",
            "2382", "2388", "2394", "2400", "2406", "2412", "2418", "2424", "2430", "2436", "2442", "2448",
            "2454", "2460", "2466", "2472", "2478", "2484", "2490", "2496", "2502", "2508", "2514", "2520",
            "2526", "2532", "2538", "2544", "2550", "2556", "2562", "2568", "2574", "2580", "2586", "2592",
            "2598", "2604", "2610", "2616", "2622", "2628", "2634", "2640", "2646", "2652", "2658", "2664",
            "2670", "2676", "2682", "2688", "2694", "2700", "2706", "2712", "2718", "2724", "2730", "2736",
            "2742", "2748", "2754", "2760", "2766", "2772", "2778", "2784", "2790", "2796", "2802", "2808",
            "2814", "2820", "2826", "2832", "2838", "2844", "2850", "2856", "2862", "2868", "2874", "2880",
            "2886", "2892", "2898", "2904", "2910", "2916", "2922", "2928", "2934", "2940", "2946", "2952",
            "2958", "2964", "2970", "2976", "2982", "2988", "2994", "3000", "3006", "3012", "3018", "3024",
            "3030", "3036", "3042", "3048", "3054", "3060", "3066", "3072", "3078", "3084", "3090", "3096",
            "3102", "3108", "3114", "3120", "3126", "3132", "3138", "3144", "3150", "3156", "3162", "3168",
            "3174", "3180", "3186", "3192", "3198", "3204", "3210", "3216", "3222", "3228", "3234", "3240",
            "3246", "3252", "3258", "3264", "3270", "3276", "3282", "3288", "3294", "3300", "3306", "3312",
            "3318", "3324", "3330", "3336", "3342", "3348", "3354", "3360", "3366", "3372", "3378", "3384",
            "3390", "3396", "3402", "3408", "3414", "3420", "3426", "3432", "3438", "3444", "3450", "3456",
            "3462", "3468", "3474", "3480", "3486", "3492", "3498", "3504", "3510", "3516", "3522", "3528",
            "3534", "3540", "3546", "3552", "3558", "3564", "3570", "3576", "3582", "3588", "3594", "3600",
            "3606", "3612", "3618", "3624", "3630", "3636", "3642", "3648", "3654", "3660", "3666", "3672",
            "3678", "3684", "3690", "3696", "3702", "3708", "3714", "3720", "3726", "3732", "3738", "3744",
            "3750", "3756", "3762", "3768", "3774", "3780", "3786", "3792", "3798", "3804", "3810", "3816",
            "3822", "3828", "3834", "3840", "3846", "3852", "3858", "3864", "3870", "3876", "3882", "3888",
            "3894", "3900", "3906", "3912", "3918", "3924", "3930", "3936", "3942", "3948", "3954", "3960",
            "3966", "3972", "3978", "3984", "3990", "3996", "4002", "4008", "4014", "4020", "4026", "4032",
            "4038", "4044", "4050", "4056", "4062", "4068", "4074", "4080", "4086", "4092", "4098", "4104",
            "4110", "4116", "4122", "4128", "4134", "4140", "4146", "4152", "4158", "4164", "4170", "4176",
            "4182", "4188", "4194", "4200", "4206", "4212", "4218", "4224", "4230", "4236", "4242", "4248",
            "4254", "4260", "4266", "4272", "4278", "4284", "4290", "4296", "4302", "4308", "4314", "4320",
            "4326", "4332", "4338", "4344", "4350", "4356", "4362", "4368", "4374", "4380", "4386", "4392",
            "4398", "4404", "4410", "4416", "4422", "4428", "4434", "4440", "4446", "4452", "4458", "4464",
            "4470", "4476", "4482", "4488", "4494", "4500", "4506", "4512", "4518", "4524", "4530", "4536",
            "4542", "4548", "4554", "4560", "4566", "4572", "4578", "4584", "4590", "4596", "4602", "4608",
            "4614", "4620", "4626", "4632", "4638", "4644", "4650", "4656", "4662", "4668", "4674", "4680",
            "4686", "4692", "4698", "4704", "4710", "4716", "4722", "4728", "4734", "4740", "4746", "4752",
            "4758", "4764", "4770", "4776", "4782", "4788", "4794", "4800", "4806", "4812", "4818", "4824",
            "4830", "4836", "4842", "4848", "4854", "4860", "4866", "4872", "4878", "4884", "4890", "4896",
            "4902", "4908", "4914", "4920", "4926", "4932", "4938", "4944", "4950", "4956", "4962", "4968",
            "4974", "4980", "4986", "4992", "4998", "5004", "5010", "5016", "5022", "5028", "5034", "5040",
            "5046", "5052", "5058", "5064", "5070", "5076", "5082", "5088", "5094", "5100", "5106", "5112",
            "5118", "5124", "5130", "5136", "5142", "5148", "5154", "5160"
        ],
        "data_format": "grib",
        "area": [23, 21, -12, 53]
    }
    
    print(f"\nStarting {'download' if download_now else 'request submission'}...")
    
    if download_now:
        print("This may take several minutes to hours depending on CDS queue...")
    else:
        print("This will initiate the request on CDS servers...")
    
    try:
        # Initialize CDS client  
        client = cdsapi.Client()
        
        if download_now:
            # Download immediately
            client.retrieve(dataset, request, filename)
            print(f"\n✅ SUCCESS! Downloaded: {filename}")
            print(f"File size: {os.path.getsize(filename) / (1024*1024):.1f} MB")
            
        else:
            # Just initiate request
            result = client.retrieve(dataset, request)
            
            print(f"\n✅ REQUEST PROCESSED!")
            print("="*50)
            
            # Handle different result types
            request_id = None
            request_url = None
            status = None
            
            # Try to get request information (may not be available if completed immediately)
            try:
                request_id = getattr(result, 'request_id', None)
                request_url = getattr(result, 'request_url', None) 
                status = getattr(result, 'state', None)
            except:
                pass
            
            if request_id:
                print(f"Request ID: {request_id}")
                print(f"Request URL: {request_url}")
                print(f"Status: {status}")
                
                # Save request info for reference
                import json
                import time
                request_info = {
                    'request_id': request_id,
                    'request_url': request_url,
                    'year': year,
                    'month': month,
                    'filename': filename,
                    'submitted_at': time.strftime('%Y-%m-%d %H:%M:%S')
                }
                
                info_filename = f"request_info_{year}_{month}.json"
                with open(info_filename, 'w') as f:
                    json.dump(request_info, f, indent=2)
                
                print("="*50)
                print("NEXT STEPS:")
                print("1. Monitor progress at: https://cds.climate.copernicus.eu/requests")
                print("2. Your request info saved to:", info_filename)
                print("3. When ready, download from CDS website using Request ID above")
                print("4. Or use this Python code to download later:")
                print(f"   client.download('{request_id}', '{filename}')")
                
            else:
                # Request might have completed immediately
                print("Request was processed very quickly!")
                print("Check if the data file was created or check the CDS website.")
                print("Sometimes fast requests complete immediately without returning a request ID.")
                
                # Check if file was actually downloaded
                if os.path.exists(filename):
                    file_size = os.path.getsize(filename) / (1024*1024)
                    print(f"\n🎉 BONUS! File was downloaded immediately!")
                    print(f"✅ Downloaded: {filename} ({file_size:.1f} MB)")
                else:
                    print(f"\nℹ️  No file created locally. Check CDS website for your request status.")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        print("\nPossible solutions:")
        print("- Check your CDS API credentials")
        print("- Verify you've accepted CDS terms and conditions")
        print("- Try again later (CDS might be busy)")
        print("- Check your internet connection")

if __name__ == "__main__":
    main()
