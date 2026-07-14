# Items before v2.6.0 PR is ready

Punch list to clear before merging to `main`. Update as work lands.

## 1. Sidebar restructure and lock-ins

- [x] SDK introduction migration: `5cc2b21c`
- [x] Home tab sidebar restructure: `5cc2b21c`
- [x] Runtime section polish: `3b11607a`
- [x] Demo OS polish: `8aa9edeb`
- [x] Dash tutorial polish: `75cd7fd6`
- [x] Coda tutorial polish: `7f9814b0`
- [x] Blank Canvas pages: `f7f71392`
- [x] Homepage opener refinement: `930085b0`
- [x] Scout tutorial tightening: `1c9d0807`

## 2. Cleanup

- [x] Drop `_legacy/production/*` and `TBD/2_6_remove/` orphans (46 files): `7a6cc9b4`
- [x] Refresh `connect-agent-os-ui` snippet: `07123216`
- [x] Add `agentos-api-scroll` demo video: `43baf92a`
- [x] Fix CI broken links: `609bacfa`

## 3. Verify before merge

- [ ] Confirm `first-agent.mdx` video substitutions are the intended clips:
  - `/videos/agent-os-connect-os.mp4` (was `agentos-connect-workbench.mp4`)
  - `/videos/agentos-agent-chat.mp4` (was `agentos-chat-workbench.mp4`)
- [ ] `videos/agentos-api-scroll.mp4` is 73 MB. GitHub flagged it as above the 50 MB recommended limit. Consider Git LFS or compression before merge.
