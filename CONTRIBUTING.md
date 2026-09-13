# Contributing to CanaryMesh

Thank you for your interest in contributing to CanaryMesh! We welcome contributions of all kinds, whether you are fixing a bug, improving documentation, or proposing new features.

---

## Code of Conduct

Please treat everyone in the community with respect, kindness, and constructive feedback. Open source thrives when developers collaborate positively.

---

## How to Contribute

### 1. Reporting Bugs & Requesting Features
- **Search existing issues** first to avoid duplicates.
- **For bugs:** Open an issue describing the bug, including steps to reproduce, expected vs. actual behavior, and environment details (OS, Python version).
- **For feature requests:** Describe the problem you are trying to solve and propose a solution or architecture pattern.

### 2. Pull Request Workflow

1. **Fork the repository** and clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/canarymesh.git
   cd canarymesh
   ```

2. **Create a topic branch** from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   # or: git checkout -b fix/issue-description
   ```

3. **Follow commit conventions:** We follow [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: add latency threshold trigger to health checker`
   - `fix: resolve race condition in probe coordinator`
   - `docs: update architecture diagrams in README`
   - `perf: optimize async socket polling loop`

4. **Ensure code quality:**
   - Keep code clean, readable, and strictly typed.
   - Verify that all existing and new unit tests pass before submitting.
   - Run the local linter and formatter.

5. **Push and open a Pull Request:**
   - Push your branch to your fork:
     ```bash
     git push origin feat/your-feature-name
     ```
   - Open a Pull Request against the `main` branch.
   - Provide a clear PR title and description outlining the changes made and referencing any related issues (e.g., `Closes #12`).

---

## Development Setup

CanaryMesh requires Python 3.12+ and uses `uv` for fast, reproducible dependency management.

1. **Clone the repository and set up a virtual environment:**
   ```bash
   git clone https://github.com/alexandrmotologa/canarymesh.git
   cd canarymesh
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   uv pip install -e ".[dev]"
   ```

2. **Run tests:**
   ```bash
   pytest -v
   ```

3. **Run code quality & linting checks:**
   ```bash
   ruff check .
   ruff format --check .
   ```

Refer to the **Quick Start** section in [README.md](README.md) for full configuration details and architecture diagrams.

---

## Questions & Discussions

If you have questions about architecture decisions or need guidance before submitting a large change, feel free to open a Discussion or an Issue with the `question` label.
