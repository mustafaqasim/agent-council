# Migration

Version 0.2.0 establishes the public `agent-council.*` schema namespace and neutral runtime file names.

Cases created by earlier private package versions are intentionally not mutable with this package. Their pinned files, event hashes, and receipts remain authoritative only under the package that created them. Create a new public case instead of rewriting historical evidence.
