{
  description = "TaskIQ development environment with Python 3.13";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python313;
        pythonPackages = pkgs.python313Packages;

        # Common dev dependencies
        devDeps = with pythonPackages; [
          pytest
          pytest-cov
          pytest-xdist
          pytest-asyncio
          freezegun
          polyfactory

          # Type checking
          mypy
          mypy-extensions
          types-requests

          # Linting and formatting
          ruff
          black

          # Test utilities
          opentelemetry-test-utils
        ];

        # TaskIQ runtime dependencies
        runtimeDeps = with pythonPackages; [
          pydantic
          pycron
          taskiq-dependencies
          anyio
          packaging
          izulu
          aiohttp
          pytz
        ];

      in {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pkgs.uv # Modern Python package manager
            pkgs.git
            pkgs.gh # GitHub CLI
            pkgs.pre-commit
          ];

          shellHook = ''
            # Create a virtual environment if it doesn't exist
            if [ ! -d .venv ]; then
              echo "Creating virtual environment with Python 3.13..."
              ${python.interpreter} -m venv .venv
            fi

            # Activate virtual environment
            source .venv/bin/activate

            # Install dependencies using uv (faster than pip)
            echo "Installing dependencies..."

            # Use pip for editable install (uv_build doesn't work on NixOS)
            # Patch pyproject.toml to use setuptools instead
            if [ -f pyproject.toml.bak ]; then
              echo "Restoring original pyproject.toml..."
              mv pyproject.toml.bak pyproject.toml
            fi

            cp pyproject.toml pyproject.toml.bak
            sed -i 's/build-backend = "uv_build"/build-backend = "setuptools.build_meta"/' pyproject.toml
            sed -i 's/uv_build>=0.9.16,<0.10.0/setuptools>=70.0.0/' pyproject.toml

            pip install -e ".[dev,zuv,reload,metrics,orjson,msgpack,cbor,opentelemetry]"

            # Restore original pyproject.toml
            mv pyproject.toml.bak pyproject.toml

            echo ""
            echo "✅ TaskIQ development environment ready!"
            echo "Python version: $(python --version)"
            echo "Virtual environment: $(which python)"
            echo ""
            echo "Available commands:"
            echo "  python -c 'from taskiq.cli.worker.health_checker import HealthChecker' - Test import"
            echo "  python -c 'from taskiq.cli.worker.run import start_listen' - Test import"
            echo "  pytest tests/cli/worker/test_health_checker.py - Run health checker tests"
            echo ""
          '';
        };
      });
}
