# Security and evidence boundary

Only process source content you are authorized to use. Fixture mode has no provider calls. Live mode explicitly transmits the supplied bundle to the official OpenAI Responses endpoint; environment API keys are passed only to the SDK, never written to reports.

The system prompt treats source text as untrusted data. Deterministic review prevents new claim text, out-of-scope citations, incomplete question coverage and fabricated source metadata. It does not establish semantic relevance, source accuracy, currentness or completeness. A malicious source can contain false statements that still pass exact matching. This tool is not a prompt-injection defense certificate.

There are no callable tools beyond the framework's structured output mechanism. No source URL fetch, arbitrary command, provider base URL, model fallback, secret vault, persistence or notification service is included. The framework's optional observability is not configured. Network isolation belongs to the deployment operator.

Limits protect common accidental oversize inputs and uncontrolled retry loops. Native token counting runs before live generation but may itself make a provider request. The timeout/cost guard is not a guarantee against billing. Price inputs are operator-supplied; provider budgets remain separate.

Exports intentionally include chosen evidence text, source IDs, URL paths and region/version. They omit unused source text and raw model messages. Input IDs or URL paths may themselves be sensitive. Inspect exports before publication. Stable unkeyed SHA-256 input digests are reproducibility markers, not signatures or anonymization.

Please report reproducible defects through the repository's GitHub issue tracker using synthetic data only. Never include real source documents, API keys or model message dumps.
