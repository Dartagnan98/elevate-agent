# nix/tui.nix — Elevate TUI (Ink/React) compiled with tsc and bundled
{ pkgs, elevateNpmLib, ... }:
let
  src = ../ui-tui;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-RU4qSHgJPMyfRSEJDzkG4+MReDZDc6QbTD2wisa5QE0=";
  };

  npm = elevateNpmLib.mkNpmPassthru { folder = "ui-tui"; attr = "tui"; pname = "elevate-tui"; };

  packageJson = builtins.fromJSON (builtins.readFile (src + "/package.json"));
  version = packageJson.version;
in
pkgs.buildNpmPackage (npm // {
  pname = "elevate-tui";
  inherit src npmDeps version;

  doCheck = false;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/lib/elevate-tui

    cp -r dist $out/lib/elevate-tui/dist

    # runtime node_modules
    cp -r node_modules $out/lib/elevate-tui/node_modules

    # @elevate/ink is a file: dependency, we need to copy it in fr
    rm -f $out/lib/elevate-tui/node_modules/@elevate/ink
    cp -r packages/elevate-ink $out/lib/elevate-tui/node_modules/@elevate/ink

    # package.json needed for "type": "module" resolution
    cp package.json $out/lib/elevate-tui/

    runHook postInstall
  '';
})
