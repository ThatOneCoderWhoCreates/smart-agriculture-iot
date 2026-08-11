# Model performance (held-out test period, days 15-20)

| Model                       | Metric                        |   Value |
|:----------------------------|:------------------------------|--------:|
| M1 Random Forest Classifier | Accuracy                      |  0.9782 |
|                             | Precision                     |  0.9216 |
|                             | Recall                        |  0.8433 |
|                             | F1-score                      |  0.8807 |
|                             | ROC-AUC                       |  0.997  |
|                             | Threshold-rule baseline F1    |  0.0521 |
| M2 Random Forest Regressor  | MAE (%)                       |  0.8578 |
|                             | RMSE (%)                      |  1.9417 |
|                             | R2                            |  0.948  |
|                             | Persistence baseline RMSE (%) |  3.2264 |
|                             | Skill score vs persistence    |  0.6378 |
| M3 Isolation Forest         | Precision                     |  0.3265 |
|                             | Recall                        |  0.4629 |
|                             | F1-score                      |  0.3829 |
|                             | ROC-AUC                       |  0.836  |

## M1 top-10 permutation importance

|                     |       0 |
|:--------------------|--------:|
| light_ma_120        | 0.02335 |
| light_pct           | 0.01965 |
| light_lag_15        | 0.01425 |
| water_level_pct     | 0.01345 |
| soil_ma_120         | 0.01265 |
| deficit_from_target | 0.01014 |
| soil_moisture_pct   | 0.00868 |
| soil_lag_30         | 0.0078  |
| soil_lag_15         | 0.00626 |
| soil_std_60         | 0.00625 |

## M2 top-10 Gini importance

|                     |       0 |
|:--------------------|--------:|
| deficit_from_target | 0.35536 |
| soil_moisture_pct   | 0.28741 |
| soil_ma_30          | 0.12207 |
| soil_lag_5          | 0.10843 |
| soil_lag_15         | 0.06839 |
| soil_lag_30         | 0.01275 |
| soil_lag_60         | 0.00976 |
| soil_rate_60        | 0.00634 |
| soil_ma_120         | 0.00462 |
| pump_on_last_60     | 0.0033  |

## M3 recall by fault family

|         |      0 |
|:--------|-------:|
| drift   | 0.2819 |
| dropout | 0      |
| spike   | 1      |
| stuck   | 0.7076 |