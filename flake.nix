{
  description = "nixos.se: homepage and RSS feed for the Stockholm NixOS meetup group";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      # Matches the environments uv resolves for in pyproject.toml.
      forAllSystems = lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      editableOverlay = workspace.mkEditablePyprojectOverlay {
        root = "$REPO_ROOT";
      };

      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3;
        in
        (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope
          (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.wheel
              overlay
            ]
          )
      );

    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          venv = pythonSets.${system}.mkVirtualEnv "meet-env" workspace.deps.default;
        in
        rec {
          default = site;
          site = pkgs.callPackage ./default.nix { inherit venv; };
          inherit venv;
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonSet = pythonSets.${system}.overrideScope editableOverlay;
          virtualenv = pythonSet.mkVirtualEnv "meet-dev-env" workspace.deps.all;
        in
        {
          default = pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
              pkgs.tailwindcss_4
            ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          lintEnv = pythonSets.${system}.mkVirtualEnv "meet-lint-env" workspace.deps.all;
          # The generator and its tool configuration, without the site content.
          pythonSource = lib.fileset.toSource {
            root = ./.;
            fileset = lib.fileset.unions [
              ./src
              ./pyproject.toml
            ];
          };
        in
        {
          site = self.packages.${system}.site;

          lint =
            pkgs.runCommand "meet-lint"
              {
                nativeBuildInputs = [ lintEnv ];
              }
              ''
                cd ${pythonSource}
                ruff check --no-cache .
                ruff format --check --no-cache .
                touch "$out"
              '';

          types =
            pkgs.runCommand "meet-types"
              {
                nativeBuildInputs = [ lintEnv ];
              }
              ''
                cd ${pythonSource}
                export MYPY_CACHE_DIR="$TMPDIR/mypy"
                mypy
                touch "$out"
              '';
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);
    };
}
