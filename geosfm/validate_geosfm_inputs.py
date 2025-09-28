#!/usr/bin/env python3
"""
GeoSFM Input Validation and Remediation Script

This script provides comprehensive validation and remediation tools for GeoSFM
hydrological model input files. It identifies issues between working (ic_input)
and failing (cc_input) files and provides automated fixes.

Features:
1. Comprehensive file structure and content validation
2. Statistical analysis and data quality assessment
3. Automated remediation suggestions and fixes
4. Historical data gap analysis
5. Model-ready format validation
6. Report generation for operational teams

Usage:
    python validate_geosfm_inputs.py --validate             # Basic validation
    python validate_geosfm_inputs.py --validate --detailed  # Detailed analysis
    python validate_geosfm_inputs.py --remediate            # Auto-fix issues
    python validate_geosfm_inputs.py --analyze-csv         # CSV source analysis
"""

import os
import sys
import argparse
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import shutil
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
import pandas as pd
import filecmp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GeoSFMInputValidator:
    """Comprehensive validator for GeoSFM input files"""

    def __init__(self,
                 ic_input_dir="test_input/ic_input",
                 cc_input_dir="test_input/cc_input",
                 source_csv="test_input/flox_results_lean_long_table_v3_20250923.csv"):

        self.ic_input_dir = Path(ic_input_dir)
        self.cc_input_dir = Path(cc_input_dir)
        self.source_csv = Path(source_csv)

        self.zones = ["zone1", "zone2", "zone3", "zone4", "zone5", "zone6"]
        self.meteo_files = ["evap.txt", "rain.txt"]

        self.validation_results = {}
        self.remediation_plan = {}

    def validate_directory_structure(self) -> Dict[str, bool]:
        """Validate that required directories and files exist"""
        logger.info("Validating directory structure...")

        structure_status = {
            "ic_input_exists": self.ic_input_dir.exists(),
            "cc_input_exists": self.cc_input_dir.exists(),
            "source_csv_exists": self.source_csv.exists(),
            "zone_directories": {},
            "zone_files": {}
        }

        # Check zone directories
        for zone in self.zones:
            ic_zone = self.ic_input_dir / zone
            cc_zone = self.cc_input_dir / zone

            structure_status["zone_directories"][zone] = {
                "ic": ic_zone.exists(),
                "cc": cc_zone.exists()
            }

            # Check meteo files in each zone
            structure_status["zone_files"][zone] = {}
            for meteo_file in self.meteo_files:
                ic_file = ic_zone / meteo_file
                cc_file = cc_zone / meteo_file

                structure_status["zone_files"][zone][meteo_file] = {
                    "ic_exists": ic_file.exists(),
                    "cc_exists": cc_file.exists(),
                    "ic_size": ic_file.stat().st_size if ic_file.exists() else 0,
                    "cc_size": cc_file.stat().st_size if cc_file.exists() else 0
                }

        return structure_status

    def analyze_file_content(self, filepath: Path) -> Dict[str, Any]:
        """Comprehensive analysis of a single file"""
        if not filepath.exists():
            return {"error": "File not found"}

        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()

            if not lines:
                return {"error": "Empty file"}

            # Basic stats
            total_lines = len(lines)
            non_empty_lines = sum(1 for line in lines if line.strip())

            # Format detection
            first_line = lines[0].strip()
            if not first_line:
                return {"error": "Empty first line"}

            # Detect separator
            if ',' in first_line:
                separator = ','
                parts = first_line.split(',')
            elif '\t' in first_line:
                separator = 'tab'
                parts = first_line.split('\t')
            else:
                separator = 'space'
                parts = first_line.split()

            # Check if header exists (non-numeric first element)
            has_header = False
            try:
                float(parts[0])
            except (ValueError, IndexError):
                has_header = True

            # Extract numeric data for analysis
            numeric_data = []
            start_idx = 1 if has_header else 0

            for line_idx in range(start_idx, min(start_idx + 1000, len(lines))):
                line = lines[line_idx].strip()
                if not line:
                    continue

                if separator == ',':
                    line_parts = line.split(',')
                elif separator == 'tab':
                    line_parts = line.split('\t')
                else:
                    line_parts = line.split()

                # Extract numeric values (skip first column which is typically timestamp)
                for part in line_parts[1:]:
                    try:
                        value = float(part.strip())
                        numeric_data.append(value)
                    except ValueError:
                        continue

            # Calculate statistics
            stats = {}
            if numeric_data:
                stats = {
                    "count": len(numeric_data),
                    "mean": np.mean(numeric_data),
                    "std": np.std(numeric_data),
                    "min": np.min(numeric_data),
                    "max": np.max(numeric_data),
                    "median": np.median(numeric_data),
                    "zeros": sum(1 for x in numeric_data if x == 0),
                    "negatives": sum(1 for x in numeric_data if x < 0)
                }

            # Sample first/last few lines for inspection
            sample_first = [line.strip() for line in lines[:3] if line.strip()]
            sample_last = [line.strip() for line in lines[-3:] if line.strip()]

            return {
                "file_size": filepath.stat().st_size,
                "total_lines": total_lines,
                "non_empty_lines": non_empty_lines,
                "empty_lines": total_lines - non_empty_lines,
                "has_header": has_header,
                "separator": separator,
                "columns": len(parts),
                "statistics": stats,
                "sample_first": sample_first,
                "sample_last": sample_last,
                "first_line": first_line
            }

        except Exception as e:
            return {"error": str(e)}

    def validate_file_pairs(self, detailed=False) -> Dict[str, Any]:
        """Compare IC and CC file pairs for each zone"""
        logger.info("Validating file pairs...")

        comparison_results = {}

        for zone in self.zones:
            zone_results = {}

            for meteo_file in self.meteo_files:
                ic_file = self.ic_input_dir / zone / meteo_file
                cc_file = self.cc_input_dir / zone / meteo_file

                file_key = f"{zone}_{meteo_file}"

                # Check file existence
                if not ic_file.exists() or not cc_file.exists():
                    zone_results[file_key] = {
                        "status": "missing",
                        "ic_exists": ic_file.exists(),
                        "cc_exists": cc_file.exists()
                    }
                    continue

                # Quick binary comparison
                files_identical = filecmp.cmp(ic_file, cc_file, shallow=False)

                if files_identical:
                    zone_results[file_key] = {"status": "identical"}
                    continue

                # Detailed analysis
                ic_analysis = self.analyze_file_content(ic_file)
                cc_analysis = self.analyze_file_content(cc_file)

                # Identify differences
                differences = []
                issues = []

                if 'error' not in ic_analysis and 'error' not in cc_analysis:
                    # Size difference
                    size_diff = cc_analysis['file_size'] - ic_analysis['file_size']
                    if abs(size_diff) > 0:
                        differences.append(f"File size: {size_diff:+,} bytes")

                    # Line count difference
                    line_diff = cc_analysis['total_lines'] - ic_analysis['total_lines']
                    if abs(line_diff) > 0:
                        differences.append(f"Line count: {line_diff:+} lines")
                        if abs(line_diff) > 100:  # Significant line difference
                            issues.append("major_line_difference")

                    # Column difference
                    col_diff = cc_analysis['columns'] - ic_analysis['columns']
                    if abs(col_diff) > 0:
                        differences.append(f"Column count: {col_diff:+} columns")
                        issues.append("column_mismatch")

                    # Format differences
                    if ic_analysis['separator'] != cc_analysis['separator']:
                        differences.append(f"Separator: IC={ic_analysis['separator']}, CC={cc_analysis['separator']}")
                        issues.append("format_mismatch")

                    if ic_analysis['has_header'] != cc_analysis['has_header']:
                        differences.append(f"Header: IC={ic_analysis['has_header']}, CC={cc_analysis['has_header']}")
                        issues.append("header_mismatch")

                    # Statistical differences
                    if ic_analysis.get('statistics') and cc_analysis.get('statistics'):
                        ic_stats = ic_analysis['statistics']
                        cc_stats = cc_analysis['statistics']

                        # Data count difference
                        count_diff = cc_stats['count'] - ic_stats['count']
                        if abs(count_diff) > 0:
                            differences.append(f"Data points: {count_diff:+} values")

                        # Mean difference (relative)
                        if ic_stats['mean'] != 0:
                            mean_diff_pct = ((cc_stats['mean'] - ic_stats['mean']) / ic_stats['mean']) * 100
                            if abs(mean_diff_pct) > 5:  # More than 5% difference
                                differences.append(f"Mean difference: {mean_diff_pct:+.2f}%")
                                issues.append("statistical_difference")

                        # Range difference
                        ic_range = ic_stats['max'] - ic_stats['min']
                        cc_range = cc_stats['max'] - cc_stats['min']
                        range_diff = cc_range - ic_range
                        if abs(range_diff) > 0.1 and ic_range > 0:
                            range_diff_pct = (range_diff / ic_range) * 100
                            differences.append(f"Range difference: {range_diff_pct:+.2f}%")

                zone_results[file_key] = {
                    "status": "different",
                    "ic_analysis": ic_analysis,
                    "cc_analysis": cc_analysis,
                    "differences": differences,
                    "issues": issues,
                    "severity": "high" if issues else "low"
                }

            comparison_results[zone] = zone_results

        return comparison_results

    def analyze_source_csv(self) -> Dict[str, Any]:
        """Analyze the source CSV file structure and content"""
        logger.info("Analyzing source CSV file...")

        if not self.source_csv.exists():
            return {"error": "Source CSV file not found"}

        try:
            # Read CSV with pandas
            df = pd.read_csv(self.source_csv)

            # Basic info
            csv_info = {
                "file_size": self.source_csv.stat().st_size,
                "total_records": len(df),
                "columns": list(df.columns),
                "memory_usage": df.memory_usage(deep=True).sum()
            }

            # Date range analysis
            if 'gtime' in df.columns:
                df['gtime_parsed'] = pd.to_datetime(df['gtime'], format='%Y%m%dT%H', errors='coerce')

                csv_info["date_range"] = {
                    "start": df['gtime_parsed'].min(),
                    "end": df['gtime_parsed'].max(),
                    "unique_dates": df['gtime_parsed'].nunique(),
                    "missing_dates": df['gtime_parsed'].isna().sum()
                }

            # Variable analysis
            if 'variable' in df.columns:
                variable_counts = df['variable'].value_counts().to_dict()
                csv_info["variables"] = {
                    "unique_variables": df['variable'].nunique(),
                    "variable_counts": variable_counts,
                    "variable_mapping": {
                        "1": "IMERG (rainfall)",
                        "2": "PET (evapotranspiration)",
                        "3": "CHIRPS (rainfall)"
                    }
                }

            # Zone analysis
            if 'zones_id' in df.columns:
                csv_info["zones"] = {
                    "unique_zones": df['zones_id'].nunique(),
                    "zone_range": {
                        "min": df['zones_id'].min(),
                        "max": df['zones_id'].max()
                    },
                    "zones_per_variable": df.groupby('variable')['zones_id'].nunique().to_dict()
                }

            # Data quality analysis
            if 'mean_value' in df.columns:
                csv_info["data_quality"] = {
                    "null_values": df['mean_value'].isna().sum(),
                    "zero_values": (df['mean_value'] == 0).sum(),
                    "negative_values": (df['mean_value'] < 0).sum(),
                    "statistics": df['mean_value'].describe().to_dict()
                }

            return csv_info

        except Exception as e:
            return {"error": str(e)}

    def generate_remediation_plan(self, validation_results: Dict[str, Any]) -> Dict[str, List[str]]:
        """Generate automated remediation recommendations"""
        logger.info("Generating remediation plan...")

        remediation = {
            "critical": [],
            "important": [],
            "recommended": [],
            "commands": []
        }

        # Analyze validation results for issues
        for zone, zone_results in validation_results.items():
            for file_key, result in zone_results.items():
                if result.get("status") == "missing":
                    remediation["critical"].append(f"Copy missing file: {file_key}")
                    remediation["commands"].append(f"cp {self.ic_input_dir}/{file_key.replace('_', '/')} {self.cc_input_dir}/{file_key.replace('_', '/')}")

                elif result.get("status") == "different":
                    issues = result.get("issues", [])
                    differences = result.get("differences", [])

                    if "major_line_difference" in issues:
                        remediation["critical"].append(f"Fix major data gap in {file_key}")

                    if "header_mismatch" in issues:
                        remediation["important"].append(f"Standardize header format in {file_key}")

                    if "format_mismatch" in issues:
                        remediation["important"].append(f"Fix file format inconsistency in {file_key}")

                    if "statistical_difference" in issues:
                        remediation["recommended"].append(f"Validate data quality in {file_key}")

        # Add general recommendations
        remediation["recommended"].extend([
            "Run full comparison validation before model execution",
            "Implement automated data quality checks",
            "Create backup of working ic_input files",
            "Test model with corrected cc_input files"
        ])

        return remediation

    def generate_report(self, validation_results: Dict[str, Any],
                       csv_analysis: Dict[str, Any],
                       remediation_plan: Dict[str, List[str]],
                       save_report: bool = True) -> str:
        """Generate comprehensive validation report"""

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report = []

        report.append("="*80)
        report.append("GeoSFM INPUT VALIDATION REPORT")
        report.append("="*80)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # Summary statistics
        total_files = 0
        identical_files = 0
        different_files = 0
        missing_files = 0

        for zone_results in validation_results.values():
            for result in zone_results.values():
                total_files += 1
                status = result.get("status", "unknown")
                if status == "identical":
                    identical_files += 1
                elif status == "different":
                    different_files += 1
                elif status == "missing":
                    missing_files += 1

        report.append("SUMMARY")
        report.append("-" * 40)
        report.append(f"Total files analyzed: {total_files}")
        report.append(f"✅ Identical files: {identical_files}")
        report.append(f"⚠️  Different files: {different_files}")
        report.append(f"❌ Missing files: {missing_files}")
        report.append("")

        # CSV Analysis Summary
        if csv_analysis and 'error' not in csv_analysis:
            report.append("SOURCE CSV ANALYSIS")
            report.append("-" * 40)
            report.append(f"Records: {csv_analysis.get('total_records', 'N/A'):,}")
            report.append(f"File size: {csv_analysis.get('file_size', 0):,} bytes")

            if 'date_range' in csv_analysis:
                date_info = csv_analysis['date_range']
                report.append(f"Date range: {date_info['start']} to {date_info['end']}")
                report.append(f"Unique dates: {date_info['unique_dates']}")

            if 'variables' in csv_analysis:
                var_info = csv_analysis['variables']
                report.append(f"Variables: {var_info['unique_variables']} types")
                for var_id, count in var_info['variable_counts'].items():
                    var_name = var_info['variable_mapping'].get(str(var_id), f"Variable {var_id}")
                    report.append(f"  - {var_name}: {count:,} records")

            report.append("")

        # Detailed file comparison
        report.append("DETAILED FILE ANALYSIS")
        report.append("-" * 40)

        for zone, zone_results in validation_results.items():
            report.append(f"\n{zone.upper()}:")

            for file_key, result in zone_results.items():
                meteo_file = file_key.split('_', 1)[1]
                status = result.get("status", "unknown")

                if status == "identical":
                    report.append(f"  ✅ {meteo_file}: Identical")
                elif status == "missing":
                    report.append(f"  ❌ {meteo_file}: Missing files")
                elif status == "different":
                    differences = result.get("differences", [])
                    severity = result.get("severity", "low")
                    icon = "🔥" if severity == "high" else "⚠️"
                    report.append(f"  {icon} {meteo_file}: {len(differences)} differences")

                    for diff in differences[:3]:  # Show first 3 differences
                        report.append(f"    - {diff}")

                    if len(differences) > 3:
                        report.append(f"    ... and {len(differences) - 3} more")

        # Remediation plan
        report.append("\n" + "="*80)
        report.append("REMEDIATION PLAN")
        report.append("="*80)

        if remediation_plan["critical"]:
            report.append("\n🔥 CRITICAL ISSUES (Must Fix):")
            for item in remediation_plan["critical"]:
                report.append(f"  - {item}")

        if remediation_plan["important"]:
            report.append("\n⚠️  IMPORTANT ISSUES (Should Fix):")
            for item in remediation_plan["important"]:
                report.append(f"  - {item}")

        if remediation_plan["recommended"]:
            report.append("\n📋 RECOMMENDED ACTIONS:")
            for item in remediation_plan["recommended"]:
                report.append(f"  - {item}")

        if remediation_plan["commands"]:
            report.append("\n🔧 SUGGESTED COMMANDS:")
            for cmd in remediation_plan["commands"][:5]:  # Show first 5 commands
                report.append(f"  {cmd}")

        report.append("\n" + "="*80)
        report.append("END OF REPORT")
        report.append("="*80)

        report_text = "\n".join(report)

        if save_report:
            report_file = f"geosfm_validation_report_{timestamp}.txt"
            with open(report_file, 'w') as f:
                f.write(report_text)
            logger.info(f"Report saved to: {report_file}")

        return report_text

    def run_validation(self, detailed=False, save_report=True) -> Dict[str, Any]:
        """Run comprehensive validation"""
        logger.info("Starting GeoSFM input validation...")

        # Validate structure
        structure = self.validate_directory_structure()

        # Validate file pairs
        file_validation = self.validate_file_pairs(detailed=detailed)

        # Analyze CSV
        csv_analysis = self.analyze_source_csv()

        # Generate remediation plan
        remediation = self.generate_remediation_plan(file_validation)

        # Generate report
        report = self.generate_report(
            file_validation,
            csv_analysis,
            remediation,
            save_report=save_report
        )

        results = {
            "structure": structure,
            "file_validation": file_validation,
            "csv_analysis": csv_analysis,
            "remediation": remediation,
            "report": report
        }

        return results

def main():
    parser = argparse.ArgumentParser(description='Validate GeoSFM input files')
    parser.add_argument('--validate', action='store_true',
                       help='Run validation analysis')
    parser.add_argument('--detailed', action='store_true',
                       help='Include detailed file content analysis')
    parser.add_argument('--analyze-csv', action='store_true',
                       help='Analyze source CSV file only')
    parser.add_argument('--save-report', action='store_true', default=True,
                       help='Save validation report to file')
    parser.add_argument('--ic-input', default='test_input/ic_input',
                       help='Path to IC input directory')
    parser.add_argument('--cc-input', default='test_input/cc_input',
                       help='Path to CC input directory')
    parser.add_argument('--source-csv',
                       default='test_input/flox_results_lean_long_table_v3_20250923.csv',
                       help='Path to source CSV file')

    args = parser.parse_args()

    # Initialize validator
    validator = GeoSFMInputValidator(
        ic_input_dir=args.ic_input,
        cc_input_dir=args.cc_input,
        source_csv=args.source_csv
    )

    try:
        if args.analyze_csv:
            # Just analyze CSV
            csv_analysis = validator.analyze_source_csv()
            print("\nSOURCE CSV ANALYSIS")
            print("="*50)
            print(json.dumps(csv_analysis, indent=2, default=str))

        elif args.validate:
            # Full validation
            results = validator.run_validation(
                detailed=args.detailed,
                save_report=args.save_report
            )

            # Print report to console
            print(results["report"])

            # Print summary
            remediation = results["remediation"]
            critical_count = len(remediation["critical"])
            important_count = len(remediation["important"])

            if critical_count > 0:
                logger.error(f"❌ {critical_count} critical issues found!")
                sys.exit(1)
            elif important_count > 0:
                logger.warning(f"⚠️  {important_count} important issues found")
                sys.exit(2)
            else:
                logger.info("✅ No critical issues found")
                sys.exit(0)
        else:
            parser.print_help()

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        sys.exit(3)

if __name__ == "__main__":
    main()