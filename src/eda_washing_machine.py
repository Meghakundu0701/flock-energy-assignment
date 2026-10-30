"""
Section 2: Exploratory Analysis of Washing-Machine Use across REFIT Households
Author: Flock Energy Data Science Team
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

HOUSE_CONFIG = {
    'House 1': {
        'file': 'CLEAN_House1.csv',
        'wm_col': 'Appliance5',
        'model': 'Beko WMC6140',
        'occupants': 2,
        'type': 'Detached, 4 bed'
    },
    'House 2': {
        'file': 'CLEAN_House2.csv',
        'wm_col': 'Appliance2',
        'model': 'LG F1289TD',
        'occupants': 4,
        'type': 'Semi-detached, 3 bed'
    },
    'House 3': {
        'file': 'CLEAN_House3.csv',
        'wm_col': 'Appliance6',
        'model': 'Unknown',
        'occupants': 2,
        'type': 'Detached, 3 bed'
    },
    'House 5': {
        'file': 'CLEAN_House5.csv',
        'wm_col': 'Appliance3',
        'model': 'AEG L99695HWD',
        'occupants': 4,
        'type': 'Mid-terrace, 4 bed'
    },
    'House 16': {
        'file': 'CLEAN_House16.csv',
        'wm_col': 'Appliance5',
        'model': 'Bosch WAB24262GB/01',
        'occupants': 6,
        'type': 'Detached, 5 bed'
    }
}

def detect_cycles(series_1m, p_thresh=20.0, max_gap_mins=3, min_duration_mins=15, min_peak_power=500.0):
    """
    Identifies active washing machine cycles using a physics-grounded threshold rule:
    1. Active reading: Power >= p_thresh (20 W) to separate from standby (0-10 W).
    2. Inactive pause bridging: Gaps between active readings <= max_gap_mins (3 mins)
       are bridged into the same cycle (accounting for drum rest / soak pauses).
    3. Minimum duration: Total cycle length >= min_duration_mins (15 mins).
    4. Minimum peak power: Peak power >= min_peak_power (500 W) to confirm water
       heating or high-speed spin execution rather than lid opens or door sensor triggers.
    """
    active_indices = np.where(series_1m.values >= p_thresh)[0]
    if len(active_indices) == 0:
        return pd.DataFrame()
    
    splits = np.where(np.diff(active_indices) > (max_gap_mins + 1))[0]
    
    cycles = []
    start_pos = 0
    for split in np.append(splits, len(active_indices) - 1):
        idx_run = active_indices[start_pos : split + 1]
        start_pos = split + 1
        
        idx_start = idx_run[0]
        idx_end = idx_run[-1]
        
        duration_mins = idx_end - idx_start + 1
        if duration_mins < min_duration_mins:
            continue
            
        cycle_power = series_1m.iloc[idx_start : idx_end + 1]
        peak_w = float(cycle_power.max())
        if peak_w < min_peak_power:
            continue
            
        energy_kwh = float(cycle_power.sum()) / 60000.0
        start_time = series_1m.index[idx_start]
        end_time = series_1m.index[idx_end]
        
        cycles.append({
            'start_idx': idx_start,
            'end_idx': idx_end,
            'start_time': start_time,
            'end_time': end_time,
            'duration_mins': duration_mins,
            'peak_power_w': peak_w,
            'mean_power_w': float(cycle_power.mean()),
            'energy_kwh': energy_kwh,
            'start_hour': start_time.hour,
            'day_of_week': start_time.day_name()
        })
        
    return pd.DataFrame(cycles)

def load_and_resample_household(house_name, config):
    """
    Loads official cleaned household CSV, converts to 1-minute grid,
    interpolates short gaps (<= 3 mins), and extracts data quality metrics.
    """
    fname = config['file']
    col = config['wm_col']
    print(f"Loading {house_name} from {fname}...")
    df = pd.read_csv(fname, usecols=['Time', 'Unix', 'Aggregate', col, 'Issues'])
    df['dt'] = pd.to_datetime(df['Time'])
    
    # Exclude invalid meter readings flagged with Issues==1
    df_valid = df.loc[df['Issues'] == 0].copy()
    
    # 1-minute resample
    df_1m = df_valid.set_index('dt')[['Aggregate', col]].resample('1min').mean()
    
    # Missingness before gap filling
    n_total_mins = len(df_1m)
    n_missing_mins = df_1m[col].isnull().sum()
    
    # Bridge short gaps <= 3 mins
    df_1m_clean = df_1m.interpolate(method='time', limit=3)
    
    # Zero/off time and standby time
    wm_clean = df_1m_clean[col].dropna()
    zero_pct = float((wm_clean <= 0).mean() * 100)
    standby_pct = float(((wm_clean > 0) & (wm_clean < 20)).mean() * 100)
    active_pct = float((wm_clean >= 20).mean() * 100)
    
    # Cycle detection
    cycles_df = detect_cycles(df_1m_clean[col].fillna(0))
    cycles_df['house'] = house_name
    
    days_monitored = (df_1m.index.max() - df_1m.index.min()).total_seconds() / 86400.0
    weeks_monitored = days_monitored / 7.0
    cycles_per_week = len(cycles_df) / (weeks_monitored if weeks_monitored > 0 else 1.0)
    
    metrics = {
        'house': house_name,
        'model': config['model'],
        'occupants': config['occupants'],
        'date_start': str(df_1m.index.min().date()),
        'date_end': str(df_1m.index.max().date()),
        'days_monitored': round(days_monitored, 1),
        'total_1min_periods': n_total_mins,
        'missing_mins': int(n_missing_mins),
        'missing_pct': round(float(n_missing_mins / n_total_mins * 100), 2),
        'zero_off_pct': round(zero_pct, 2),
        'standby_pct': round(standby_pct, 2),
        'active_pct': round(active_pct, 2),
        'detected_cycles': len(cycles_df),
        'cycles_per_week': round(cycles_per_week, 2),
        'mean_cycle_duration_mins': round(float(cycles_df['duration_mins'].mean()), 1) if len(cycles_df) else 0,
        'median_cycle_duration_mins': round(float(cycles_df['duration_mins'].median()), 1) if len(cycles_df) else 0,
        'mean_peak_power_w': round(float(cycles_df['peak_power_w'].mean()), 1) if len(cycles_df) else 0,
        'mean_energy_kwh': round(float(cycles_df['energy_kwh'].mean()), 3) if len(cycles_df) else 0
    }
    
    return df_1m_clean, cycles_df, metrics

def run_washing_machine_eda(output_dir='figures'):
    """
    Executes full EDA across the selected 5 households, computes metrics,
    and creates required figures:
    (i) 24-hour trace of aggregate + washing machine
    (ii) Detected washing-machine cycle details
    (iii) Cross-house comparison
    (iv) Diurnal and day-of-week usage distributions
    """
    os.makedirs(output_dir, exist_ok=True)
    all_metrics = []
    all_cycles = []
    house_dfs = {}
    
    for hname, cfg in HOUSE_CONFIG.items():
        df_1m, cycles_df, metrics = load_and_resample_household(hname, cfg)
        all_metrics.append(metrics)
        all_cycles.append(cycles_df)
        house_dfs[hname] = (df_1m, cfg['wm_col'])
        
    summary_df = pd.DataFrame(all_metrics)
    combined_cycles = pd.concat(all_cycles, ignore_index=True)
    print("\n=== Washing Machine Availability & Quality Summary ===")
    print(summary_df[['house', 'model', 'occupants', 'days_monitored', 'zero_off_pct', 'detected_cycles', 'cycles_per_week', 'mean_cycle_duration_mins', 'mean_energy_kwh']])
    
    # -------------------------------------------------------------
    # Plot 1: Representative 24-hour aggregate + washing machine trace
    # -------------------------------------------------------------
    # Choose House 2 on 2014-04-12 (a clear active day with multiple appliance events)
    h2_df, h2_wm_col = house_dfs['House 2']
    t_start = pd.to_datetime('2014-04-12 00:00:00')
    t_end = pd.to_datetime('2014-04-12 23:59:00')
    mask_24h = (h2_df.index >= t_start) & (h2_df.index <= t_end)
    sub_24h = h2_df.loc[mask_24h]
    
    fig, ax = plt.subplots(figsize=(14, 5.5))
    ax.plot(sub_24h.index, sub_24h['Aggregate'], color='#7f8c8d', lw=1.2, label='Household Aggregate Load')
    ax.plot(sub_24h.index, sub_24h[h2_wm_col], color='#e74c3c', lw=2.0, label='Washing Machine (LG F1289TD)')
    ax.fill_between(sub_24h.index, 0, sub_24h[h2_wm_col], color='#e74c3c', alpha=0.35)
    ax.set_title('Representative 24-Hour Trace: Aggregate vs Washing Machine Load (House 2, 2014-04-12)', fontsize=13, fontweight='bold')
    ax.set_ylabel('Active Power (Watts)', fontsize=11)
    ax.set_xlabel('Time of Day', fontsize=11)
    ax.grid(True, linestyle=':', alpha=0.6)
    ax.legend(fontsize=11, loc='upper right')
    
    # Annotate the wash cycle
    wm_peak_time = sub_24h[h2_wm_col].idxmax()
    wm_peak_val = sub_24h[h2_wm_col].max()
    ax.annotate(f'Wash Cycle\n(Heating Pulse {wm_peak_val:.0f} W)',
                xy=(wm_peak_time, wm_peak_val),
                xytext=(wm_peak_time + pd.Timedelta(hours=1.5), wm_peak_val * 0.9),
                arrowprops=dict(facecolor='black', shrink=0.08, width=1.5, headwidth=8),
                fontsize=10, fontweight='bold',
                bbox=dict(boxstyle="round,pad=0.3", fc="#f1c40f", alpha=0.8))
                
    p1_path = os.path.join(output_dir, 's2_24h_trace.png')
    plt.tight_layout()
    plt.savefig(p1_path, dpi=200)
    plt.close()
    print(f"Saved: {p1_path}")
    
    # -------------------------------------------------------------
    # Plot 2: Detailed Anatomy of Detected Washing-Machine Cycles
    # -------------------------------------------------------------
    # Take two example cycles from House 1 (Beko) and House 2 (LG)
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    
    # Example cycle 1: House 1
    h1_df, h1_wm_col = house_dfs['House 1']
    h1_cycles = combined_cycles[combined_cycles['house'] == 'House 1'].iloc[15]
    c1_series = h1_df[h1_wm_col].loc[h1_cycles['start_time'] - pd.Timedelta(minutes=5) : h1_cycles['end_time'] + pd.Timedelta(minutes=10)]
    t_rel1 = [(t - h1_cycles['start_time']).total_seconds() / 60.0 for t in c1_series.index]
    
    axes[0].plot(t_rel1, c1_series.values, color='#2980b9', lw=2)
    axes[0].fill_between(t_rel1, 0, c1_series.values, color='#3498db', alpha=0.3)
    axes[0].axvspan(0, h1_cycles['duration_mins'], color='#2ecc71', alpha=0.15, label='Detected Cycle Window')
    axes[0].set_title(f"House 1 (Beko WMC6140): {h1_cycles['duration_mins']}m Cycle ({h1_cycles['energy_kwh']:.2f} kWh)", fontsize=11, fontweight='bold')
    axes[0].set_xlabel('Elapsed Time (minutes)', fontsize=10)
    axes[0].set_ylabel('Power (Watts)', fontsize=10)
    axes[0].grid(True, linestyle=':', alpha=0.6)
    axes[0].legend(fontsize=9)
    
    # Example cycle 2: House 2
    h2_cycles = combined_cycles[combined_cycles['house'] == 'House 2'].iloc[22]
    c2_series = h2_df[h2_wm_col].loc[h2_cycles['start_time'] - pd.Timedelta(minutes=5) : h2_cycles['end_time'] + pd.Timedelta(minutes=10)]
    t_rel2 = [(t - h2_cycles['start_time']).total_seconds() / 60.0 for t in c2_series.index]
    
    axes[1].plot(t_rel2, c2_series.values, color='#d35400', lw=2)
    axes[1].fill_between(t_rel2, 0, c2_series.values, color='#e67e22', alpha=0.3)
    axes[1].axvspan(0, h2_cycles['duration_mins'], color='#2ecc71', alpha=0.15, label='Detected Cycle Window')
    axes[1].set_title(f"House 2 (LG F1289TD): {h2_cycles['duration_mins']}m Cycle ({h2_cycles['energy_kwh']:.2f} kWh)", fontsize=11, fontweight='bold')
    axes[1].set_xlabel('Elapsed Time (minutes)', fontsize=10)
    axes[1].set_ylabel('Power (Watts)', fontsize=10)
    axes[1].grid(True, linestyle=':', alpha=0.6)
    axes[1].legend(fontsize=9)
    
    p2_path = os.path.join(output_dir, 's2_wm_cycles.png')
    plt.tight_layout()
    plt.savefig(p2_path, dpi=200)
    plt.close()
    print(f"Saved: {p2_path}")
    
    # -------------------------------------------------------------
    # Plot 3: Diurnal (Hour of Day) & Day of Week Usage Patterns
    # -------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    
    # Hour of day distribution
    hourly_counts = combined_cycles.groupby(['start_hour', 'house']).size().unstack(fill_value=0)
    hourly_norm = hourly_counts.div(hourly_counts.sum(axis=0), axis=1) * 100
    hourly_norm.plot(kind='line', ax=axes[0], marker='o', lw=2)
    axes[0].set_title('Washing Machine Starts by Hour of Day (% of Home Cycles)', fontsize=12, fontweight='bold')
    axes[0].set_xlabel('Hour of Day (0 - 23)', fontsize=10)
    axes[0].set_ylabel('Percentage of Cycles (%)', fontsize=10)
    axes[0].set_xticks(range(0, 24, 2))
    axes[0].grid(True, linestyle=':', alpha=0.6)
    axes[0].legend(title='Household', fontsize=9)
    
    # Day of week distribution
    day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    dow_counts = combined_cycles.groupby(['day_of_week', 'house']).size().unstack(fill_value=0).reindex(day_order)
    dow_norm = dow_counts.div(dow_counts.sum(axis=0), axis=1) * 100
    dow_norm.plot(kind='bar', ax=axes[1], width=0.8)
    axes[1].set_title('Washing Machine Starts by Day of Week (% of Home Cycles)', fontsize=12, fontweight='bold')
    axes[1].set_xlabel('Day of Week', fontsize=10)
    axes[1].set_ylabel('Percentage of Cycles (%)', fontsize=10)
    axes[1].grid(True, linestyle=':', alpha=0.6)
    axes[1].legend(title='Household', fontsize=9)
    axes[1].tick_params(axis='x', rotation=30)
    
    p3_path = os.path.join(output_dir, 's2_hourly_dow_patterns.png')
    plt.tight_layout()
    plt.savefig(p3_path, dpi=200)
    plt.close()
    print(f"Saved: {p3_path}")
    
    # -------------------------------------------------------------
    # Plot 4: Cross-House Comparison of Key Cycle Characteristics
    # -------------------------------------------------------------
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    houses_list = list(HOUSE_CONFIG.keys())
    
    # Subplot A: Cycle Duration Boxplot
    dur_data = [combined_cycles[combined_cycles['house'] == h]['duration_mins'].values for h in houses_list]
    axes[0].boxplot(dur_data, tick_labels=[f"{h}\n({HOUSE_CONFIG[h]['occupants']} occ)" for h in houses_list], patch_artist=True,
                    boxprops=dict(facecolor='#aed6f1', color='#2980b9'),
                    medianprops=dict(color='#c0392b', lw=2))
    axes[0].set_title('Cycle Duration across Households', fontsize=11, fontweight='bold')
    axes[0].set_ylabel('Duration (minutes)', fontsize=10)
    axes[0].grid(True, linestyle=':', alpha=0.6)
    
    # Subplot B: Energy per Cycle Boxplot
    nrg_data = [combined_cycles[combined_cycles['house'] == h]['energy_kwh'].values for h in houses_list]
    axes[1].boxplot(nrg_data, tick_labels=[f"{h}\n({HOUSE_CONFIG[h]['occupants']} occ)" for h in houses_list], patch_artist=True,
                    boxprops=dict(facecolor='#a9dfbf', color='#27ae60'),
                    medianprops=dict(color='#c0392b', lw=2))
    axes[1].set_title('Energy Consumption per Cycle', fontsize=11, fontweight='bold')
    axes[1].set_ylabel('Energy (kWh)', fontsize=10)
    axes[1].grid(True, linestyle=':', alpha=0.6)
    
    # Subplot C: Weekly Cycle Frequency Bar Plot
    axes[2].bar([f"{h}\n({HOUSE_CONFIG[h]['occupants']} occ)" for h in houses_list],
                summary_df['cycles_per_week'],
                color='#f39c12', edgecolor='black', alpha=0.85)
    axes[2].set_title('Weekly Cycle Frequency (Cycles / Week)', fontsize=11, fontweight='bold')
    axes[2].set_ylabel('Mean Cycles per Week', fontsize=10)
    axes[2].grid(True, linestyle=':', alpha=0.6)
    for i, v in enumerate(summary_df['cycles_per_week']):
        axes[2].text(i, v + 0.15, f"{v:.1f}", ha='center', fontweight='bold', fontsize=10)
        
    p4_path = os.path.join(output_dir, 's2_cross_house_comparison.png')
    plt.tight_layout()
    plt.savefig(p4_path, dpi=200)
    plt.close()
    print(f"Saved: {p4_path}")
    
    return summary_df, combined_cycles
