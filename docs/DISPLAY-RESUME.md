<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Display blank/resume glitch: DSI timeout + FIFO error

## Symptom

After the screen has been idle/locked, the top of the display may show a clock
band, then the panel turns into noise/bands. Turning the screen off and on again
restores a normal Plasma image. The GPU/DPU continue to work; this is a display
link recovery problem, not a dead panel or GPU.

## Evidence

`dmesg` around the event:

```text
panel-xiaomi-umi ae94000.dsi.0: mode: 1080x2340@60, 1112x3532 total, 235655 kHz
dsi_err_worker: status=5
dsi_err_worker: status=5
... (repeated)
panel-xiaomi-umi ae94000.dsi.0: off-sequence: sent 3 packets / 27 bytes
panel-xiaomi-umi ae94000.dsi.0: prepare 1080x2340@60Hz (DSC)
panel-xiaomi-umi ae94000.dsi.0: on-sequence: sent 32 packets / 404 bytes
```

`status=5` is the `msm` DSI error bitmask:

```c
#define DSI_ERR_STATE_ACK              0x0000
#define DSI_ERR_STATE_TIMEOUT          0x0001
#define DSI_ERR_STATE_DLN0_PHY         0x0002
#define DSI_ERR_STATE_FIFO             0x0004
#define DSI_ERR_STATE_MDP_FIFO_UNDERFLOW 0x0008
#define DSI_ERR_STATE_INTERLEAVE_OP_CONTENTION 0x0010
#define DSI_ERR_STATE_PLL_UNLOCKED     0x0020
```

So `0x5` = `TIMEOUT | FIFO`.

## Why it does not self-heal

`drivers/gpu/drm/msm/dsi/dsi_host.c:dsi_err_worker()` only performs a software
reset for `MDP_FIFO_UNDERFLOW`:

```c
if (status & DSI_ERR_STATE_MDP_FIFO_UNDERFLOW)
    dsi_sw_reset(msm_host);
```

The `TIMEOUT | FIFO` combination is logged and the interrupt is re-enabled, but
the DSI link is not reset. The command-mode DSC panel remains desynchronised;
the framebuffer gets corrupted until the panel is power-cycled/off-on, which
re-runs the 32-packet on-sequence (and PPS setup).

This is a driver recovery gap, not a GPU fault. It appeared on the Samsung panel
variant after the screen had been blanked/locked.

## Workaround used

- Disable the Plasma automatic locker (`~umi/.config/kscreenlockerrc`):

  ```ini
  [Daemon]
  Autolock=false
  LockOnResume=false
  ```

- In Plasma Power Management set **Screen Energy Saving = Never** and
  **Suspend Session = Never** for the AC/USB profile. The device is normally on
  a charger; keeping the panel awake avoids the blank/resume trigger.
- If the glitch appears anyway, turn the screen off/on once; that replays the
  panel init and restores the image.

## Possible proper fix (not applied)

- In `dsi_err_worker()`, also reset on `TIMEOUT | FIFO` (or all errors), and/or
  notify the panel to re-run its on-sequence/PPS after the reset. The host
  worker currently has no panel context, so a panel-level recovery hook or a
  DRM panel notifier would be needed. This is not upstream and was not tested.

## Relation to the other issues

- This is separate from the UFS LPM panic ([UFS-LPM.md](UFS-LPM.md)) and from the
  ath11k scan abort ([WIFI-WORKAROUND.md](WIFI-WORKAROUND.md)).
- `dpu_encoder_frame_done_timeout` was zero on the working UFS/kernel setup;
  the corruption here comes from the DSI error path, not the DPU frame-done
  timeout seen after the earlier crashes.
