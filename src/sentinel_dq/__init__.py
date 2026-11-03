"""DataSentinel core logic as a plain-Python, unit-tested package.

Pure-Python twins of the rules the Databricks notebooks apply with Spark (11_dq_lib, 49_silver_lib, 50_silver_history):
the same contract semantics, fix steps, PII hashing/masking and SCD2 versioning, so they can be tested locally and in CI
without Spark. The notebooks remain the production implementation; the tests keep both in step.
"""
__version__ = "0.1.0"
