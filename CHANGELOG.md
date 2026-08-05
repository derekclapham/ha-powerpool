# Changelog

All notable changes to this integration are documented here.

## [0.1.0] - 2026-08-05

Initial release. Requires Home Assistant 2025.3 or newer.

### Features
- UI config flow that takes an API key and derives the account username from the API response, with a picker when one key unlocks several accounts
- Support for several PowerPool accounts, one config entry per account
- Reauthentication flow for when a PowerPool password change resets the API key, guarded so that pasting a different account's key cannot silently repoint an entry
- Per-algorithm devices covering whatever the account reports, with per-worker devices nested underneath
- Account sensors for unpaid balance, last payout amount and time, and lifetime payouts, per coin
- Algorithm and worker sensors for hashrate, rolling-average hashrate, accepted, rejected and stale shares, share efficiency, blocks credited and estimated 24-hour revenue
- Binary sensors for account mining state and per-worker online state
- Configurable poll interval via the options flow
- Diagnostics download, with the API key, username, payout addresses, transaction ids and worker names redacted

### Notes on the API
PowerPool's published documentation is incomplete, so a few behaviours were established against a live account:

- The payout transaction id arrives as `txid`, not the documented `txID`; both are accepted
- Workers report an undocumented `stale_shares` count, which is surfaced and counted against share efficiency so late work is not treated as accepted
- A rejected key returns `200 {}` rather than an HTTP error, so an established account is given several consecutive rejections before reauthentication is triggered — while the first poll after setup is treated strictly
- Every supported algorithm and payout coin is returned on every account regardless of use, so unmined algorithms are skipped and never-held coins are created disabled

### Internal
- Hashrates normalised to base units on ingest and rendered in a unit fixed per algorithm, so a changing source unit cannot break long-term statistics
- API keys scrubbed from any error message that can reach the log
- Account, algorithm and worker devices registered parents-first during setup, rather than letting each platform create them in load order and reference a `via_device` that does not exist yet
- A response that no longer carries the configured username fails the update instead of parsing into an empty account, so a renamed account surfaces as unavailable entities rather than silent blanks
