# p2pKanban v1.0.0-beta.13

Recovery release for a legacy Docker deployment.

- Adopts the running beta.10 stack without restarting containers.
- Preserves the web port, PostgreSQL data and deployment secrets volumes.
- Moves the controller from `UserTestSpace` into a durable runtime root.
- Restores the GitHub update banner and UI update on the current web port.

Apply through the devctl patch. Full notes:
`docs/product/v1.0.0-beta.13-release-notes.md`.
