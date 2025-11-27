{
  description = "A scraper that uploads Lublin district council events to google calendar";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    nur,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {
        inherit system;
      };
    in {
      devShells.default =
        pkgs.callPackage ./nix/shells/default.nix {};
      # For nix develop
      devShell = self.devShells.${system}.default;
    });
}
