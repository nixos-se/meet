{
  lib,
  stdenvNoCC,
  tailwindcss_4,
  venv,
}:

stdenvNoCC.mkDerivation {
  name = "nixos-se-meet-site";

  src = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./site.toml
      ./venues.toml
      ./speakers.toml
      ./meetups
      ./templates
      ./static
    ];
  };

  nativeBuildInputs = [
    venv
    tailwindcss_4
  ];

  buildPhase = ''
    runHook preBuild
    meet-build --output "$out"
    runHook postBuild
  '';

  dontInstall = true;
}
