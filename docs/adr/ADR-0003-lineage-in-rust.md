# ADR-0003: Lineage Chaining in Rust (Atomic With Gate Result)
**Status:** Accepted | **Vector:** Safety
No gap between gate result and chain write. Blocked actions chained too.
**Invariant:** Every transaction — approved or blocked — must be chained.
