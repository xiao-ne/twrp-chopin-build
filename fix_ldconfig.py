#!/usr/bin/env python3
"""修复 boot.img 里 0 字节的 linkerconfig/ld.config.txt。

TWRP (twrp-14.1) 这棵树打出来的 recovery ramdisk 里，linkerconfig/ld.config.txt
是 0 字节，而原厂 ramdisk 根本没有这个文件（只有 system/etc/ld.config.txt）。
动态链接器只要发现 /linkerconfig/ld.config.txt 存在，就拿它当完整配置；空文件
= 没有任何 namespace，连 libc.so 都找不到，于是 /system/bin/init 起不来，内核
报 "No working init found" 直接 panic 重启 —— init_fatal_reboot_target 是 init
层的参数，管不到内核这一步。

修法：把 ramdisk 里那份真正的 system/etc/ld.config.txt 填进 linkerconfig/ld.config.txt。

用法: fix_ldconfig.py <boot.img> <输出路径>
"""
import gzip
import hashlib
import struct
import sys

SRC = "linkerconfig/ld.config.txt"
DONOR = "system/etc/ld.config.txt"
PAD_BLOCK = 512


def read_entries(rd):
    entries = []
    pos = 0
    while pos + 110 <= len(rd):
        if rd[pos:pos + 6] != b"070701":
            break
        f = [int(rd[pos + 6 + 8 * i:pos + 6 + 8 * (i + 1)], 16) for i in range(13)]
        namesize = f[11]
        filesize = f[6]
        name = rd[pos + 110:pos + 110 + namesize - 1].decode("utf-8", "replace")
        body_at = (pos + 110 + namesize + 3) // 4 * 4
        data = rd[body_at:body_at + filesize]
        entries.append({"fields": f, "name": name, "data": data})
        pos = (body_at + filesize + 3) // 4 * 4
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
        out += b"070701"
        out += b"".join(b"%08X" % v for v in f)
        out += name + b"\0"
        out += b"\0" * ((4 - len(out) % 4) % 4)
        out += data
        out += b"\0" * ((4 - len(out) % 4) % 4)
    while len(out) % PAD_BLOCK:
        out += b"\0"
    return bytes(out)


def main():
    src_path, out_path = sys.argv[1], sys.argv[2]
    img = bytearray(open(src_path, "rb").read())
    total = len(img)

    page = struct.unpack_from("<I", img, 36)[0]
    hdrver = struct.unpack_from("<I", img, 40)[0]
    assert hdrver == 2, "only boot header v2 is handled"
    ks = struct.unpack_from("<I", img, 8)[0]
    rs = struct.unpack_from("<I", img, 16)[0]
    dtb_size = struct.unpack_from("<I", img, 1648)[0]

    koff = page
    roff = koff + (ks + page - 1) // page * page
    doff = roff + (rs + page - 1) // page * page
    kernel = bytes(img[koff:koff + ks])
    ramdisk = bytes(img[roff:roff + rs])
    dtb = bytes(img[doff:doff + dtb_size])

    rd = gzip.decompress(ramdisk)
    entries = read_entries(rd)
    by_name = {e["name"]: e for e in entries}
    if SRC not in by_name:
        print("no %s in ramdisk - nothing to do" % SRC)
        return 0
    if DONOR not in by_name:
        print("no %s in ramdisk - cannot repair" % DONOR, file=sys.stderr)
        return 1

    donor = by_name[DONOR]["data"]
    if not donor:
        print("%s is empty - cannot repair" % DONOR, file=sys.stderr)
        return 1

    before = len(by_name[SRC]["data"])
    by_name[SRC]["data"] = donor
    print("%s: %d -> %d bytes" % (SRC, before, len(donor)))

    new_rd = write_entries(entries)
    new_gz = gzip.compress(new_rd, 9)
    print("ramdisk: %d unpacked, %d -> %d bytes gzip" % (len(new_rd), rs, len(new_gz)))

    header = bytearray(img[:page])
    struct.pack_into("<I", header, 16, len(new_gz))
    digest = hashlib.sha1()
    digest.update(kernel)
    digest.update(struct.pack("<I", len(kernel)))
    digest.update(new_gz)
    digest.update(struct.pack("<I", len(new_gz)))
    header[576:596] = digest.digest()  # 20 字节 sha1，id 字段剩 12 字节保持 0
    assert len(header) == page, "header shrank: %d != %d" % (len(header), page)

    out = bytearray(header)
    out += kernel + b"\0" * ((page - len(kernel) % page) % page)
    out += new_gz + b"\0" * ((page - len(new_gz) % page) % page)
    out += dtb + b"\0" * ((page - len(dtb) % page) % page)
    if len(out) < total:
        out += b"\0" * (total - len(out))
    elif len(out) > total:
        print("ERROR: new image %d exceeds partition %d" % (len(out), total), file=sys.stderr)
        return 1

    open(out_path, "wb").write(bytes(out))
    print("written %s (%d bytes)" % (out_path, len(out)))
    print("sha256: %s" % hashlib.sha256(bytes(out)).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
