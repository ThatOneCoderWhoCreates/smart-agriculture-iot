# Stage-2 analytics tables

## Descriptive statistics

|                   |   count |   mean |    std |   min |   5% |   25% |   50% |   75% |   95% |   max |   skew |   kurtosis |    cv_% |
|:------------------|--------:|-------:|-------:|------:|-----:|------:|------:|------:|------:|------:|-------:|-----------:|--------:|
| temperature_c     |   30180 | 28.328 |  6.002 |    14 | 19   | 23    | 29    | 33    | 38    |    60 | -0.004 |     -0.957 |  21.189 |
| humidity_pct      |   30180 | 50.059 | 18.639 |     0 | 27   | 35    | 46    | 63    | 88    |   100 |  0.706 |     -0.265 |  37.234 |
| soil_moisture_pct |   30180 | 48.92  |  9.971 |     0 | 34.9 | 41.64 | 50.73 | 56.99 | 60.02 |   100 | -0.629 |      1.211 |  20.382 |
| light_pct         |   30180 | 22.942 | 30.016 |     0 |  0   |  0    |  2.25 | 42.82 | 87.98 |   100 |  1.1   |     -0.075 | 130.835 |
| water_level_pct   |   30180 | 62.797 | 21.048 |     0 | 19.5 | 51.75 | 65.5  | 78    | 94.75 |   100 | -0.389 |     -0.484 |  33.518 |

## Pearson correlation (sensors)

|                   |   temperature_c |   humidity_pct |   soil_moisture_pct |   light_pct |   water_level_pct |
|:------------------|----------------:|---------------:|--------------------:|------------:|------------------:|
| temperature_c     |           1     |         -0.931 |              -0.362 |       0.665 |             0.142 |
| humidity_pct      |          -0.931 |          1     |               0.243 |      -0.581 |            -0.102 |
| soil_moisture_pct |          -0.362 |          0.243 |               1     |      -0.358 |             0.179 |
| light_pct         |           0.665 |         -0.581 |              -0.358 |       1     |             0.238 |
| water_level_pct   |           0.142 |         -0.102 |               0.179 |       0.238 |             1     |

## Spearman correlation (sensors)

|                   |   temperature_c |   humidity_pct |   soil_moisture_pct |   light_pct |   water_level_pct |
|:------------------|----------------:|---------------:|--------------------:|------------:|------------------:|
| temperature_c     |           1     |         -0.956 |              -0.406 |       0.664 |             0.15  |
| humidity_pct      |          -0.956 |          1     |               0.37  |      -0.636 |            -0.132 |
| soil_moisture_pct |          -0.406 |          0.37  |               1     |      -0.396 |             0.074 |
| light_pct         |           0.664 |         -0.636 |              -0.396 |       1     |             0.257 |
| water_level_pct   |           0.15  |         -0.132 |               0.074 |       0.257 |             1     |

## Outlier screening

| sensor            |   iqr_outliers |   global_z_outliers |   rolling_z_outliers |   pct_rolling |
|:------------------|---------------:|--------------------:|---------------------:|--------------:|
| temperature_c     |              1 |                   1 |                   13 |         0.043 |
| humidity_pct      |              0 |                   0 |                   14 |         0.046 |
| soil_moisture_pct |            560 |                 583 |                   62 |         0.205 |
| light_pct         |              0 |                   0 |                  375 |         1.243 |
| water_level_pct   |             56 |                   0 |                   93 |         0.308 |

## Processing log

- [load] raw shape = (30240, 15)
- [clean] invalid / dropout readings converted to NaN : 220
- [clean] missing timestamps on the 1-min grid       : 0
- [clean] residual NaNs after imputation             : 0
- [feature] water-balance calibration: d(soil)/30min = +0.0980*pump_min -0.06480*ET_proxy +0.0012
- [feature] engineered table shape = (30180, 96)
- [corr] temperature leads maximum soil drying rate by ~0 min (r = -0.245)
- [baseline] rolling-z detector vs injected faults: precision=0.268 recall=0.088 (this is the bar Isolation Forest must beat)
