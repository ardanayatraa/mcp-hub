# Laravel connector simulation

2026-10-28: Postman CLI 1.80.0 served the local Hub protocol mock on 18130.

Start from the repository root with the simulation command in the package README.
Set MCP_HUB_SIM_URL=http://127.0.0.1:18130/hub/mcp when running HubSimulationTest.

The mock models the repository-owned Hub tools/list response. It validates the
dummy bearer token, origin and JSON-RPC metadata, and echoes the actual request ID.
The PHP HubClient ran over actual HTTP and received the expected empty tool catalog.
The Hub member received a POST to /mcp through the simulation route prefix.

A valid config.yaml requires version: 1 and an explicit default scenario.
The initial missing-version manifest was rejected before the simulation started.
The normal sandbox source URL differs from the mock's test origin; use the test's
configuration rather than treating the ordinary sandbox doctor as a mock check.

This proves transport wiring against this stand-in. The separate source verifier
checks the PHP source against the actual Python manifest validator; neither run
proves provider completions, Hub pairing, production use, or untested Laravel majors.
