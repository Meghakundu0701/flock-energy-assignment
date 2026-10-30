"""
Section 3: Build and Evaluate an Appliance-Disaggregation Model
Author: Flock Energy Data Science Team
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, precision_recall_fscore_support

# Ensure joblib loky doesn't fail on Windows wmic
os.environ["LOKY_MAX_CPU_COUNT"] = "4"

def engineer_features(df_1m, agg_col='Aggregate', target_col='Appliance2'):
    """
    Engineers sequence context features for 1-minute aggregate load disaggregation:
    - Point aggregate power
    - Lagged and lead values capturing sequence context [-15 to +15 mins]
    - Rolling window statistics (mean, std, min, max over 5, 15, 30, 60 mins)
    - First-order power difference (step-change indicator)
    - Diurnal context (hour of day, day of week)
    """
    agg = df_1m[agg_col]
    features = pd.DataFrame(index=df_1m.index)
    features['agg'] = agg
    
    # Lag and lead features (Seq2Point context)
    for k in [1, 2, 3, 5, 10, 15]:
        features[f'lag_{k}'] = agg.shift(k)
        features[f'lead_{k}'] = agg.shift(-k)
        
    # Multi-scale rolling statistics
    for w in [5, 15, 30, 60]:
        features[f'roll_mean_{w}'] = agg.rolling(w, center=True).mean()
        features[f'roll_std_{w}'] = agg.rolling(w, center=True).std()
        features[f'roll_max_{w}'] = agg.rolling(w, center=True).max()
        features[f'roll_min_{w}'] = agg.rolling(w, center=True).min()
        
    features['agg_diff'] = agg.diff(1)
    features['hour'] = df_1m.index.hour
    features['dayofweek'] = df_1m.index.dayofweek
    
    y = df_1m[target_col].values
    valid_mask = ~features.isnull().any(axis=1) & ~np.isnan(y)
    
    X_clean = features.loc[valid_mask]
    y_clean = y[valid_mask.values]
    dt_clean = df_1m.index[valid_mask.values]
    
    return X_clean, y_clean, dt_clean

def temporal_split(X, y, dt, train_pct=0.70, val_pct=0.10):
    """
    Strict chronological partition into Train, Validation, and Test.
    Avoids data leakage from overlapping sliding windows and auto-correlated cycles.
    """
    n = len(X)
    n_train = int(n * train_pct)
    n_val = int(n * val_pct)
    
    X_train, y_train, dt_train = X.iloc[:n_train], y[:n_train], dt[:n_train]
    X_val, y_val, dt_val = X.iloc[n_train:n_train+n_val], y[n_train:n_train+n_val], dt[n_train:n_train+n_val]
    X_test, y_test, dt_test = X.iloc[n_train+n_val:], y[n_train+n_val:], dt[n_train+n_val:]
    
    return (X_train, y_train, dt_train), (X_val, y_val, dt_val), (X_test, y_test, dt_test)

def evaluate_predictions(y_true, y_pred, model_name, active_threshold=20.0):
    """
    Computes regression and ON/OFF detection metrics:
    - MAE: Mean Absolute Error in Watts
    - RMSE: Root Mean Square Error in Watts
    - SAE: Signal Aggregate Error (relative total energy discrepancy)
    - Active State Precision, Recall, and F1-score
    """
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    
    total_true_energy = np.sum(y_true)
    total_pred_energy = np.sum(y_pred)
    sae = np.abs(total_pred_energy - total_true_energy) / (total_true_energy + 1e-6)
    
    true_on = (y_true >= active_threshold).astype(int)
    pred_on = (y_pred >= active_threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(true_on, pred_on, average='binary', zero_division=0)
    
    return {
        'Model': model_name,
        'MAE (W)': round(float(mae), 2),
        'RMSE (W)': round(float(rmse), 2),
        'SAE': round(float(sae), 4),
        'Energy Error (%)': round(float(sae * 100), 2),
        'Precision': round(float(precision), 4),
        'Recall': round(float(recall), 4),
        'F1-Score': round(float(f1), 4),
        'Total True Energy (kWh)': round(float(total_true_energy / 60000.0), 2),
        'Total Pred Energy (kWh)': round(float(total_pred_energy / 60000.0), 2)
    }

def train_and_evaluate_disaggregation(df_1m, target_col='Appliance2', house_name='House 2', output_dir='figures'):
    """
    End-to-end pipeline for model training, baseline benchmarking,
    metrics calculation, and actual-vs-predicted visualization.
    """
    os.makedirs(output_dir, exist_ok=True)
    print(f"\n--- Training Disaggregation Model on {house_name} ---")
    
    # 1. Feature Engineering
    X, y, dt = engineer_features(df_1m, agg_col='Aggregate', target_col=target_col)
    
    # 2. Chronological Split
    (X_train, y_train, dt_train), (X_val, y_val, dt_val), (X_test, y_test, dt_test) = temporal_split(X, y, dt)
    print(f"Train period: {dt_train.min().date()} to {dt_train.max().date()} ({len(X_train):,} mins)")
    print(f"Val period:   {dt_val.min().date()} to {dt_val.max().date()} ({len(X_val):,} mins)")
    print(f"Test period:  {dt_test.min().date()} to {dt_test.max().date()} ({len(X_test):,} mins)")
    
    # 3. Baselines
    # Baseline 1: Always Off
    y_pred_base0 = np.zeros_like(y_test)
    
    # Baseline 2: Hour-of-day mean profile
    hourly_means = pd.Series(y_train, index=X_train.index).groupby(X_train['hour']).mean()
    y_pred_base_hourly = X_test['hour'].map(hourly_means).fillna(float(np.mean(y_train))).values
    
    # 4. Disaggregation Model: HistGradientBoostingRegressor
    model = HistGradientBoostingRegressor(
        max_iter=160,
        max_depth=8,
        learning_rate=0.08,
        min_samples_leaf=20,
        random_state=42
    )
    model.fit(X_train, y_train)
    
    raw_pred_test = model.predict(X_test)
    y_pred_model = np.clip(raw_pred_test, 0, None)
    # Threshold slight noise under 10W
    y_pred_model[y_pred_model < 10.0] = 0.0
    
    # 5. Evaluate Metrics
    metrics_base0 = evaluate_predictions(y_test, y_pred_base0, "Baseline 1: Always Off")
    metrics_base_hourly = evaluate_predictions(y_test, y_pred_base_hourly, "Baseline 2: Hourly Profile")
    metrics_model = evaluate_predictions(y_test, y_pred_model, "Sequence Gradient Boosting")
    
    results_df = pd.DataFrame([metrics_base0, metrics_base_hourly, metrics_model])
    print("\n--- Disaggregation Evaluation Metrics on Test Set ---")
    print(results_df.to_string(index=False))
    
    # 6. Plotting Actual vs Predicted on Evaluation Data
    # Find a representative test window with multiple washing machine cycles
    # Window of 4 days: 2015-02-14 to 2015-02-18
    eval_df = pd.DataFrame({
        'dt': dt_test,
        'Aggregate': X_test['agg'].values,
        'Actual': y_test,
        'Predicted': y_pred_model
    }).set_index('dt')
    
    # Find period with high actual activity
    daily_act = eval_df['Actual'].resample('D').sum()
    peak_day = daily_act.idxmax()
    plot_start = peak_day - pd.Timedelta(days=1)
    plot_end = peak_day + pd.Timedelta(days=2)
    
    sub_eval = eval_df.loc[plot_start:plot_end]
    
    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True, gridspec_kw={'height_ratios': [1, 2]})
    
    # Subplot 1: Household Aggregate Load
    axes[0].plot(sub_eval.index, sub_eval['Aggregate'], color='#7f8c8d', lw=1.2, label='Household Aggregate Load')
    axes[0].set_title(f"Test Set Disaggregation: {house_name} ({plot_start.date()} to {plot_end.date()})", fontsize=13, fontweight='bold')
    axes[0].set_ylabel('Aggregate (W)', fontsize=11)
    axes[0].grid(True, linestyle=':', alpha=0.6)
    axes[0].legend(loc='upper right')
    
    # Subplot 2: Actual vs Predicted Washing Machine Power
    axes[1].plot(sub_eval.index, sub_eval['Actual'], color='#2c3e50', lw=2.0, label='Actual Sub-metered WM Load')
    axes[1].plot(sub_eval.index, sub_eval['Predicted'], color='#e74c3c', lw=1.8, linestyle='--', label='Model Disaggregated WM Load')
    axes[1].fill_between(sub_eval.index, 0, sub_eval['Predicted'], color='#e74c3c', alpha=0.25)
    axes[1].set_ylabel('Washing Machine Power (W)', fontsize=11)
    axes[1].set_xlabel('Timestamp (UTC)', fontsize=11)
    axes[1].grid(True, linestyle=':', alpha=0.6)
    axes[1].legend(loc='upper right', fontsize=11)
    
    p_path = os.path.join(output_dir, 's3_actual_vs_predicted.png')
    plt.tight_layout()
    plt.savefig(p_path, dpi=200)
    plt.close()
    print(f"Saved: {p_path}")
    
    # 7. Error Distribution & Failure Mode Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    errors = y_pred_model - y_test
    ax.hist(errors, bins=60, range=(-500, 500), color='#8e44ad', edgecolor='black', alpha=0.75)
    ax.axvline(0, color='red', linestyle='--', lw=2)
    ax.set_title('Test Set Error Distribution (Predicted - Actual Power in Watts)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Error (Watts)', fontsize=11)
    ax.set_ylabel('Frequency (Minutes)', fontsize=11)
    ax.grid(True, linestyle=':', alpha=0.6)
    
    p_err_path = os.path.join(output_dir, 's3_error_distribution.png')
    plt.tight_layout()
    plt.savefig(p_err_path, dpi=200)
    plt.close()
    print(f"Saved: {p_err_path}")
    
    return results_df, model, eval_df
