# Evaluation report

Model: `groq/openai/gpt-oss-20b`

| Metric | Value |
|---|---|
| answer_accuracy | 0.905 |
| strict_exact | 0.571 |
| safety_pass_rate | 1.0 |
| first_try_rate | 0.905 |
| median_latency_ms | 2085 |
| avg_tokens | 866 |
| answer accuracy (ambiguous) | 1.0 |
| answer accuracy (followup) | 1.0 |
| answer accuracy (glossary) | 1.0 |
| answer accuracy (hard) | 0.8 |
| answer accuracy (medium) | 1.0 |

## Failures

- **#102** What is the repeat purchase rate: the percentage of customers with at least 2 completed orders among customers with at least 1 completed order? -> `success` 
- **#103** For each country, what is net revenue per customer, dividing by ALL customers in that country including those who never bought? -> `success` 