# Security

Report reproducible security issues privately to aliafacan.dev@gmail.com. Include
the affected version, provider, distribution, reproduction steps and expected
behavior. Remove credentials, personal paths and private repository tokens from logs.

Scope includes package command construction, archive extraction, portable ownership,
credentials, desktop integration and local metadata parsing. Acknowledgement and
response times depend on maintainer availability; no guaranteed service window is claimed.

SourceDock runs as the normal desktop user. Native package operations request limited
administrative access. Credentials are kept in memory, passed to sudo on stdin,
redacted from diagnostics and cleared after the operation. GUI execution as root is refused.

Local files are unverified unless an actual verification mechanism proves otherwise.
The release SHA-256 file checks the downloaded DEB's integrity; it is not a digital
signature and must not be described as signer or publisher authentication.
AppImage inspection never executes the file. An installed AppImage is not guaranteed
to be sandboxed. Portable removal requires matching ownership records and manifests.

Automated tests use disposable directories and mocked privileged commands. They do
not install, remove or update the host system's packages. See [Authorization](docs/AUTHORIZATION.md).
