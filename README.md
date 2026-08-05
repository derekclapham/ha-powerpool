# PowerPool for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/derekclapham/ha-powerpool/actions/workflows/validate.yaml/badge.svg)](https://github.com/derekclapham/ha-powerpool/actions/workflows/validate.yaml)

A Home Assistant integration for [PowerPool](https://powerpool.io) — the multi-algorithm mining pool. Connect your account with an API key and get native sensors for hashrate, workers, share quality, estimated revenue, unpaid balances and payouts.

Everything is read-only: PowerPool's API cannot change your mining setup, and neither can this integration.

## Features

- 🔑 **UI config flow** — paste an API key, nothing else. Your username is read from the account automatically, so there is no field to mistype and no YAML.
- 👥 **Multiple accounts** — add the integration once per API key. Each account becomes its own device tree and polls independently.
- ⛏️ **Every algorithm you mine** — SHA-256, Scrypt, kHeavyHash, Eaglesong, Etchash, X11, Blake2s and Equihash each get their own device, created from whatever your account actually reports.
- 🖥️ **Per-worker detail** — each rig gets a device with its own hashrate, share counts and online state, so you can alert on a single miner dropping out.
- 📈 **Stable units for long-term statistics** — PowerPool reports a hashrate as a number plus a unit that changes with magnitude (`980 GH/s` one poll, `1.1 TH/s` the next). Every reading is normalised on ingest and displayed in a unit fixed per algorithm, so history and charts stay continuous.
- 💰 **Balances and payouts** — unpaid balance, last payout amount and time, and a lifetime total, per coin.
- 🔒 **Credential hygiene** — the API key is stored as a password field, scrubbed from any error that reaches the log, and redacted from diagnostics downloads.

## Requirements

- Home Assistant **2025.1** or newer.
- A [PowerPool](https://powerpool.io) mining account.
- Your account's **API key**, found on the PowerPool dashboard.

> **Note:** changing your PowerPool password resets the API key. When that happens the integration notices, marks the account as needing attention and prompts you for the new key — no need to remove and re-add it.

## Installation

### HACS (custom repository)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/derekclapham/ha-powerpool` with category **Integration**.
3. Install **PowerPool**, then restart Home Assistant.

### Manual

Copy `custom_components/powerpool` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → PowerPool**, then paste your API key.

If the key unlocks more than one account you will be asked which one to add. To add the others, run the same flow again and pick the next.

### Adding a second account

Run **Add Integration → PowerPool** again and paste that account's API key. Accounts are keyed by username, so the same account cannot be added twice, and each entry keeps its own poll timer, devices and history.

### Options

**Configure** on the integration entry exposes the poll interval (default 300 seconds, minimum 60). PowerPool's figures are rolling averages, so polling faster than a minute adds load without adding detail.

## Devices and entities

Each account creates a three-tier device tree:

```
PowerPool <account>                      balances, payouts, mining state
  └─ PowerPool <account> <algorithm>     per-algorithm totals
       └─ PowerPool <account> <worker>   one physical rig
```

Devices can be renamed in Home Assistant if you want shorter entity IDs — renaming a device renames its entities with it.

### Account

| Entity | Notes |
| --- | --- |
| `<COIN>` balance | Unpaid balance, one sensor per coin your account holds |
| `<COIN>` total paid | Lifetime payouts, as far back as the API reports |
| `<COIN>` last payout | Amount of the most recent payout; the transaction ID is an attribute |
| `<COIN>` last payout time | Renders as "x hours ago" |
| Mining | On while any rig on the account is hashing |

### Algorithm

| Entity | Notes |
| --- | --- |
| Hashrate | Current, in a unit fixed for the algorithm |
| Hashrate (average) | The pool's rolling average |
| Estimated revenue (24h) | PowerPool's own USD projection |
| Workers online | Rigs currently submitting work |
| Accepted / rejected shares | Summed across the account's rigs |
| Share efficiency | Accepted shares as a percentage of all shares — a good health signal |

### Worker

| Entity | Notes |
| --- | --- |
| Hashrate / Hashrate (average) | Same fixed unit as its algorithm |
| Accepted / rejected shares | This rig only |
| Share efficiency | This rig only |
| Blocks found | Blocks this rig has been credited with |
| Online | On while the rig reports a non-zero hashrate |

## Behaviour worth knowing

**New workers need a reload.** Devices and entities are created from what the account reports when the entry loads. Point a new rig at the pool and it appears after you reload the integration entry (**⋮ → Reload**). Existing rigs need nothing.

**A rig that disappears goes unavailable, not missing.** If a miner is unplugged or reboots, PowerPool stops listing it and its entities become unavailable — they are never removed, so history survives. `Online` turning *off* means something different: the rig is still known to the pool but has fallen to zero hashrate.

**Rejected keys are detected, not guessed at.** PowerPool answers a bad API key with an empty `200` response rather than an HTTP error, which is also what a server-side blip would look like. An account that has been polling happily is given a few consecutive empty responses before the integration concludes the key is dead and asks you to re-enter it.

## Not included yet

- Pool-wide public statistics (`/api/pool`) — pool hashrate, miner counts, block counts and pay rates.
- Backfilling the account's earnings history into long-term statistics.
- Brand icons and logos.

## Credits

Built against PowerPool's [public API documentation](https://powerpool.io/api). Not affiliated with or endorsed by PowerPool.

## License

MIT — see [LICENSE](LICENSE).
