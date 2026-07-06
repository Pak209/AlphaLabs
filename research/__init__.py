"""AlphaLabs quantitative research framework.

Offline, read-only analysis of the decision telemetry that production already
collects (signal_evaluations, execution_audit gate traces, alpha_ideas,
training_rows). Nothing in this package creates ideas, decisions, orders, or
trades, and every database connection it opens is forced read-only.

See docs/RESEARCH_WORKFLOW.md for the workflow this package implements and
docs/CALIBRATION_PLAN.md for the governance rules it operates under.
"""
