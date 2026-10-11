# AstraCode development rules

## Required documentation maintenance

For every development-related change in this directory—feature work, refactoring, bug fixes, protocol changes, UI changes, tests, migrations, or dependency/configuration changes—the developer or AI must update both documents before considering the task complete:

1. `docs/project_docs/product/PRODUCT_DESIGN.md`: update intended behavior, user-facing capability, status, boundaries, and roadmap.
2. `docs/project_docs/product/PRODUCT_DEVELOPMENT.md`: record implementation details, files/modules affected, incidents or trade-offs, tests performed, and remaining technical debt.

If the change uses a real model/provider, add or update a dated test report under `docs/project_docs/testing/` and keep redacted machine-readable evidence under `docs/project_docs/testing/evidence/`.

Never write API keys, authorization headers, hidden reasoning, or sensitive workspace contents into documentation or evidence.
