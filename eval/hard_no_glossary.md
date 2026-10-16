# Evaluation report

Model: `groq/openai/gpt-oss-120b`

| Metric | Value |
|---|---|
| answer_accuracy | 0.714 |
| strict_exact | 0.429 |
| safety_pass_rate | 1.0 |
| first_try_rate | 0.714 |
| median_latency_ms | 1149 |
| avg_tokens | 589 |
| answer accuracy (ambiguous) | 1.0 |
| answer accuracy (followup) | 0.667 |
| answer accuracy (glossary) | 0.667 |
| answer accuracy (hard) | 0.7 |
| answer accuracy (medium) | 0.667 |

## Failures

- **#101** How many customers placed completed orders in both 2024 and 2025? -> `success` 
- **#103** For each country, what is net revenue per customer, dividing by ALL customers in that country including those who never bought? -> `success` 
- **#105** Show the running total of net revenue by month for 2025. -> `success` 
- **#113** What is the gross margin percentage overall (gross profit divided by net revenue)? -> `success` 
- **#116** What is the net revenue by sales channel? -> `success` 
- **#117** Now only for orders placed in 2025. -> `success` 