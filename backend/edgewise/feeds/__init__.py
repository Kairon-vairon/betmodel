"""Data feeds (Milestone 2): fixtures and results, bookmaker odds, Betfair Exchange prices.

Each client turns a provider's response into plain Edgewise records. Nothing here touches
the database; services/ingest.py stores what the clients return. Bookmaker prices come
only from the licensed odds feed: no bookmaker website is ever scraped (CLAUDE.md rule 2).
"""
