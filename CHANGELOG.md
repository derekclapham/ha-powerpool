# Changelog

All notable changes to this integration are documented here.

## [0.1.0] - Unreleased

Initial release.

### Features
- UI config flow that takes only an API key and derives the account username from the API response
- Support for several PowerPool accounts, one config entry per API key
- Reauthentication flow for when a PowerPool password change resets the API key
- Per-algorithm devices covering whatever the account reports, with per-worker devices nested underneath
- Account sensors for unpaid balance, last payout amount and time, and lifetime payouts, per coin
- Algorithm and worker sensors for hashrate, rolling-average hashrate, accepted and rejected shares, share efficiency, blocks found and estimated 24-hour revenue
- Binary sensors for account mining state and per-worker online state
- Configurable poll interval via the options flow

### Internal
- Hashrates normalised to base units on ingest and rendered in a unit fixed per algorithm, so a changing source unit cannot break long-term statistics
- API keys scrubbed from error messages and redacted from diagnostics
- Empty API responses tolerated for a few polls before triggering reauthentication, since PowerPool signals a rejected key with `200 {}` rather than an HTTP error
- A response that no longer carries the configured username fails the update instead of parsing into an empty account, so a renamed account surfaces as unavailable entities rather than silent blanks
