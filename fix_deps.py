#!/usr/bin/env python3
"""确保 recovery ramdisk 的启动依赖闭包完整。

背景：bootable/recovery/Android.mk 被改成了链接 *_ndk（而不是 *_ndk_platform），
于是 recovery 的 DT_NEEDED 里出现 android.system.keystore2-V4-ndk.so 这类库，
它们从来没被装进 recovery ramdisk。更麻烦的是**传递依赖**：补进 V4 之后它自己又
缺 android.hardware.security.keymint-V3-ndk.so，缺一层就整机起不来。

所以这里从 system/bin/init 和 system/bin/recovery 出发做**传递闭包**：
逐层把缺的库从 out/target/product/$DEVICE 里找出来补进 ramdisk，直到收敛；
启动链上补不到的库直接让构建失败（以前就是默默产出起不来的镜像，浪费一整轮刷机）。
启动链之外的缺失（比如 openaes -> libopenaes.so，OrangeFox 也有）只告警。

用法: fix_deps.py <boot.img> <product_out_dir> [输出路径=原地]
"""
import gzip
import hashlib
import pathlib
import struct
import sys

PAD_BLOCK = 512
ROOTS = ("system/bin/recovery", "system/bin/init")
LIB_DIRS = ("system/lib64/", "vendor/lib64/", "system/lib/", "vendor/lib/")


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
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4] != 2:
        return []
    e_phoff, = struct.unpack_from("<Q", data, 0x20)
    e_phentsize, e_phnum = struct.unpack_from("<HH", data, 0x36)
    dyn = None
    loads = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, = struct.unpack_from("<I", data, o)
        p_offset, = struct.unpack_from("<Q", data, o + 8)
        p_vaddr, = struct.unpack_from("<Q", data, o + 16)
        p_filesz, = struct.unpack_from("<Q", data, o + 32)
        if p_type == 2:
            dyn = (p_offset, p_filesz)
        elif p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz))
    if dyn is None:
        return []
    off, size = dyn
    needed, strtab = [], None
    for j in range(0, size - 15, 16):
        tag, val = struct.unpack_from("<qQ", data, off + j)
        if tag == 0:
            break
        if tag == 1:
            needed.append(val)
        elif tag == 5:
            strtab = val
    if strtab is None or not needed:
        return []
    foff = None
    for vaddr, offset, filesz in loads:
        if vaddr <= strtab < vaddr + filesz:
            foff = offset + (strtab - vaddr)
            break
    if foff is None:
        return []
    names = []
    for n in needed:
        try:
            end = data.index(b"\0", foff + n)
        except ValueError:
            continue
        names.append(data[foff + n:end].decode("utf-8", "replace"))
    return names


def main():
    src = sys.argv[1]
    product_out = pathlib.Path(sys.argv[2])
    dst = sys.argv[3] if len(sys.argv) > 3 else src

    img = bytearray(open(src, "rb").read())
    total = len(img)
    page = struct.unpack_from("<I", img, 36)[0]
    assert struct.unpack_from("<I", img, 40)[0] == 2, "only boot header v2"
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

    def find_lib(name):
        for d in ("system/lib64", "vendor/lib64", "system/lib", "vendor/lib", "system_ext/lib64"):
            p = product_out / d / name
            if p.is_file():
                return p
        for pat in ("system/apex/*/lib64/" + name,
                    "system/apex/*/*/lib64/" + name,
                    "system/apex/*/*/*/lib64/" + name):
            for p in sorted(product_out.glob(pat)):
                if p.is_file():
                    return p
        return None

    tmpl = next((e for n, e in by_name.items()
                 if n.startswith("system/lib64/") and n.endswith(".so") and e["data"]), None)
    if tmpl is None:
        print("ERROR: no system/lib64/*.so in ramdisk to use as a template", file=sys.stderr)
        return 1

    lib_path_of = {}
    for n in by_name:
        if n.startswith(LIB_DIRS):
            lib_path_of.setdefault(n.split("/")[-1], n)
    injected, missing_boot = [], []

    # 从 roots 做 BFS，只沿启动链
    queue = [r for r in ROOTS if r in by_name]
    seen = set()
    while queue:
        cur = queue.pop(0)
        if cur in seen or cur not in by_name:
            continue
        seen.add(cur)
        for lib in elf_needed(by_name[cur]["data"]):
            if lib in lib_path_of:
                queue.append(lib_path_of[lib])
                continue
            src_lib = find_lib(lib)
            if src_lib is None:
                missing_boot.append("%s (needed by %s)" % (lib, cur))
                continue
            fields = list(tmpl["fields"])
            fields[11] = 0
            entries.insert(len(entries) - 1,
                           {"fields": fields, "name": "system/lib64/" + lib,
                            "data": src_lib.read_bytes()})
            by_name["system/lib64/" + lib] = entries[-2]
            lib_path_of[lib] = "system/lib64/" + lib
            injected.append(lib)
            queue.append("system/lib64/" + lib)

    # 启动链之外的缺失只告警
    warn = []
    for name, e in by_name.items():
        if name in seen or not e["data"][:4] == b"\x7fELF":
            continue
        for lib in elf_needed(e["data"]):
            if lib not in lib_path_of:
                warn.append("%s -> %s" % (name, lib))

    print("injected %d lib(s): %s" % (len(injected), ", ".join(injected) or "none"))
    if warn:
        print("warnings (not on the boot chain):")
        for w in sorted(set(warn))[:10]:
            print("   ", w)

    if missing_boot:
        print("\nERROR: boot chain is incomplete, refusing to ship a dead image:",
              file=sys.stderr)
        for m in missing_boot:
            print("   ", m, file=sys.stderr)
        return 1

    if not injected:
        print("boot chain already complete - nothing to do")
        return 0

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
