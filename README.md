# PowerPool for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/derekclapham/ha-powerpool/actions/workflows/validate.yaml/badge.svg)](https://github.com/derekclapham/ha-powerpool/actions/workflows/validate.yaml)

A Home Assistant integration for [PowerPool](https://powerpool.io) — the multi-algorithm mining pool. Connect your account with an API key and get native sensors for hashrate, workers, share quality, estimated revenue, unpaid balances and payouts.

Everything is read-only: PowerPool's API cannot change your mining setup, and neither can this integration.

## Features

- 🔑 **UI config flow** — paste an API key, and pick an account only if that key covers more than one. Your username is read from the account automatically, so there is no field to mistype and no YAML.
- 👥 **Multiple accounts** — add the integration once per account. Each becomes its own device tree and polls independently.
- ⛏️ **Every algorithm you mine** — SHA-256, Scrypt, kHeavyHash, Eaglesong, Etchash, X11, Blake2s and Equihash each get their own device, created from whatever your account actually reports.
- 🖥️ **Per-worker detail** — each rig gets a device with its own hashrate, share counts and online state, so you can alert on a single miner dropping out.
- 📈 **Stable units for long-term statistics** — PowerPool reports a hashrate as a number plus a unit that changes with magnitude (`980 GH/s` one poll, `1.1 TH/s` the next). Every reading is normalised on ingest and displayed in a unit fixed per algorithm, so history and charts stay continuous.
- 💰 **Balances and payouts** — unpaid balance, last payout amount and time, and a lifetime total, per coin.
- 🔒 **Credential hygiene** — the API key is stored as a password field, scrubbed from any error that reaches the log, and redacted from diagnostics downloads.

## Requirements

- Home Assistant **2025.3** or newer (the entity platforms use `AddConfigEntryEntitiesCallback`, which does not exist before 2025.3).
- A [PowerPool](https://powerpool.io) mining account.
- Your account's **API key**, found on the PowerPool dashboard.

> **Note:** changing your PowerPool password resets the API key. When that happens the integration notices, marks the account as needing attention and prompts you for the new key — no need to remove and re-add it.

## Installation

### HACS (custom repository)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/derekclapham/ha-powerpool` with category **Integration**.
3. Download **PowerPool**, then restart Home Assistant.

### Manual

Copy `custom_components/powerpool` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → PowerPool**, then paste your API key.

If the key unlocks more than one account you will be asked which one to add. To add the others, run the same flow again and pick the next.

### Adding a second account

Run **Add Integration → PowerPool** again and paste the key for that account — or the same key again, then pick the next account from the list. Accounts are keyed by username, so the same account cannot be added twice, and each entry keeps its own poll timer, devices and history.

### Options

**Configure** on the integration entry exposes the poll interval — default 300 seconds, adjustable between 60 and 3600 in steps of 30. PowerPool's figures are rolling averages, so polling faster than a minute adds load without adding detail.

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
| `<COIN>` balance | Unpaid balance, one sensor per payout coin the API reports; coins you have never held are created disabled |
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
| Accepted / rejected / stale shares | Summed across the account's rigs |
| Share efficiency | Accepted shares as a percentage of every share submitted, counting rejects and stales — a good health signal |

### Worker

| Entity | Notes |
| --- | --- |
| Hashrate / Hashrate (average) | Same fixed unit as its algorithm |
| Accepted / rejected / stale shares | This rig only |
| Share efficiency | This rig only |
| Blocks credited | Blocks the pool credits to this rig — **not** Bitcoin blocks, see below |
| Online | On while the rig reports a non-zero hashrate |

## Behaviour worth knowing

**"Blocks credited" is not a count of Bitcoin blocks.** PowerPool switches between many SHA-256 coins and merge-mines alongside them, so a rig is credited with blocks on chains whose difficulty is orders of magnitude below Bitcoin's. Treat the figure as a curiosity rather than an earnings signal: the pool pays RTPPS (real-time pay-per-share), so payouts follow accepted shares and hashrate whether or not a block is ever found. If you want numbers that track income, watch **hashrate**, **share efficiency** and **estimated revenue**.

**Only what you actually mine gets entities.** PowerPool returns every algorithm and payout coin it supports on every account, nearly all of them permanently zero — left alone that is around a hundred entities for a single-rig account. Algorithms you do not mine are skipped entirely, since each one would otherwise add an empty device. Coins you have never held live on the existing account device, so they *are* created but arrive switched off: the account device page lists its disabled entities, and you can enable any you want to watch.

**New rigs, algorithms and coins need a reload.** Devices and entities are created from what the account reports when the entry loads. Point a new rig at the pool, start mining an algorithm you did not before, or take a first payout in a new coin, and those entities appear after you reload the integration entry (**⋮ → Reload**). Everything already present needs nothing.

**A rig that disappears goes unavailable, not missing.** If a miner is unplugged or reboots, PowerPool stops listing it and its entities become unavailable — they are never removed, so history survives. `Online` turning *off* means something different: the rig is still known to the pool but has fallen to zero hashrate. When a rig is gone for good, its device can be deleted from the device page; devices the account still reports refuse deletion, so a rig that is merely powered off is safe.

**Share totals are per rig, not per account, for long-term statistics.** The account-wide accepted/rejected/stale figures are sums over the rigs currently being reported, so they step down whenever one drops out or the pool resets its counter. Recording that as an ever-increasing total would corrupt the statistics, so those three carry no state class and are there for at-a-glance reading. The per-worker equivalents are proper counters and are what long-term statistics and energy-style charts should use.

**A renamed account is reported, not silently blanked.** PowerPool keys its response by username. If the account is renamed the entry stops matching, and rather than reporting a successful poll full of empty readings, the integration fails the update and names what the API returned instead — so the entities go unavailable with a reason in the log.

**Rejected keys are detected, not guessed at.** PowerPool answers a bad API key with an empty `200` response rather than an HTTP error, which is also what a server-side blip would look like. An account that has been polling happily is given a few consecutive rejections before the integration concludes the key is dead and asks you to re-enter it. The very first poll after setup is treated strictly, so a key that is already dead prompts you straight away instead of retrying forever.

## Not included yet

- Pool-wide public statistics (`/api/pool`) — pool hashrate, miner counts, block counts and pay rates.
- Backfilling the account's earnings history into long-term statistics.

## Credits

Built against PowerPool's [public API documentation](https://powerpool.io/api). Not affiliated with or endorsed by PowerPool.

## License

MIT — see [LICENSE](LICENSE).
