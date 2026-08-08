# ResearchOps Product Benchmark

Generated: `2026-08-06T05:29:20+00:00`  
Suite: `researchops-product-benchmark-v1`

This report measures deterministic local product behavior. It does not by itself prove superior research quality against third-party products.

## Summary

| Tool | Checks (covered) | Coverage | Existing files preserved | Host-root files added | Intake mode | Dashboard start | Memory lifecycle |
|---|---:|---:|---:|---:|---|---|---|
| ResearchOps 2.1.0 | 19/19 | 100% | 100% | 0 | adopt | yes | 8/8 |
| ResearchOps 2.0.0 | 3/18 | 95% | 100% | 7 | — | no | 0/8 |

## Candidate checks

- [x] `preserves_existing_files`
- [x] `avoids_host_root_pollution`
- [x] `records_adoption_mode`
- [x] `infers_non_charter_phase`
- [x] `single_hidden_root`
- [x] `dashboard_ready`
- [x] `dashboard_quick_start`
- [x] `dashboard_process_cleanup`
- [x] `dashboard_shows_intake`
- [x] `dashboard_shows_memory`
- [x] `memory_deduplicates`
- [x] `memory_supersedes`
- [x] `memory_scope_isolation`
- [x] `memory_has_provenance`
- [x] `memory_context_bundle`
- [x] `memory_sync_idempotent`
- [x] `memory_temporal_validity`
- [x] `memory_superseded_excluded`
- [x] `memory_four_layer_coverage`

## Interpretation boundary

- The fixture represents adopting a non-empty software/research repository.
- Latencies are local-process measurements and should not be compared across machines.
- Third-party observability, research-agent, or memory products need adapters, equivalent data, and their own configured services before head-to-head claims are valid.
- Product usability should additionally be evaluated with user studies and longitudinal project outcomes.
