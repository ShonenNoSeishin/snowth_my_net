---
name: docker-hardened-check
description: Build the snowth_my_net image and prove a change works under the production hardening (non-root, no capabilities, read-only filesystem). Use after touching the Dockerfile, adding a system tool such as nmap, or a feature that spawns processes or writes files.
---

# docker-hardened-check

The compose services run `read_only`, `cap_drop: ALL`, `no-new-privileges`, user 10001, with tmpfs for writable paths (see `compose.yml`). A feature that works on the host can still fail there, so test in that shape.

1. `docker build -q -t snowth_my_net:check .`
2. Run the command under the same constraints:
   ```
   docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges:true \
     --user 10001:10001 --tmpfs /tmp --entrypoint snowth_my_net snowth_my_net:check <args>
   ```
   Add `-v` mounts for config/state the way `compose.yml` does when the command needs them.
3. For a scan: start a throwaway server in another container on a user network, scan its address, and confirm the result (`scan <ip> --profile quick`, then `show scans`). Test the empty case too: an address with nothing open must say "ok" with no ports, never "down" by accident.
4. Report exactly what ran and what did not (the live network is never reachable from here).

Never run a scan against anything but a container you started yourself.
