{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    git
    pandoc
    (python3.withPackages (ps: [ ps.ansi2html ps.pyyaml ]))
    qpdf  # zlib-deflate
    texlive.combined.scheme-full
    xxd
  ];
}

