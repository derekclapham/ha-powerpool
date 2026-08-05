# Security

This integration handles a credential and reports on money. It runs inside Home
Assistant with the same privileges as everything else there, and it is installed
by people who will never read its source. That combination sets the bar for how
it is written.

This document describes the principles it is held to and the mechanisms that
enforce them. It is not a changelog — the commit history covers what changed and
when.

## Reporting a vulnerability

**Please report privately, not in a public issue.**

Use [GitHub's private vulnerability reporting][advisory] on this repository. That
opens a channel visible only to you and the maintainer, and it is the fastest
route to a fix.

[advisory]: https://github.com/derekclapham/ha-powerpool/security/advisories/new

Useful things to include: what an attacker has to control to reach the problem
(a compromised pool, a network position, an installed integration, physical
access), what they get out of it, and a payload or sequence that demonstrates it.
A proof of concept is welcome but not required — a clear description of the
mechanism is enough.

This is a single-maintainer hobby project. There is no bounty and no guaranteed
response time, but security reports are prioritised over everything else, and you
will get an acknowledgement. Please give a reasonable window for a fix before
disclosing publicly. Credit is offered in the advisory unless you prefer
otherwise.

Only the latest release is supported. Fixes ship in a new version rather than as
patches to older ones.

## What this integration is trusted with

Three things, in rough order of how much damage their loss would do:

1. **A PowerPool API key.** It is a credential, and it is the one thing here an
   attacker would want.
2. **A picture of your mining income.** Hashrate, share quality, unpaid balances,
   payout amounts, payout timestamps and transaction ids. Individually dull;
   together, a profile of the money.
3. **Standing in your Home Assistant instance.** Anything it does badly — burning
   memory, filling the entity registry, corrupting recorded statistics — lands on
   the whole instance, not just on itself.

### Why crypto changes the calculus

Two things are different from a typical sensor integration.

**Financial data is deanonymising, and permanently so.** A payout amount and the
time it landed can be searched against a public block explorer to find the
transaction, and from there the wallet address and its whole history. This is not
theoretical and it does not expire — a value leaked today is still searchable in
ten years. So exact amounts are treated as identifying data in their own right,
alongside the addresses and transaction ids they would lead to. That is why the
diagnostics download redacts amounts and balances, not just the obvious
identifiers.

**People targeting cryptocurrency are motivated and technical.** A hashrate
readout also tells an observer the scale of your operation, which is targeting
information of a different kind. Data minimisation here is not a formality.

### What a leaked API key cannot do

PowerPool's API is read-only. There is no endpoint to change a payout address,
move a balance, or reconfigure mining, and this integration only ever issues
`GET` requests — it registers no services, exposes no buttons or switches, and
has no code path that writes anything to the pool.

So the realistic worst case for a leaked key is disclosure: someone learns what
you earn and can correlate it on-chain. That is bad, and worth preventing. It is
not loss of funds. Both halves of that sentence matter — the first is why the key
is handled carefully, the second is why you should not panic if one leaks. Rotate
it (changing your PowerPool password resets it) and move on.

## Principles

### 1. The pool is not trusted

Everything arriving from the API is treated as hostile input, because a
compromised pool, a hijacked DNS record or an intercepting proxy all produce the
same thing: attacker-chosen JSON delivered to code running inside your home.

Concretely, the parsing layer assumes the response is trying to break it:

- **Every collection is bounded on ingest.** Workers, algorithms, payments,
  balances and distinct payout coins all have ceilings, applied where the data
  enters rather than where it is used. Each worker becomes a device carrying
  several entities, written to Home Assistant's registries and persisted to disk
  — so an unbounded list is not a slow poll, it is durable damage that survives
  restarts. Limits are set far above any real mining operation, and they compose:
  a per-item cap that multiplies by another cap is not a cap.
- **Every number must be finite.** `Infinity` and `NaN` are refused at the JSON
  layer, individual values are clamped to a plausible ceiling, and every derived
  sum, average and percentage is re-checked before it becomes a sensor reading.
  Home Assistant rejects a non-finite state in a way that leaves the entity
  frozen at its last good value rather than unavailable — a sensor that lies
  quietly is worse than one that admits it is broken.
- **Every string is sanitised.** Names from the API become device names, parts of
  entity identifiers, and text in log lines. Control, format and surrogate
  characters are stripped — these carry terminal escape sequences that rewrite
  the screen of anyone tailing the log, newlines that forge log entries, and
  direction overrides that make a name display as something it is not. Delimiter
  characters are removed so a name cannot forge an identifier belonging to
  another device. Lengths are capped.
- **Every response is bounded in size.** Bodies are read in chunks against a
  ceiling and refused past it, without trusting a `Content-Length` the server is
  free to misstate. Compressed responses are decompressed without any ratio
  limit by the HTTP layer, so a small reply can expand to hundreds of megabytes
  and exhaust a small Home Assistant host.
- **Nothing structural is inferred from the payload.** A missing or reshaped
  field yields a null reading, not an exception. An unparseable response fails
  the update cleanly and marks entities unavailable with a reason.

### 2. The credential is handled as one

- It is entered in a masked field and stored only in Home Assistant's own config
  entry storage — the same place every other integration keeps its secrets. It is
  never written to a separate file, an environment variable, or an option.
- It is **scrubbed from every error message this integration produces**, in raw
  *and* percent-encoded form. The key travels in a query string, and HTTP client
  errors stringify to include the request URL, so a naive substring match misses
  the encoded spelling entirely while a reader can simply decode it.
- Error messages are built from the status code rather than from the underlying
  exception, and the original exception is deliberately not chained, so no
  handler that logs a traceback can recover the URL.
- It never appears in the diagnostics download, and never in the config flow's
  user-facing text.
- One residual is worth stating plainly: the API carries the key in the query
  string, which is the pool's design and not something this integration can
  change. If you enable debug logging for the underlying HTTP client, Home
  Assistant will log full request URLs including the key. Treat such logs as
  secret.

### 3. Minimum surface

- **No third-party runtime dependencies.** The integration declares none, so
  installing it adds no packages to your Home Assistant environment and no
  supply chain beyond this repository.
- **One endpoint, fixed at compile time.** The base URL is a constant, HTTPS, and
  not user-configurable. There is nowhere to point this at an arbitrary host, so
  it cannot be used to reach your internal network.
- **Redirects are not followed.** The API has no legitimate reason to redirect,
  and following one would let a response choose the next host to be contacted.
- **Read-only, all the way down.** `GET` requests only, no services, no
  controllable entities.
- **No `eval`, no dynamic imports, no deserialisation of anything but JSON**, and
  no filesystem access.

### 4. Data minimisation in what is shared

The diagnostics download is designed to be pasted into a public issue, so it
assumes an untrusted reader. The API key, username, payout addresses, transaction
ids, worker names, payout amounts and balances are all redacted. Timestamps,
tickers, counts and rates remain, because they are what makes a diagnostics file
useful and are far weaker in isolation.

Worker names are redacted too — they are user-chosen and routinely name a site,
a room, or a piece of hardware.

### 5. The release pipeline is part of the product

Users install a zip built by CI and run it with full Home Assistant privileges.
The pipeline is therefore treated as production code:

- Values that an author controls — notably the release tag — are passed to build
  scripts as environment variables, never interpolated into a shell command.
  GitHub substitutes template expressions before the shell parses the line, so
  quoting does not contain them, and git permits shell metacharacters in tag
  names.
- The release job refuses to build from anything that is not a plain semantic
  version tag.
- Git credentials are dropped immediately after checkout, since nothing later in
  the build needs them.
- Concurrent publishes of the same tag are serialised, so two overlapping runs
  cannot interleave and leave the wrong artifact attached.
- A `SHA256SUMS` file is published beside the zip, so a later substitution of the
  asset can be detected rather than merely suspected.
- The validation workflow declares read-only permissions explicitly rather than
  inheriting a default that could be widened later. Pull requests from forks run
  without access to any secret, and the repository holds none.

### 6. Findings are proven, then pinned

Two working rules, because both failure modes have bitten this project:

**A vulnerability is reproduced before it is fixed.** Plausible-sounding analysis
is not evidence. Every security change here started with a payload or a request
that demonstrably caused the bad outcome, and finished by replaying it. One
carefully argued finding did not survive that test and was correctly not "fixed".

**A hardening change is re-tested against benign input.** Tightening a limit is
an easy way to silently break the normal path. At least one fix here did exactly
that and was caught only because the ordinary case was re-checked afterwards.

Each confirmed issue leaves behind a regression test that reproduces the original
attack, so a later refactor cannot quietly reopen it.

## Scope

**In scope:** anything in this repository — the integration, its release
workflows, and its published artifacts.

**Out of scope**, though still worth telling us about if the interaction is
interesting:

- Vulnerabilities in Home Assistant itself. Report those to the
  [Home Assistant security team](https://www.home-assistant.io/security/).
- Vulnerabilities in PowerPool's API or website. Report those to PowerPool.
- Attacks that require an attacker to already have arbitrary code execution on
  the Home Assistant host or access to its storage. At that point the API key is
  the least of the problems.

## What this cannot protect you from

Stated plainly, because a security document that implies more than it delivers is
itself a hazard:

- **Home Assistant's own trust model.** Any integration you install can read this
  one's stored credential. Integrations are not sandboxed from one another. Only
  install code you are willing to extend that trust to — including this.
- **Your own instance's exposure.** If your Home Assistant is reachable from the
  internet without authentication, nothing here helps.
- **The pool having your data.** PowerPool knows your addresses, payouts and
  hashrate regardless of this integration. This only governs what reaches your
  logs, your database and anything you share.
- **A compromised maintainer account.** The pipeline hardening raises the cost of
  an accidental or opportunistic compromise; it does not defend against someone
  who controls the account that signs releases.
