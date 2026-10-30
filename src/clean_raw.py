"""
Section 1: Basic Inspection and Cleaning of Raw Data (House 1)
Author: Flock Energy Data Science Team
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def inspect_raw_data(filepath):
    """
    Inspects raw REFIT CSV file for timestamp validity, ordering,
    duplicates, irregular intervals, missing readings, and extreme values.
    """
    print(f"--- Inspecting Raw Data: {os.path.basename(filepath)} ---")
    df = pd.read_csv(filepath)
    n_rows = len(df)
    
    # 1. Timestamp Parsing & Duplicate Checks
    parsed_dt = pd.to_datetime(df['Time'], errors='coerce')
    invalid_dates = parsed_dt.isnull().sum()
    dup_time_str = df['Time'].duplicated().sum()
    dup_unix = df['Unix'].duplicated().sum()
    
    # 2. Ordering & Sampling Intervals
    diffs = df['Unix'].diff()
    non_positive_steps = (diffs <= 0).sum()
    interval_stats = {
        'min_sec': float(diffs.min()),
        'p01_sec': float(diffs.quantile(0.01)),
        'p05_sec': float(diffs.quantile(0.05)),
        'median_sec': float(diffs.median()),
        'p95_sec': float(diffs.quantile(0.95)),
        'p99_sec': float(diffs.quantile(0.99)),
        'max_sec': float(diffs.max())
    }
    
    # 3. Missing Readings & Impossible Values
    null_counts = {k: int(v) for k, v in df.isnull().sum().to_dict().items()}
    appliance_cols = [c for c in df.columns if c.startswith('Appliance')]
    
    extreme_spikes = {}
    for col in appliance_cols:
        extreme_spikes[col] = int((df[col] > 4000).sum())
    agg_extreme = int((df['Aggregate'] > 25000).sum())
    negative_counts = {c: int((df[c] < 0).sum()) for c in ['Aggregate'] + appliance_cols}
    
    summary = {
        'file': os.path.basename(filepath),
        'total_rows': n_rows,
        'invalid_dates': int(invalid_dates),
        'dup_time_strings': int(dup_time_str),
        'dup_unix_timestamps': int(dup_unix),
        'non_positive_steps': int(non_positive_steps),
        'interval_stats': interval_stats,
        'null_counts': null_counts,
        'extreme_appliance_spikes_gt_4kw': extreme_spikes,
        'agg_extreme_gt_25kw': int(agg_extreme),
        'negative_counts': negative_counts
    }
    
    print(f"Rows: {n_rows:,} | Duplicate Unix timestamps: {dup_unix:,} ({dup_unix/n_rows*100:.2f}%)")
    print(f"Non-positive dt steps (backward/duplicate): {non_positive_steps:,}")
    print(f"Sampling interval median: {interval_stats['median_sec']}s, max: {interval_stats['max_sec']/86400:.2f} days")
    print(f"Appliance spikes > 4 kW (sensor overflows): {sum(extreme_spikes.values()):,}")
    return summary, df

def run_cleaning_pipeline(df_raw, max_interp_mins=3):
    """
    Documented cleaning pipeline:
    1. Chronological sort by Unix epoch.
    2. De-duplication: Group by Unix timestamp and take column-wise mean.
    3. Extreme value filtering: Active power < 0 or > 4 kW (appliances) / > 25 kW (aggregate) -> NaN.
    4. Resample onto a uniform 1-minute grid.
    5. Gap handling: Short gaps (<= 3 mins) linearly interpolated.
       Longer outages (> 3 mins) flagged as outages (kept NaN/masked).
    """
    print("\n--- Running Raw Data Cleaning Pipeline ---")
    cols = ['Aggregate'] + [f'Appliance{i}' for i in range(1, 10)]
    
    # Step 1: Sort by Unix
    df_sorted = df_raw.sort_values('Unix').reset_index(drop=True)
    
    # Step 2: Extreme value filtering (before resampling to avoid polluting averages)
    for c in cols:
        if c == 'Aggregate':
            df_sorted.loc[(df_sorted[c] < 0) | (df_sorted[c] > 25000), c] = np.nan
        else:
            df_sorted.loc[(df_sorted[c] < 0) | (df_sorted[c] > 4000), c] = np.nan
            
    # Step 3: De-duplicate by timestamp using stated rule (mean of concurrent updates)
    df_dedup = df_sorted.groupby('Unix')[cols].mean()
    
    # Step 4: Resample onto 1-minute grid
    df_dedup.index = pd.to_datetime(df_dedup.index, unit='s', utc=True)
    df_1m = df_dedup.resample('1min').mean()
    
    # Step 5: Short gap interpolation vs Outage flagging
    # Flag original missing intervals before short-gap filling
    was_nan = df_1m.isnull()
    
    # Interpolate short missing gaps up to max_interp_mins
    df_cleaned = df_1m.interpolate(method='time', limit=max_interp_mins, limit_area='inside')
    
    # Outage mask: remaining NaNs represent outages > max_interp_mins
    is_outage = df_cleaned.isnull()
    
    print(f"Uniform 1-minute periods: {len(df_cleaned):,}")
    print(f"Missing 1-minute buckets before short interpolation: {was_nan['Aggregate'].sum():,}")
    print(f"Short gaps interpolated (<= {max_interp_mins} mins): {(was_nan['Aggregate'] & ~is_outage['Aggregate']).sum():,}")
    print(f"Flagged outage buckets (> {max_interp_mins} mins): {is_outage['Aggregate'].sum():,}")
    
    return df_sorted, df_cleaned, is_outage

def plot_cleaning_comparison(df_raw_sorted, df_cleaned, output_dir='figures'):
    """
    Plots aggregate power and two appliance channels (Appliance1: Fridge,
    Appliance5: Washing Machine) before and after cleaning on a representative window.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Select a representative 48-hour window containing active washing machine usage and typical fridge cycling
    # Window: 2013-10-12 00:00:00 to 2013-10-14 00:00:00 UTC
    start_ts = pd.to_datetime('2013-10-12 00:00:00', utc=True)
    end_ts = pd.to_datetime('2013-10-14 00:00:00', utc=True)
    
    raw_dt = pd.to_datetime(df_raw_sorted['Unix'], unit='s', utc=True)
    mask_raw = (raw_dt >= start_ts) & (raw_dt <= end_ts)
    sub_raw = df_raw_sorted.loc[mask_raw].copy()
    sub_raw['dt'] = raw_dt[mask_raw]
    
    mask_clean = (df_cleaned.index >= start_ts) & (df_cleaned.index <= end_ts)
    sub_clean = df_cleaned.loc[mask_clean].copy()
    
    fig, axes = plt.subplots(3, 2, figsize=(16, 11), sharex=True)
    plt.subplots_adjust(hspace=0.25, wspace=0.15)
    
    # Channel 1: Aggregate Power
    axes[0, 0].plot(sub_raw['dt'], sub_raw['Aggregate'], color='#e74c3c', lw=0.8, alpha=0.8)
    axes[0, 0].set_title('Raw Aggregate Power (Irregular ~8s, Spikes & Duplicates)', fontsize=12, fontweight='bold')
    axes[0, 0].set_ylabel('Power (Watts)')
    axes[0, 0].grid(True, linestyle=':', alpha=0.6)
    
    axes[0, 1].plot(sub_clean.index, sub_clean['Aggregate'], color='#2980b9', lw=1.2)
    axes[0, 1].set_title('Cleaned Aggregate Power (Resampled 1-min Grid, Gaps Handled)', fontsize=12, fontweight='bold')
    axes[0, 1].set_ylabel('Power (Watts)')
    axes[0, 1].grid(True, linestyle=':', alpha=0.6)
    
    # Channel 2: Appliance 1 (Fridge)
    axes[1, 0].plot(sub_raw['dt'], sub_raw['Appliance1'], color='#e67e22', lw=0.8, alpha=0.8)
    axes[1, 0].set_title('Raw Appliance 1: Fridge (Raw Sensor Stream)', fontsize=12, fontweight='bold')
    axes[1, 0].set_ylabel('Power (Watts)')
    axes[1, 0].grid(True, linestyle=':', alpha=0.6)
    
    axes[1, 1].plot(sub_clean.index, sub_clean['Appliance1'], color='#27ae60', lw=1.2)
    axes[1, 1].set_title('Cleaned Appliance 1: Fridge (1-min Resampled, De-noised)', fontsize=12, fontweight='bold')
    axes[1, 1].set_ylabel('Power (Watts)')
    axes[1, 1].grid(True, linestyle=':', alpha=0.6)
    
    # Channel 3: Appliance 5 (Washing Machine)
    axes[2, 0].plot(sub_raw['dt'], sub_raw['Appliance5'], color='#8e44ad', lw=0.8, alpha=0.8)
    axes[2, 0].set_title('Raw Appliance 5: Washing Machine (Raw Sensor Stream)', fontsize=12, fontweight='bold')
    axes[2, 0].set_ylabel('Power (Watts)')
    axes[2, 0].set_xlabel('Timestamp (UTC)')
    axes[2, 0].grid(True, linestyle=':', alpha=0.6)
    
    axes[2, 1].plot(sub_clean.index, sub_clean['Appliance5'], color='#d35400', lw=1.2)
    axes[2, 1].set_title('Cleaned Appliance 5: Washing Machine (1-min Grid, Signature Preserved)', fontsize=12, fontweight='bold')
    axes[2, 1].set_ylabel('Power (Watts)')
    axes[2, 1].set_xlabel('Timestamp (UTC)')
    axes[2, 1].grid(True, linestyle=':', alpha=0.6)
    
    out_path = os.path.join(output_dir, 's1_house1_cleaning_comparison.png')
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved cleaning comparison plot: {out_path}")

def plot_interval_distribution(df_raw, output_dir='figures'):
    """
    Plots the distribution of raw sampling intervals highlighting irregularities.
    """
    os.makedirs(output_dir, exist_ok=True)
    diffs = df_raw['Unix'].diff().dropna()
    # Filter to 0 to 60s for clear visual distribution
    sub_diffs = diffs[(diffs >= 0) & (diffs <= 60)]
    
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(sub_diffs, bins=60, color='#3498db', edgecolor='black', alpha=0.75)
    ax.axvline(sub_diffs.median(), color='#e74c3c', linestyle='--', lw=2, label=f'Median: {sub_diffs.median():.1f}s')
    ax.set_title('House 1 Raw Sampling Interval Distribution (0 - 60s)', fontsize=13, fontweight='bold')
    ax.set_xlabel('Interval between consecutive readings (seconds)', fontsize=11)
    ax.set_ylabel('Frequency (Readings)', fontsize=11)
    ax.legend(fontsize=11)
    ax.grid(True, linestyle=':', alpha=0.6)
    
    out_path = os.path.join(output_dir, 's1_house1_interval_distribution.png')
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved interval distribution plot: {out_path}")
