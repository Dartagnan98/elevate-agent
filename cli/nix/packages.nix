# nix/packages.nix — Elevate package built with uv2nix
{ inputs, ... }:
{
  perSystem =
    { pkgs, inputs', ... }:
    let
      elevateVenv = pkgs.callPackage ./python.nix {
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
      };

      elevateNpmLib = pkgs.callPackage ./lib.nix {
        npm-lockfile-fix = inputs'.npm-lockfile-fix.packages.default;
      };

      elevateTui = pkgs.callPackage ./tui.nix {
        inherit elevateNpmLib;
      };

      # Import bundled skills, excluding runtime caches
      bundledSkills = pkgs.lib.cleanSourceWith {
        src = ../skills;
        filter = path: _type: !(pkgs.lib.hasInfix "/index-cache/" path);
      };

      elevateWeb = pkgs.callPackage ./web.nix {
        inherit elevateNpmLib;
      };

      runtimeDeps = with pkgs; [
        nodejs_22
        ripgrep
        git
        openssh
        ffmpeg
        tirith
      ];

      runtimePath = pkgs.lib.makeBinPath runtimeDeps;

      # Lockfile hashes for dev shell stamps
      pyprojectHash = builtins.hashString "sha256" (builtins.readFile ../pyproject.toml);
      uvLockHash =
        if builtins.pathExists ../uv.lock then
          builtins.hashString "sha256" (builtins.readFile ../uv.lock)
        else
          "none";
    in
    {
      packages = {
        default = pkgs.stdenv.mkDerivation {
          pname = "elevate";
          version = (fromTOML (builtins.readFile ../pyproject.toml)).project.version;

          dontUnpack = true;
          dontBuild = true;
          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            runHook preInstall

            mkdir -p $out/share/elevate $out/bin
            cp -r ${bundledSkills} $out/share/elevate/skills
            cp -r ${elevateWeb} $out/share/elevate/web_dist

            # copy pre-built TUI (same layout as dev: ui-tui/dist/ + node_modules/)
            mkdir -p $out/ui-tui
            cp -r ${elevateTui}/lib/elevate-tui/* $out/ui-tui/

            ${pkgs.lib.concatMapStringsSep "\n"
              (name: ''
                makeWrapper ${elevateVenv}/bin/${name} $out/bin/${name} \
                  --suffix PATH : "${runtimePath}" \
                  --set ELEVATE_BUNDLED_SKILLS $out/share/elevate/skills \
                  --set ELEVATE_WEB_DIST $out/share/elevate/web_dist \
                  --set ELEVATE_TUI_DIR $out/ui-tui \
                  --set ELEVATE_PYTHON ${elevateVenv}/bin/python3 \
                  --set ELEVATE_NODE ${pkgs.nodejs_22}/bin/node
              '')
              [
                "elevate"
                "elevate-agent"
                "elevate-acp"
              ]
            }

            runHook postInstall
          '';

          passthru.devShellHook = ''
            STAMP=".nix-stamps/elevate"
            STAMP_VALUE="${pyprojectHash}:${uvLockHash}"
            if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$STAMP_VALUE" ]; then
              echo "elevate: installing Python dependencies..."
              uv venv .venv --python ${pkgs.python312}/bin/python3 2>/dev/null || true
              source .venv/bin/activate
              uv pip install -e ".[all]"
              [ -d mini-swe-agent ] && uv pip install -e ./mini-swe-agent 2>/dev/null || true
              [ -d tinker-atropos ] && uv pip install -e ./tinker-atropos 2>/dev/null || true
              mkdir -p .nix-stamps
              echo "$STAMP_VALUE" > "$STAMP"
            else
              source .venv/bin/activate
              export ELEVATE_PYTHON=${elevateVenv}/bin/python3
            fi
          '';

          meta = with pkgs.lib; {
            description = "AI agent with advanced tool-calling capabilities";
            homepage = "https://github.com/Dartagnan98/elevate-agent";
            mainProgram = "elevate";
            license = licenses.mit;
            platforms = platforms.unix;
          };
        };

        tui = elevateTui;
        web = elevateWeb;

        fix-lockfiles = elevateNpmLib.mkFixLockfiles {
          packages = [ elevateTui elevateWeb ];
        };
      };
    };
}
