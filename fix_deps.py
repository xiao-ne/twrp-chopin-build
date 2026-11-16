#!/usr/bin/env python3
"""确保 recovery ramdisk 里所有 DT_NEEDED 库都在，缺的从构建树补进去。

起因：bootable/recovery/Android.mk 被改成了链接 android.system.keystore2-V4-ndk，
recovery 二进制的 DT_NEEDED 里因此记下 android.system.keystore2-V4-ndk.so，但这个库
从来没被装进 recovery ramdisk（只有 -ndk_platform 那套）。链接器在 main() 之前就
报 "library not found"，recovery 起不来，整机硬循环，连日志都不留。

与其追着模块命名改，不如在产物上兜底：解包 ramdisk，把 system/bin/{recovery,init}
的 DT_NEEDED 全部核对一遍，缺的从 out/target/product/$DEVICE/system/lib64/ 拷进来。
拷不到就让构建失败并打印清单，不要产出起不来的镜像。

用法: fix_deps.py <boot.img> <product_out_dir> [输出路径=原地]
"""
import gzip
import hashlib
import pathlib
import struct
import sys

PAD_BLOCK = 512
BINARIES = ("system/bin/recovery", "system/bin/init")


def read_entries(rd):
    entries = []
    pos = 0
    while pos + 110 <= len(rd):
        if rd[pos:pos + 6] != b"070701":
            break
        f = [int(rd[pos + 6 + 8 * i:pos + 6 + 8 * (i + 1)], 16) for i in range(13)]
        namesize, filesize = f[11], f[6]
        name = rd[pos + 110:pos + 110 + namesize - 1].decode("utf-8", "replace")
        body = (pos + 110 + namesize + 3) // 4 * 4
        entries.append({"fields": f, "name": name, "data": rd[body:body + filesize]})
        pos = (body + filesize + 3) // 4 * 4
        if name == "TRAILER!!!":
            break
    return entries


def write_entries(entries):
    out = bytearray()
    for e in entries:
        f = list(e["fields"])
        name = e["name"].encode()
        data = e["data"]
        f[6] = len(data)
        f[11] = len(name) + 1
        out += b"070701" + b"".join(b"%08X" % v for v in f)
        out += name + b"\0"
        out += b"\0" * ((4 - len(out) % 4) % 4)
        out += data
        out += b"\0" * ((4 - len(out) % 4) % 4)
    while len(out) % PAD_BLOCK:
        out += b"\0"
    return bytes(out)


def elf_needed(data):
    if data[:4] != b"\x7fELF" or data[4] != 2:
        return []
    e_phoff, = struct.unpack_from("<Q", data, 0x20)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    dyn = None
    load = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, = struct.unpack_from("<I", data, o)
        p_offset, = struct.unpack_from("<Q", data, o + 8)
        p_vaddr, = struct.unpack_from("<Q", data, o + 16)
        p_filesz, = struct.unpack_from("<Q", data, o + 32)
        if p_type == 2:
            dyn = (p_offset, p_filesz)
        elif p_type == 1:
            load.append((p_vaddr, p_offset, p_filesz))
    if dyn is None:
        return []
    needed, strtab = [], None
    off, size = dyn
    for j in range(0, size, 16):
        tag, val = struct.unpack_from("<qQ", data, off + j)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        elif tag == 5:
            strtab = val
    if strtab is None:
        return []
    foff = None
    for vaddr, offset, filesz in load:
        if vaddr <= strtab < vaddr + filesz:
            foff = offset + (strtab - vaddr)
            break
    if foff is None:
        return []
    names = []
    for n in needed:
        end = data.index(b"\0", foff + n)
        names.append(data[foff + n:end].decode())
    return names


def main():
    src = sys.argv[1]
    product_out = pathlib.Path(sys.argv[2])
    dst = sys.argv[3] if len(sys.argv) > 3 else src

    img = bytearray(open(src, "rb").read())
    total = len(img)
    page = struct.unpack_from("<I", img, 36)[0]
    assert struct.unpack_from("<I", img, 40)[0] == 2
    ks = struct.unpack_from("<I", img, 8)[0]
    rs = struct.unpack_from("<I", img, 16)[0]
    dtb_size = struct.unpack_from("<I", img, 1648)[0]

    koff = page
    roff = koff + (ks + page - 1) // page * page
    doff = roff + (rs + page - 1) // page * page
    kernel = bytes(img[koff:koff + ks])
    ramdisk = bytes(img[roff:roff + rs])
    dtb = bytes(img[doff:doff + dtb_size])
    assert ramdisk[:2] == b"\x1f\x8b", "expect gzip ramdisk"

    rd = gzip.decompress(ramdisk)
    entries = read_entries(rd)
    by_name = {e["name"]: e for e in entries}

    # 从现有库拿一个模板（uid/gid/mode/时间戳）
    lib_dir = "system/lib64/"
    tmpl = next((e for n, e in by_name.items()
                 if n.startswith(lib_dir) and n.endswith(".so") and e["data"]), None)
    if tmpl is None:
        print("ERROR: ramdisk has no system/lib64/*.so to use as a template",
              file=sys.stderr)
        return 1

    def find_lib(name):
        for p in (product_out / "system/lib64" / name,
                  product_out / "vendor/lib64" / name,
                  product_out / "system_ext/lib64" / name):
            if p.is_file():
                return p
        for pat in ("system/apex/*/lib64/" + name,
                    "system/apex/*/*/lib64/" + name,
                    "system/apex/*/*/*/lib64/" + name):
            for p in sorted(product_out.glob(pat)):
                if p.is_file():
                    return p
        return None

    added, missing_hard = [], []
    present = {n.split("/")[-1] for n in by_name
               if n.startswith("system/lib64/") or n.startswith("vendor/lib64/")}
    for binary in BINARIES:
        e = by_name.get(binary)
        if not e or not e["data"]:
            print("skip %s (absent)" % binary)
            continue
        for lib in elf_needed(e["data"]):
            if lib in present:
                continue
            src_lib = find_lib(lib)
            if src_lib is None:
                missing_hard.append("%s (needed by %s)" % (lib, binary))
                continue
            fields = list(tmpl["fields"])
            fields[11] = 0
            entries.insert(len(entries) - 1, {
                "fields": fields,
                "name": lib_dir + lib,
                "data": src_lib.read_bytes(),
            })
            present.add(lib)
            added.append(lib)

    if not added and not missing_hard:
        print("all DT_NEEDED libs already present - nothing to do")
        return 0

    for lib in added:
        print("added %s%s" % (lib_dir, lib))
    if missing_hard:
        print("\nERROR: cannot resolve these libraries:", file=sys.stderr)
        for m in missing_hard:
            print("   ", m, file=sys.stderr)
        return 1

    new_rd = write_entries(entries)
    new_gz = gzip.compress(new_rd, 9)
    header = bytearray(img[:page])
    struct.pack_into("<I", header, 16, len(new_gz))
    d = hashlib.sha1()
    d.update(kernel)
    d.update(struct.pack("<I", len(kernel)))
    d.update(new_gz)
    d.update(struct.pack("<I", len(new_gz)))
    header[576:596] = d.digest()
    assert len(header) == page

    out = bytearray(header)
    out += kernel + b"\0" * ((page - len(kernel) % page) % page)
    out += new_gz + b"\0" * ((page - len(new_gz) % page) % page)
    out += dtb + b"\0" * ((page - len(dtb) % page) % page)
    if len(out) < total:
        out += b"\0" * (total - len(out))
    elif len(out) > total:
        print("ERROR: image grew to %d > %d" % (len(out), total), file=sys.stderr)
        return 1

    open(dst, "wb").write(bytes(out))
    print("written %s (%d bytes, ramdisk gzip %d)" % (dst, len(out), len(new_gz)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
