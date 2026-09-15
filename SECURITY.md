# Security

## Reporting a vulnerability

Email **hello@vantion.co** with "Security" in the subject. Include a
description, the affected commit, and steps to reproduce. Please do not open
a public issue.

We aim to reply within a few working days, confirm the issue, agree a
disclosure date with you, and credit you in the release notes unless you
prefer not to be named.

## Running it safely

- **Adapters are code.** `target.adapter` imports and runs a Python module named in
  `evals.yaml`. Treat a config from someone else like any script you are asked to run.
- **Reports contain inputs and outputs.** If your test cases or your application's
  answers include personal or confidential data, treat `reports/` and anything you
  export to Langfuse accordingly, and keep `reports/` out of public artifacts.
- **Judge prompts see your data.** Rubric cases send the input, the sources and the
  answer to the judge's provider.
- **Keys** for providers, Langfuse and HTTP targets come from the environment. Use
  your CI's secret store, never the config file.
