# Changelog

All notable changes to Hyprprem are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## Unreleased

### Added
- Accounts have a role: viewers read everything, editors also change the documentation, admins also manage users and the instance. Admins pick the role per user and the role new accounts start with

### Changed
- Documentation belongs to the instance rather than to the account that wrote it; deleting an account keeps it
- Sign-up is off on a fresh install

## [0.1.0] — 2026-09-25

### Added
- The first version, started from the Hyprlab Flask template
