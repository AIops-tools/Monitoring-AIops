# Release notes — monitoring-aiops 0.4.1

Previous release: 0.4.0.

## Fixed: `topn` reported a failed query as "no nodes under load"

It swallowed every exception and returned an empty list. A failed SWQL query and
"nothing is hot right now" are **opposite findings**, and rendering them identically
is exactly the kind of misreport this line exists to prevent.

**BREAKING** — `topn` now returns an envelope:
`{"nodes": [...], "returned": N, "metric": str, "error": str | None}`.

`noc_rollup` keeps its shape — `topCpu` is still the node list — but gained
`topCpuError`, so a failed sub-query is not shown as an empty top-3 in the one-shot
glance. Its SWQL call order is unchanged.
