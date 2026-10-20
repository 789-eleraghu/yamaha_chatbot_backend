# Component 2: Time-of-Day (TOD) Tariff & Cost Accounting

## 1. Scope & Purpose
Calculates financial electricity bill costs under Tariff `HT_1`.

## 2. Tariff Schedule (`HT_1`)
| IST Hours | Band | Rate (₹/kWh) |
|---|---|---:|
| 00:00–04:59 | Off-Peak | 7.125 |
| 05:00–05:59 | Normal | 7.500 |
| 06:00–09:59 | Peak | 9.375 |
| 10:00–17:59 | Normal | 7.500 |
| 18:00–21:59 | Peak | 9.375 |
| 22:00–23:59 | Off-Peak | 7.125 |

## 3. Mandatory Rescaling Formula (Section 3)
Raw hourly deltas have period boundary losses. The model must strictly enforce:
1. Compute true daily energy:
   $$E_{\text{daily}} = \max(\text{counter}) - \min(\text{counter})$$
2. Compute raw hourly deltas ($h_0 \dots h_{23}$) using `toStartOfHour(reading_timestamp)`:
   $$h_i = \max_{\text{hour } i}(\text{counter}) - \min_{\text{hour } i}(\text{counter})$$
3. Compute rescaling factor:
   $$\text{scale} = \frac{E_{\text{daily}}}{\sum_{i=0}^{23} h_i}$$
4. Compute rescaled hourly values:
   $$h_i^* = h_i \times \text{scale}$$
5. Total Cost:
   $$\text{Cost (₹)} = \sum_{i=0}^{23} (h_i^* \times \text{Rate}_i)$$

## 4. Invariants
- Cost is ALWAYS calculated on **kWh**, NEVER on kVAh.
- Tariff rates are fixed constants and never rounded.
- Computed cost is rounded to 2 decimal places (or 1 for display).
