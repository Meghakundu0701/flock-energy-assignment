# Flock Energy: REFIT Data Cleaning & Appliance Disaggregation

A modular, reproducible, end-to-end data science pipeline built for **Flock Energy** using the University of Strathclyde **REFIT Electrical Load Measurements** dataset. The project implements:
1. **Raw Telemetry Inspection & Cleaning (Section 1)**: Ingests raw House 1 data, resolves non-monotonic timestamps, filters 16-bit sensor overflows (>4 kW), removes duplicate timestamps, resamples to a uniform 1-minute grid, and flags extended outages.
2. **Multi-Household Washing-Machine EDA (Section 2)**: Analyzes 5 households with dedicated washing-machine channels (Houses 1, 2, 3, 5, 16), defines a physics-grounded cycle detection rule, profiles diurnal/weekly habits, and cross-compares appliance characteristics.
3. **Appliance Disaggregation Model (Section 3)**: Disaggregates washing machine load from whole-home aggregate smart-meter data using sequence-windowed feature gradient boosting, evaluated against reference baselines on a strict chronological holdout split.
4. **Utility Strategy & Practical Implications (Section 4)**: Synthesizes findings into actionable utility recommendations, evaluates 15/30-minute sampling limits, and details cross-geography domain shifts (UK to India).

---

## 1. Repository Structure

```
flock/
├── figures/                              # Generated high-resolution plots
│   ├── s1_house1_cleaning_comparison.png   # Raw vs Cleaned aggregate & appliances (House 1)
│   ├── s1_house1_interval_distribution.png # Distribution of raw sampling intervals
│   ├── s2_24h_trace.png                    # Representative 24h aggregate vs washing machine trace
│   ├── s2_wm_cycles.png                    # Detailed anatomy of detected wash cycles
│   ├── s2_hourly_dow_patterns.png          # Diurnal (hour of day) and day of week distributions
│   ├── s2_cross_house_comparison.png       # Cycle duration, energy, and frequency across 5 homes
│   ├── s3_actual_vs_predicted.png          # Test set actual vs predicted disaggregation
│   └── s3_error_distribution.png           # Test set residual power error distribution
├── src/                                  # Modular source code
│   ├── __init__.py
│   ├── clean_raw.py                        # Section 1: Raw data inspection & cleaning pipeline
│   ├── eda_washing_machine.py              # Section 2: Washing machine cycle detection & EDA
│   └── disaggregation_model.py             # Section 3: Sequence feature engineering & model training
├── data_summary/                         # Generated data artifacts & metrics
│   ├── section1_raw_inspection.json        # Raw House 1 quality metrics
│   ├── section2_detected_cycles.csv        # Detected cycle logs across 5 households
│   ├── section2_household_summary.csv      # Household availability & duty cycle summary
│   └── section3_model_metrics.csv          # Test set benchmark metrics (Baselines vs Model)
├── run_pipeline.py                       # Master CLI script executing all steps end-to-end
├── pipeline_notebook.ipynb               # Fully reproducible Jupyter notebook
├── README.md                             # Architecture, setup, assumptions, and trade-offs
├── DATA.md                               # Data coverage, quality findings, cleaning steps, gaps
├── RESULTS.md                            # Comprehensive EDA, modeling metrics, plots & interpretations
├── Recommendation.md                     # Utility-facing summary and Section 4 answers
├── requirements.txt                      # Python dependencies
└── .gitignore                            # Clean repo tracking configuration
```

---

## 2. Setup & Execution Instructions

### Prerequisites
- Python 3.10+ (tested on Python 3.13)
- Dataset archives or extracted CSV files located in repository root:
  - Raw: `RAW_House1_Part1.csv` (or `REFIT_RAW_081116.7z`)
  - Clean: `CLEAN_House1.csv`, `CLEAN_House2.csv`, `CLEAN_House3.csv`, `CLEAN_House5.csv`, `CLEAN_House16.csv` (or `CLEAN_REFIT_081116.7z`)

### Quickstart

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Execute Full Pipeline (CLI)**:
   ```bash
   python run_pipeline.py
   ```
   *Runs all steps end-to-end in ~85 seconds, generating all figures in `figures/` and metrics in `data_summary/`.*

3. **Run Interactively (Jupyter Notebook)**:
   ```bash
   jupyter notebook pipeline_notebook.ipynb
   ```

---

## 3. Assumptions & Preprocessing Decisions

1. **Timezone & Ordering**: Timestamps in raw files suffer from local British Summer Time shifts and backward jumps. We convert Unix epoch timestamps to UTC (`pd.to_datetime(df['Unix'], unit='s', utc=True)`) and sort chronologically.
2. **De-duplication Rule**: Concurrent duplicate timestamps are grouped by timestamp and aggregated via column-wise mean.
3. **Physical Extreme Filtering**: Domestic UK plug circuits (13A at 230V) cannot exceed ~3 kW. Values > 4,000 W on appliance channels (e.g., 32,767 W and 65,535 W integer overflows) and > 25,000 W on aggregate are replaced with NaN before resampling.
4. **Resampling Grid**: Resampled to a uniform 1-minute (`60s`) interval using mean power.
5. **Gap Handling vs Outage Flagging**: Short gaps ($\le 3$ minutes) are linearly interpolated, reflecting persistent appliance operational states. Longer outages ($> 3$ minutes) are strictly masked and flagged as outages, avoiding artificial baseload plateaus or false zeros.

---

## 4. Validation Design & Data Leakage Prevention

- **Strict Chronological Holdout**:
  - We train on earlier months (70%), validate on intermediate months (10%), and test on the final holdout period (20%).
  - **Leakage Prevention**: Standard random train/test splits or random k-fold cross-validation cause severe look-ahead leakage in NILM because sliding feature windows $[-15\text{ min}, +15\text{ min}]$ and active wash cycles ($40$ to $120$ minutes) share high auto-correlation across adjacent minutes. A chronological partition ensures that the model is evaluated on completely unseen future operational periods.
- **Baselines**:
  - *Baseline 1 (Always-Off)*: Predicts 0 W. Tests whether models capitalize on the extreme sparsity of the appliance ($95\%$ off).
  - *Baseline 2 (Hourly Profile)*: Predicts the historical training mean for each hour of the day.

---

## 5. Architectural Trade-Offs

| Decision | Chosen Approach | Alternative Considered | Trade-off Rationale |
|---|---|---|---|
| **Resampling Rate** | 1-Minute Grid | 8-Second Raw / 15-Minute Grid | 1-minute captures the fast dynamics of heating coils and spin cycles while drastically reducing noise and memory footprint compared to 8-second polling. |
| **Model Architecture** | Sequence-Windowed Gradient Boosting | Deep CNN / Seq2Point PyTorch / Bi-LSTM | Gradient Boosting with sliding sequence statistics trains in ~4 seconds on CPU, is fully deterministic, requires no GPU, and avoids heavy deep learning dependencies while matching Seq2Point performance. |
| **Long Outage Handling** | Outage Masking (NaN) | Zero-filling or Forward-filling | Zero-filling artificially distorts energy consumption and duty cycle; forward-filling fabricates constant loads for days. Masking preserves statistical integrity. |

---

## 6. AI Tools Used

During the development of this project:
- **Claude (Anthropic), Gemini (Google), and ChatGPT (OpenAI)**: Used as AI pair programming and research assistants for ideation, drafting exploratory analysis scripts, sanity-checking pandas vectorization patterns, and reviewing documentation structure against take-home guidelines.
- All code implementation, data handling decisions, pipeline execution, mathematical definitions, and validation analyses were tested and verified locally.

---

## 7. Possible Future Improvements

1. **Multi-Task Learning (State + Power Regression)**: Jointly predict discrete operational state (Off, Wash/Heat, Rinse, Spin) alongside continuous power output to eliminate low-power background noise.
2. **Cross-Household Transfer / Domain Adaptation**: Implement adversarial feature alignment or zero-shot transfer learning across homes to adapt to unmetered target households without requiring ground-truth sub-metering.
3. **Reactive Power Incorporation**: Where available, incorporating reactive power ($Q$) or power factor significantly aids in distinguishing resistive heating elements from inductive motor loads.

---

## 8. Summary of Results

- **Cleaning**: Over 1M duplicate timestamps and 3,000+ integer overflow spikes resolved on House 1.
- **EDA**: Identified 2,220 total cycles across 5 households; established that laundry is concentrated between 9:00 AM – 12:00 PM and on weekends, drawing 0.32–0.60 kWh per wash.
- **Model**: Sequence Gradient Boosting model reduces RMSE by **18.6%** over the Always-Off baseline and achieves an active state **F1-Score of 0.3649** (3.4x precision gain over the hourly baseline).

*For in-depth analysis and plots, refer to [DATA.md](DATA.md), [RESULTS.md](RESULTS.md), and [Recommendation.md](Recommendation.md).*
