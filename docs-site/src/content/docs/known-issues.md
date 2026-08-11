---
title: Known Issues
---# Known Issues

## OAuth Token Expiry

**Symptoms:** The provider stops working after several days or weeks with no obvious configuration errors.

**Cause:** FastMCP Server OAuth tokens have a limited lifetime. After expiry, the provider loses API access.

**Fix:** Re-authorise in the provider settings: remove the current configuration, add the provider again, and complete the authorisation flow.

---

## API Disconnects During Long Sessions

**Symptoms:** Playback stops or tracks fail to load after several hours of use.

**Cause:** The FastMCP Server API closes long-lived connections. This is upstream service behaviour.

**Fix:** Restart Music Assistant or reconnect the provider. The error resolves itself on the next request.

---

## Geo-Restricted Playlists and Tracks

**Symptoms:** Some playlists or tracks are unavailable even though they open fine in the FastMCP Server app.

**Cause:** Certain content is restricted by geography or subscription tier.

**Fix:** Content blocked by geo-restrictions or subscription limits cannot be played through the provider. This is a FastMCP Server-side limitation.

---

## Multiple Accounts Not Yet Supported

**Symptoms:** Adding a second FastMCP Server account causes the first to stop working.

**Cause:** The provider currently supports only one FastMCP Server account.

**Fix:** Use a single account. Multi-account support is planned for a future release.
