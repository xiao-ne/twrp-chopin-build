# TWRP Build for Redmi Note 10 Pro (chopin)

Automated TWRP build using GitHub Actions.

## Device

- Redmi Note 10 Pro (chopin), MT6891Z / Dimensity 1100
- The tree mounts as `device/xiaomi/ares` and lunches `twrp_ares-ap2a-userdebug`.
  Those names are build plumbing inherited from the ares tree; renaming them
  means changing the local manifest, the lunch target and the artifact paths in
  `build.yml` together.

## What gets built

`BOARD_USES_RECOVERY_AS_BOOT` is true and `TARGET_NO_RECOVERY` is set, so this
device has no recovery partition and the flashable artifact is **`boot.img`**.
`recovery.img` may not exist at all. Flash it to the boot partition of the
active slot, in fastboot:

```sh
fastboot flash boot_a boot.img
fastboot reboot recovery
```

The workflow fails if neither `boot.img` nor `recovery.img` was produced, so a
green run means there is something to flash.

## Kernel

`prebuilt/kernel` and `prebuilt/dtb.img` come from the device tree, not from
this repo. They are currently the chopin A17 kernel (`4.14.336-@Xiaonai-@`) and
the device's own dtbo blob.

To refresh the kernel after rebuilding it in `xiaomi_kernel_chopin`:

```sh
# in the kernel tree, on branch backport-4.14.336-A17
./recovery/make-prebuilt.sh --image out/arch/arm64/boot/Image \
    --out ~/chopin_twrp_device/prebuilt --kernel-only
```

`--kernel-only` is deliberate: the dtb is fixed for this device and does not
need regenerating.

## Decryption

The tree carries the TEE chain (`keymaster@4.0-service.mitee`, `beanpod`,
`tee-supplicant`, `teei_daemon`) plus a `/data` line with
`fileencryption=aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized` and
`keydirectory=/metadata/vold/metadata_encryption`. Whether that actually
decrypts on the device is not yet verified.

## History

This repo was reduced to a single commit. The long trail of build fixes it used
to carry distilled to the following, which is why `build.yml` patches `libtar`
the way it does:

- `bootable/recovery/libtar` does not compile against Android 14+ headers: its
  `fscrypt_policy` macro and policy helpers clash. What held was
  `#undef USE_FSCRYPT` at the top of `append.c` and `block.c`, plus changing
  `fscrypt_policy *fep` to `struct fscrypt_policy_v1 *fep` in `libtar.h`.
  Earlier attempts — deleting lines, sed line ranges, regex-driven Python
  patchers — all broke again on the next source sync.
- libtar's `Android.mk` referenced `-ndk_platform` variants that no longer
  exist; they are renamed to the current `-ndk` / `-V4-ndk` names.
- The `gsi_keys` inherit is stripped because the TWRP minimal manifest does not
  ship `gsi_keys.mk`.

## Build

Triggered on push to `main`, or manually via workflow_dispatch in the Actions
tab. Artifacts are kept for 30 days.
