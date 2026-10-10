{
  inputs = {
    nixpkgs = {
      url = "github:nixos/nixpkgs/nixos-unstable";
    };
    flake-utils = {
      url = "github:numtide/flake-utils";
    };
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        pythonEnv = pkgs.python313.withPackages (
          ps: with ps; [
            numpy
            capstone
            keystone-engine
            evdev
            pyyaml
            pyelftools
            pyxbe
            pyghidra
          ]
        );

        crystal = pkgs.stdenvNoCC.mkDerivation {
          pname = "crystal";
          version = "unstable";

          src = pkgs.fetchFromGitHub {
            owner = "itsybitsypixel";
            repo = "crystal";
            rev = "main";
            hash = "sha256-Lw8hp8bJqt0o5Lrmll0gwPhSCrjyAipfUUIzKGPdnWs=";
          };

          installPhase = ''
            mkdir -p $out/bin
            cp -r . $out/crystal

            cat > $out/bin/crystal <<EOF
            #!${pkgs.bash}/bin/bash
            exec ${pythonEnv}/bin/python3 $out/crystal/crystal.py "\$@"
            EOF

            chmod +x $out/bin/crystal
          '';
        };
      in
      {
        packages = {
          default = crystal;
        };
        devShells = {
          default = pkgs.mkShell {
            packages = with pkgs; [
              ghidra
              jdk21
              crystal
              pythonEnv
              xxd
              ffmpeg
              git
            ];
          };
          shellHook = ''
            export JAVA_HOME="${pkgs.jdk21}/lib/openjdk"
            export PATH="$JAVA_HOME/bin:$PATH"
          '';
        };
      }
    );
}
