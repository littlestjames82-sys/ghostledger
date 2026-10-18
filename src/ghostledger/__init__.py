"""GhostLedger: local token and cost ledger for GhostSlice.

Zero-dependency Python stdlib only. Local only, no network.
All dollar figures are ESTIMATES from a local dated price table,
never billed amounts and never live prices. API keys are never
stored or logged: importers drop credential-named fields on sight.
"""

__version__ = "0.1.0"
LOOP_THRESHOLD = 3.0
