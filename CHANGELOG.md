# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Release notes are kept in sync with the in-app changelog (`threatatlas-app/frontend/src/data/changelog.json`).

## [0.6.1] - 2026-05-10

### Added

- New Diagram Wizard: replaced the simple 'New Diagram' button with a guided choice between starting from a blank canvas or importing an existing Draw.io (.drawio/.xml) file.

### Changed

- AI Threat Modeling Assistant: complete overhaul of the chat interface with rich markdown support (tables, fenced code blocks, blockquotes), real-time 'thinking' status updates, and improved proposal management (add/remove threats and mitigations).
- Diagram canvas performance: refined DiagramNode rendering and selection logic for smoother interaction on complex threat models.
- Product workflow: the Import Draw.io tool is now a first-class citizen of the product details page, accessible directly via the New Diagram wizard.
- AI Configuration: admin panel now supports more granular provider settings and improved credential management for OpenAI, Anthropic, and compatible providers.

### Fixed

- State synchronization in the Create Product wizard to ensure 'Additional details' are correctly persisted when toggled.

## [0.6.0] - 2026-04-29

### Added

- Single Sign-On via generic OIDC: works with Microsoft Entra ID, Okta, PingFederate, Keycloak / Red Hat SSO, Auth0, Google, and any OIDC-compliant provider.
- SSO providers are managed at runtime via User Management → SSO Providers — no redeploys or env-var edits needed. Client secrets are encrypted at rest (Fernet) using the app SECRET_KEY.
- Login screen auto-renders a button per enabled SSO provider; callback page finalizes the JWT handoff.
- Optional Discovery URL override per provider — enables split DNS setups (e.g. docker-net internal hostname for backchannel vs. public hostname in the issuer claim).
- Groups with role grants: create named groups that grant admin / standard / read_only, assign users, and a user's effective role is automatically the most permissive between their direct role and any group membership.
- Full SCIM 2.0 server at /scim/v2 (RFC 7643 / 7644): Users and Groups CRUD, discovery endpoints (ServiceProviderConfig, ResourceTypes, Schemas), filter parsing (eq), PATCH with add / replace / remove including member path filters (members[value eq "id"]).
- SCIM bearer tokens: admin-generated, SHA-256 hashed at rest, shown in plaintext exactly once. Full inbound provisioning from Keycloak (via the scim-for-keycloak extension), Okta, Entra ID, JumpCloud, Authentik, etc.
- Ready-to-run Keycloak 25 dev environment: pre-imported realm with a confidential client, two test users, OIDC correctly configured for the Docker network, and a pre-registered OIDC provider in ThreatAtlas.
- Documentation: docs/scim-keycloak.md walks through token generation, scim-for-keycloak setup, SCIM client configuration, and role-mapping workflow.
- Product optional metadata: project status (Design / Development / Testing / Deployment / Production), repository URL, Confluence URL, application URL, business area, owner name and email. Surfaced in the New Product wizard (collapsible "Additional details"), the Edit dialog, and the product details page with clickable links.
- Product downloads from the details page: Diagrams (JSON, re-importable), Threats & Mitigations (CSV), full Report (standalone print-friendly HTML), and an All-files ZIP bundle with a README.
- Description field on the Element Information panel — free-form notes per node (role, trust level, data handled, owners). Persisted with the diagram.
- Optional TLS overlay (docker-compose.tls.yml) — adds a Caddy 2 reverse proxy that terminates HTTPS on :443 with HTTP→HTTPS redirect on :80. Single Caddyfile supports three modes via the TLS_DIRECTIVE env var: self-signed (Caddy local CA — dev), mounted (drop your corporate-CA cert + key into ./certs/ — production), and Let's Encrypt (auto ACME — public deployments). Backend overrides set --proxy-headers and HTTPS-aware FRONTEND_URL/CORS_ORIGINS so OIDC, invitations and secure cookies behave correctly behind the proxy. Full walkthrough including how to import a corporate CA-signed certificate is in docs/tls.md.
- Seven new threat-modeling frameworks seeded: DREAD (5/5), VAST (8/8), OCTAVE (6/6), Trike (6/6), Attack Trees (8/8), Kill Chain (7/7), and MITRE ATT&CK (30 techniques across all 14 Enterprise tactics, 13 mitigations). Seeding is idempotent — existing installs pick up the new frameworks on restart.

### Changed

- User model: users.hashed_password is now nullable to support SSO-only accounts, and users.scim_external_id ties records back to the upstream IdP.
- RBAC permission checks (require_admin, require_standard_or_admin, resource access) now evaluate effective_role, so group-granted roles are honored everywhere.
- /auth/me now returns effective_role alongside the direct role, so the UI can reflect group-based elevation.
- SessionMiddleware wired into the app: required by Authlib for OIDC state/nonce and previously missing — OIDC flows now actually work end-to-end.
- Diagram editor: replaced the share-style icon on the per-diagram JSON export with a proper Download icon and tooltip ("Download (JSON)") for clarity.
- New Product wizard — "Select Frameworks" step is now scrollable (max-height) and includes a Select-all / Deselect-all toggle with a "{n} of {total} selected" counter. Needed since the default seed now has 11 frameworks.
- Product cards on the Products page show the project status (Design / Development / Testing / Deployment / Production) as a colored badge plus the business area as a neutral badge, matching the palette used on the product details page.

### Fixed

- Product downloads were saving with a generic "download" filename (interpreted by the OS as .txt). CORS middleware now exposes Content-Disposition so the browser hands the server-sent filename (e.g. Payment_Service-report.html) through to JS.

## [0.5.0] - 2026-04-28

### Added

- AI Threat Modeling Assistant: a conversational AI chat panel embedded in the diagram editor that performs deep, framework-exhaustive threat analysis across every element and data flow.
- AI-assisted diagram import: when importing a DrawIO file, the AI automatically classifies each element into the correct DFD type (process, datastore, external entity, data flow, trust boundary).
- DrawIO to DFD import: upload any .drawio or .xml file and convert it into a fully editable Data Flow Diagram with element type mapping.
- OWASP LLM Top 10 framework added to the knowledge base with threats and mitigations covering prompt injection, insecure output handling, training data poisoning, and more.
- AI configuration panel in Settings (admin only): configure provider (OpenAI, Anthropic, OpenAI-compatible), model, API key, temperature, and max tokens; API keys are stored encrypted.
- Streaming AI responses via Server-Sent Events for a real-time, token-by-token chat experience.
- AI proposal removal: the AI can propose removing outdated or duplicate threats and mitigations already on the diagram.

### Changed

- Diagram elements now show threat (T) and mitigation (M) count badges directly on the canvas for at-a-glance risk visibility.
- Version history now tracks threat and mitigation changes (added, removed, modified) in addition to diagram structure, with dedicated Threats and Mitigations diff tabs in the comparison view.
- Overall UI refresh: updated component styles, layout consistency, and visual hierarchy across the diagram editor, settings, and knowledge base pages.
- Conversation persistence: AI chat history is stored per diagram and restored across sessions.
- Redis-backed knowledge base cache: KB threats and mitigations are cached per framework to reduce database load during AI analysis.

## [0.4.0] - 2026-03-29

### Added

- Risk matrix (Likelihood × Impact heatmap) on the Analytics page and in the product-level Analytics tab.
- Expanded knowledge base to 7 frameworks (MITRE ATT&CK, CVSS Risk Framework, OWASP ASVS) with 200+ new threats and mitigations.
- Coverage chart in Knowledge Base showing threats vs mitigations per category.
- Toast notifications for all user actions across the application.
- Skeleton loading states and error boundaries on all pages.
- Product-level analytics tab with risk, threat, and mitigation charts.
- Shared ThreatCard component with compact mitigation chips and progress tracking.
- Smart mitigation search pre-filtered by threat framework and category.

### Changed

- Full UI redesign: Dashboard, ProductDetails, Login, and ThreatDetailsSheet with modern shadcn components.
- Theme management migrated to next-themes for proper dark mode and shadcn Sonner compatibility.
- Accessibility and responsive design audit: aria-labels, mobile breakpoints, and keyboard navigation.

### Fixed

- Dark mode toast styling and missing frameworks in new diagram dialog.
- Product sharing and visibility: public/private flag persisted correctly, access checks respect visibility, and the share dialog toggles visibility and collaborator management reliably.
- User invitations: accepting an invitation no longer fails with a server error when checking expiration (UTC-aware datetime handling).

## [0.3.0] - 2026-03-23

### Added

- Changelog page with interactive timeline view in the sidebar navigation.
- Analytics page with global threat statistics and charts.
- Comments on threats and mitigations.

## [0.2.0] - 2026-03-21

### Added

- User-specific ownership and access control: custom frameworks, threats, and mitigations are now scoped to their creator.
- Full screen mode to the diagram editor.
- Export diagram to JSON format.

### Changed

- All threats from different frameworks are now shown in ALL ANALYSES mode.
- History and version comparison feature improved in the diagram editor.
- Diagram node rendering refined: proper zIndex layering and improved element selection behavior.
- Access control layer enforced at both API and UI level for all user-owned resources.
- Diagram elements have four connection points instead of 2.

### Fixed

- Trust boundary layer overlapping while editing the boundaries.

## [0.1.0] - 2026-03-18

### Added

- Custom frameworks support: users can now create, edit, and manage their own threat/mitigation frameworks.
- Risk assessment fields on diagram threats: likelihood, impact, and computed risk score.
- Product collaborators: share products with other users and control their access level.
- Diagram versioning: snapshot and restore previous versions of a diagram's threat model.
- Threat-to-mitigation linking: mitigations can now be explicitly linked to specific threats in a diagram.
- RBAC (Role-Based Access Control) and invitation system for team collaboration.
- User authentication with JWT, password hashing, and admin/member roles.
- Threat modeling models (STRIDE, PASTA, LINDDUN, etc.) with framework associations.
- Initial project setup for ThreatAtlas OWASP project.
- Root project structure, GitHub issue and pull request templates.
- Backend FastAPI architecture with PostgreSQL integration and Alembic migrations.
- Frontend React + TypeScript application with ReactFlow for interactive diagram editing.
- Docker and Docker Compose support for easy local and production deployment.
- Core threat modeling features: Products, Data Flow Diagrams (DFDs).
- STRIDE and PASTA framework support out of the box.
- Knowledge Base page for browsing threats and mitigations by framework.
- Analytics dashboard with global threat statistics and charts.
- License updated to Apache 2.0.
