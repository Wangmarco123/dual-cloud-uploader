# Local maintenance changes · 2026-11-14

Base: qjfoidnh/BaiduPCS-Go v4.0.2, commit 225bdd3b6cb298601c4d5ef7104c3e08cd1d692d.

- requester/dial.go: use a context-aware, timed Dialer for the cached address; retry the original hostname after a cached-address connection failure. Added a maintenance notice in the source header.
- requester/dial_fallback_test.go: local regression test for an unreachable cached address and hostname fallback.
- README.md and two historical API documents under docs/: replaced token-shaped public upstream examples with EXAMPLE_ACCESS_TOKEN. These were upstream documentation examples, not locally collected account credentials. The changes do not alter executable behavior.

See ../../docs/BAIDU_FIX.md and ../../patches/baidupcs-address-fallback.patch for the functional patch and validation scope.
This is a local maintenance snapshot, not a new upstream release. Apache-2.0 and upstream attribution remain in place.
