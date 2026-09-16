# funke task runner. Run `just --list` to see available recipes.

# Install the package in editable mode with test/dev extras.
dev-install:
    pip install --editable .[test]

# Install the package with test/dev extras.
install:
    pip install .[test]

# Regenerate the bundled HL7 schema JSON from the source XSDs.
build-schema:
    python scripts/build_hl7_schemas.py

# Run the test suite (from the repo root).
test: install
    pytest tests/

# Format Python code with black.
fmt:
    black src tests scripts resources

# Refresh the vendored copy of the pure-Python ADT engine bundled with the control-room app.
# (Databricks Apps can't reference the project wheel by path, so funke.demo is vendored.)
vendor-engine:
    rm -rf src/app/funke/demo
    mkdir -p src/app/funke/demo
    touch src/app/funke/__init__.py
    cp src/funke/demo/__init__.py src/funke/demo/adt.py src/funke/demo/volume.py src/funke/demo/facilities.py src/funke/demo/emr.py src/app/funke/demo/

# Build the control-room app: refresh the vendored engine and build the React frontend to
# src/app/frontend/dist. Run before `databricks bundle deploy`.
build-app: vendor-engine
    cd src/app/frontend && npm install && npm run build
