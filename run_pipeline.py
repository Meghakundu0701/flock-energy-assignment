"""
End-to-End Master Pipeline Runner: REFIT Data Cleaning & Appliance Disaggregation
Author: Flock Energy Data Science Team
"""

import sys
import os
import time
import json
import tempfile

os.environ["MPLCONFIGDIR"] = os.path.join(tempfile.gettempdir(), "matplotlib_flock")
os.environ["LOKY_MAX_CPU_COUNT"] = "4"

import pandas as pd

# Import modular pipeline functions
from src.clean_raw import inspect_raw_data, run_cleaning_pipeline, plot_cleaning_comparison, plot_interval_distribution
from src.eda_washing_machine import run_washing_machine_eda
from src.disaggregation_model import train_and_evaluate_disaggregation

def main():
    print("="*80)
    print("FLOCK ENERGY: REFIT DATA CLEANING & APPLIANCE DISAGGREGATION PIPELINE")
    print("="*80)
    t_start = time.time()
    
    # Create directories
    os.makedirs('figures', exist_ok=True)
    os.makedirs('data_summary', exist_ok=True)
    
    # -------------------------------------------------------------
    # SECTION 1: Basic Inspection and Cleaning of Raw Data (House 1)
    # -------------------------------------------------------------
    print("\n[STEP 1/3] Executing Section 1: Raw Data Cleaning Pipeline (House 1)...")
    raw_p1_path = 'RAW_House1_Part1.csv'
    if not os.path.exists(raw_p1_path):
        print(f"Error: {raw_p1_path} not found.")
        sys.exit(1)
        
    raw_summary, df_raw = inspect_raw_data(raw_p1_path)
    with open('data_summary/section1_raw_inspection.json', 'w') as f:
        json.dump(raw_summary, f, indent=2, default=str)
        
    plot_interval_distribution(df_raw, output_dir='figures')
    
    df_raw_sorted, df_cleaned, is_outage = run_cleaning_pipeline(df_raw, max_interp_mins=3)
    plot_cleaning_comparison(df_raw_sorted, df_cleaned, output_dir='figures')
    print("[OK] Section 1 completed successfully.")
    
    # -------------------------------------------------------------
    # SECTION 2: Exploratory Analysis of Washing-Machine Use
    # -------------------------------------------------------------
    print("\n[STEP 2/3] Executing Section 2: Washing-Machine Exploratory Analysis...")
    summary_df, combined_cycles = run_washing_machine_eda(output_dir='figures')
    summary_df.to_csv('data_summary/section2_household_summary.csv', index=False)
    combined_cycles.to_csv('data_summary/section2_detected_cycles.csv', index=False)
    print("[OK] Section 2 completed successfully.")
    
    # -------------------------------------------------------------
    # SECTION 3: Build and Evaluate Disaggregation Model
    # -------------------------------------------------------------
    print("\n[STEP 3/3] Executing Section 3: Disaggregation Modeling...")
    # Load House 2 clean 1-minute data for model evaluation
    clean_h2_path = 'CLEAN_House2.csv'
    df_h2 = pd.read_csv(clean_h2_path, usecols=['Time', 'Unix', 'Aggregate', 'Appliance2', 'Issues'])
    df_h2_valid = df_h2.loc[df_h2['Issues'] == 0].copy()
    df_h2_valid['dt'] = pd.to_datetime(df_h2_valid['Time'])
    df_h2_1m = df_h2_valid.set_index('dt')[['Aggregate', 'Appliance2']].resample('1min').mean().interpolate(method='time', limit=3)
    
    results_df, model, eval_df = train_and_evaluate_disaggregation(
        df_h2_1m,
        target_col='Appliance2',
        house_name='House 2',
        output_dir='figures'
    )
    results_df.to_csv('data_summary/section3_model_metrics.csv', index=False)
    print("[OK] Section 3 completed successfully.")
    
    elapsed = time.time() - t_start
    print("\n" + "="*80)
    print(f"PIPELINE COMPLETE: All steps executed in {elapsed:.1f} seconds.")
    print("Generated Figures:")
    for fig in os.listdir('figures'):
        print(f" - figures/{fig}")
    print("Generated Data Summaries:")
    for f in os.listdir('data_summary'):
        print(f" - data_summary/{f}")
    print("="*80)

if __name__ == '__main__':
    main()
