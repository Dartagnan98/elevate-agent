# nix/web.nix — Elevate Web Dashboard (Vite/React) frontend build
{ pkgs, elevateNpmLib, ... }:
let
  src = ../web;
  npmDeps = pkgs.fetchNpmDeps {
    inherit src;
    hash = "sha256-TS/vrCHbdvXkPcAPxImKzAd2pdDCrKlgYZkXBMQ+TEg=";
  };

  npm = elevateNpmLib.mkNpmPassthru { folder = "web"; attr = "web"; pname = "elevate-web"; };
in
pkgs.buildNpmPackage (npm // {
  pname = "elevate-web";
  version = "0.0.0";
  inherit src npmDeps;

  doCheck = false;

  buildPhase = ''
    npx tsc -b
    npx vite build --outDir dist
  '';

  installPhase = ''
    runHook preInstall
    cp -r dist $out
    runHook postInstall
  '';
})
