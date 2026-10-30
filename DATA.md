# DATA.md: REFIT Dataset Coverage, Quality Inspection, and Cleaning Pipeline

## 1. Dataset Overview & Documentation

The analysis uses the **REFIT Electrical Load Measurements** dataset collected by the University of Strathclyde, Loughborough University, and the University of East Anglia (supported by EPSRC). The study monitored 20 UK households across Loughborough between 2013 and 2015.

- **Households & Files Monitored**: 20 homes (labelled House 1 to House 21, skipping House 14). Each house is monitored with a whole-house aggregate current clamp and up to 9 Individual Appliance Monitors (IAMs).
- **Nominal Sampling Interval**: Polled approximately every 6–8 seconds (event-triggered when power changes).
- **Units**: Active power in **Watts (W)**. Timestamps are provided as ISO-like strings (`YYYY-MM-DD HH:MM:SS`) and Unix epoch timestamps (`Unix`).
- **Files Used**:
  - `RAW_House1_Part1.csv` & `RAW_House1_Part2.csv`: Raw uncleaned telemetry for House 1 used in Section 1.
  - `CLEAN_House1.csv`, `CLEAN_House2.csv`, `CLEAN_House3.csv`, `CLEAN_House5.csv`, `CLEAN_House16.csv`: Official cleaned datasets for multi-household exploratory analysis (Section 2) and disaggregation modeling (Section 3).
  - `CLEAN_READ_ME_081116.txt`: Official dataset documentation and metadata.

---

## 2. Raw Data Inspection & Quality Findings (House 1)

Detailed auditing of `RAW_House1_Part1.csv` (4,377,877 rows, Oct 2013 – Oct 2014) and `RAW_House1_Part2.csv` (4,140,886 rows, Jun 2014 – Jul 2015) revealed several critical data-quality anomalies:

### 2.1 Timestamp Parsing, Ordering & Timezone Discrepancies
- **Daylight Saving Time Inconsistencies**: The string `Time` column in raw files was logged in local UK time, leading to non-monotonic clock resets during daylight savings shifts (e.g., the autumn transition back to GMT produced negative intervals of $-3,597$ seconds).
- **Non-positive Steps**: In Part 1, **1,003,951 consecutive time steps ($\approx 22.9\%$) had non-positive intervals** ($\Delta t \le 0$). Readings were frequently out of chronological order due to asynchronous logger buffers.
- **Conversion Resolution**: Parsing the `Unix` epoch seconds as UTC (`pd.to_datetime(df['Unix'], unit='s', utc=True)`) completely resolves clock jumps and provides a monotonic global timeline.

### 2.2 Duplicate Timestamps
- **Part 1**: Contains **1,004,404 duplicate Unix timestamps** ($22.94\%$ of all rows).
- **Part 2**: Contains **14,755 duplicate Unix timestamps** ($0.36\%$).
- **Root Cause**: The data logger recorded changes across multiple IAM channels or aggregate clamps in asynchronous bursts, writing multiple rows with the identical second timestamp when multiple sensors reported near-simultaneously.

### 2.3 Irregular Intervals & Outages
- **Sampling Interval Distribution**:
  - Minimum: $-3,597$ s (raw clock rewind)
  - 1st Percentile: $0$ s (duplicate)
  - Median: $3.0$ s (rapid change logging)
  - 95th Percentile: $15.0$ s
  - Maximum: $3,594,414$ s ($\approx 41.6$ days)
- **Extended Outages**: Part 1 exhibits a severe 41.6-day outage in February 2014 caused by an internet gateway/hardware routing failure. Part 2 exhibits an 8.6-day gap ($747,251$ seconds).

```
   House 1 Raw Sampling Interval Quantiles:
   ┌────────────┬──────────────┐
   │ Percentile │ Interval (s) │
   ├────────────┼──────────────┤
   │ Min        │ -3,597 s     │
   │ 1%         │ 0 s          │
   │ Median     │ 3 s          │
   │ 95%        │ 15 s         │
   │ 99%        │ 15 s         │
   │ Max        │ 3,594,414 s  │
   └────────────┴──────────────┘
```

### 2.4 Extreme & Physically Impossible Power Spikes
Standard domestic appliances in the UK are supplied at 230V single-phase and protected by a 13A plug fuse (theoretical resistive ceiling $\approx 3,000$ W). Inspection of raw appliance channels revealed severe telemetry corruption and 16-bit integer overflow artifacts:
- **Appliance 1 (Fridge)**: Maximum value of **69,629 W** (impossible for a domestic refrigerator).
- **Appliance 2 & Appliance 4 (Freezer / Washer-Dryer)**: Maximum of **98,301 W**.
- **Appliance 5 (Washing Machine)**: Maximum of **32,767 W** (exactly $2^{15} - 1$, the signed 16-bit integer maximum).
- **Appliance 9**: Maximum of **65,535 W** (exactly $2^{16} - 1$, unsigned 16-bit integer maximum).
- **Spike Count**: Over 3,038 readings exceeded 4 kW on individual sub-metered channels.

---

## 3. Documented Cleaning Pipeline

To transform the raw telemetry into an analysis-ready time series, we implemented a simple, rigorous, 5-step pipeline:

```
Raw Telemetry
      │
      ▼
[1. Chronological Sort] ──► Order strictly by Unix epoch timestamp
      │
      ▼
[2. Spike Filtering]    ──► Cap impossible physical extremes:
                            - Appliances: [0, 4,000 W] (values > 4kW or < 0 -> NaN)
                            - Aggregate:  [0, 25,000 W] (values > 25kW or < 0 -> NaN)
      │
      ▼
[3. De-duplication]     ──► Group by Unix timestamp: mean of concurrent valid sensor updates
      │
      ▼
[4. 1-Minute Grid]      ──► Resample to uniform 60s frequency: mean active power per minute
      │
      ▼
[5. Gap vs Outage]      ──► Short gaps (<= 3 mins): linear interpolation
                            Long outages (> 3 mins): flagged as outages (masked NaN)
```

### Pipeline Decision Details:
1. **De-duplication Stated Rule**: When multiple rows share the same `Unix` second, we group by timestamp and compute the mean of non-null values. This prevents data loss while averaging out sensor sub-second jitter.
2. **Short Missing Gaps ($\le 3$ minutes)**: Filled via linear time interpolation. In domestic settings, thermal and motor states do not vanish during a transient 60–120s logger hiccup.
3. **Outage Flagging ($> 3$ minutes)**: Left strictly un-interpolated and flagged (`is_outage = True`). Filling multi-hour or multi-week gaps with zeros falsely dilutes load factor, while forward-filling creates artificial baseload plateaus.

---

## 4. Cleaning Results & Visual Verification

- **Total 1-minute intervals generated**: 513,322 periods (House 1 Part 1 span).
- **Missing intervals prior to gap filling**: 76,904 minutes.
- **Short gaps safely interpolated ($\le 3$ mins)**: 1,635 minutes.
- **Flagged long outage buckets ($> 3$ mins)**: 75,269 minutes across 395 distinct outage blocks.

### Visual Comparison: Before vs After Cleaning
The generated figure `figures/s1_house1_cleaning_comparison.png` visualizes a 48-hour continuous window comparing raw vs cleaned streams:
- **Aggregate**: Raw irregular step noise is replaced by a crisp 1-minute load profile.
- **Appliance 1 (Fridge)**: 69 kW telemetry spikes are removed; regular cyclic thermostat cycling (~70 W) is cleanly recovered.
- **Appliance 5 (Washing Machine)**: Integer overflow spikes (32,767 W) are eliminated while preserving authentic 2.3 kW wash cycles.

![Cleaning Comparison](figures/s1_house1_cleaning_comparison.png)

### Sampling Interval Distribution
The distribution plot `figures/s1_house1_interval_distribution.png` confirms that over 90% of raw readings arrive within 3 to 15 seconds, with a median of 3.0 seconds, justifying the 1-minute resampling window.

![Interval Distribution](figures/s1_house1_interval_distribution.png)

---

## 5. Remaining Data Quality Concerns & Caveats

1. **Unmonitored Baseload / Sub-meter Discrepancies**: In the official cleaned data, `Issues == 1` flags intervals where $\sum \text{Appliance}_i > \text{Aggregate}$. Although infrequent in House 1 ($0.84\%$) and House 2 ($0.50\%$), House 3 and House 5 have $\approx 5.7\%$ flagged rows. These rows were filtered out before disaggregation modeling.
2. **Appliance Swapping**: As noted in the REFIT metadata, occupants were requested not to move plugs, but occasional changes occurred (e.g., kettles or blenders swapped into monitored sockets).
3. **Standby Creep**: Standby draw on modern washing machines (1–5 W) can be confused with true low-power idling unless a strict active threshold ($\ge 20$ W) is enforced.
